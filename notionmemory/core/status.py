"""온보딩 상태 probe — PAT 연결(live verify)·calendar/memory 바인딩·library 색인 나이를
한 곳에서 집계한다. `notionmemory status` CLI, SessionStart 훅의 library 넛지, 에이전트의
PAT 완료 재확인이 전부 `probe()` 하나를 공유한다(source of truth) —
docs/superpowers/specs/2026-07-29-connection-onboarding-design.md §2.

**조회 불변식: DB를 절대 만들지 않는다.** 하는 일은 셋뿐이다 — config 읽기
(`SkillMeta.get_meta`), PAT live-verify 정확히 한 번(`NotionIntegration.test`), 로컬
색인 파일 읽기(`skills/library/index.py`). `ensure(create=True)`/`POST /databases` 없음.

기본은 `NotionIntegration.status()`가 아니라 `.test()`다 — `.status()`는 PAT 존재만
보고 네트워크를 타지 않는다(대시보드 목록처럼 매 로드마다 부르기엔 그게 맞다). `.test()`만
`load_pat()` 뒤에 `verify_token()`으로 실제로 살아있는 토큰인지 확인한다 — `notionmemory
status` CLI·에이전트의 PAT 완료 게이팅이 요구하는 "live verify"는 이쪽이다.

**단, `verify=False` 는 `.status()`(네트워크 0)로 떨어진다.** SessionStart 훅처럼 세션마다
도는 호출부는 라이브 HTTP 왕복을 감당할 수 없다(`tests/hooks/test_session_start_library.py`
의 `test_injection_makes_no_network_call` 이 이미 이 불변식을 지킨다) — 넛지 판정에는
"PAT 가 있는가"만으로 충분하고, 진짜 유효성 재확인은 CLI/게이팅 쪽 `verify=True` 호출이
맡는다.
"""
from __future__ import annotations

from notionmemory.core import notion_auth  # noqa: F401 — 미사용처럼 보여도 필요:
# `NotionIntegration.test()`가 호출 시점에 이 모듈 객체의 `load_pat` 속성을 조회하므로,
# 테스트가 `status.notion_auth.load_pat`을 monkeypatch 하려면 이 이름이 여기 있어야 한다.
from notionmemory.core.config import SkillMeta
from notionmemory.core.i18n import language, tui
from notionmemory.core.integrations import NotionIntegration
from notionmemory.skills.calendar.notion_db import db_url as cal_url
from notionmemory.skills.memory.notion_db import db_url as mem_url


def _binding(config, skill_id: str, url_fn) -> dict:
    """config 에 적힌 database_id 만 읽는다 — 네트워크 0, DB 생성 0."""
    meta = SkillMeta(config, skill_id)
    dbid = meta.get_meta("database_id")
    return {"bound": bool(dbid), "url": url_fn(dbid) if dbid else ""}


def library_state() -> dict:
    """library 색인의 3갈래 판정(미갱신/빈/색인됨)을 계산 — `hooks/session_start.py`의
    `library_injection()`과 이 모듈의 `_library_index()`가 이 하나를 공유한다(중복
    구현 금지, 계약: task-3 브리프). 로컬 색인 파일만 읽는다(네트워크 0).

    반환: {"refreshed": bool, "count": int, "watermark": str}
    `refreshed`=False 면 count/watermark 는 의미가 없어 항상 0/"" 로 고정한다."""
    from notionmemory.skills.library import index as library_index
    idx = library_index.load()
    refreshed = library_index.was_refreshed(idx)
    return {
        "refreshed": refreshed,
        "count": library_index.count(idx) if refreshed else 0,
        "watermark": library_index.watermark(idx) if refreshed else "",
    }


def _library_index(config) -> tuple[bool, str]:
    """(indexed, detail). 색인 미존재(한 번도 refresh 안 됨) 또는 빈 색인(refresh 는
    됐지만 공유 페이지 0개)이면 둘 다 indexed=False — detail 이 둘을 구분해 보여준다."""
    lang = language(config)
    st = library_state()
    if not st["refreshed"]:
        return False, tui(lang, "ui.status.library.never",
                          "not scanned yet — run `notionmemory library refresh --full`")
    if not st["count"]:
        return False, tui(lang, "ui.status.library.empty",
                          "0 pages scanned (no pages shared with the integration yet)")
    wm = st["watermark"] or tui(lang, "ui.status.library.watermark_unknown", "(unknown)")
    return True, tui(lang, "ui.status.library.count", "{n} page(s), last refreshed {watermark}",
                     n=st["count"], watermark=wm)


def probe(config, *, verify: bool = True) -> dict:
    """{"notion": {"connected", "detail"}, "calendar": {"bound", "url"},
    "memory": {"bound", "url"}, "library": {"indexed", "detail"}}.

    `verify=True`(기본) — `NotionIntegration.test()`: PAT load + live `verify_token()`,
    유일한 네트워크 호출(`notionmemory status` CLI·PAT 게이팅용).
    `verify=False` — `NotionIntegration.status()`: PAT 존재만 확인, 네트워크 0
    (SessionStart 처럼 세션마다 도는 넛지용)."""
    integ = NotionIntegration()
    ns = integ.test(config) if verify else integ.status(config)
    indexed, detail = _library_index(config)
    return {
        "notion": {"connected": ns.connected, "detail": ns.detail},
        "calendar": _binding(config, "calendar", cal_url),
        "memory": _binding(config, "memory", mem_url),
        "library": {"indexed": indexed, "detail": detail},
    }
