#!/usr/bin/env python3
"""SessionStart 훅 — 현 프로젝트의 memory 컨텍스트(브리프+고Strength+pending nudge)를
세션 시작에 주입.

Claude Code / Codex 공용. 어떤 실패도 조용히 무시한다(세션 시작을 막지 않음).
등록은 `notionmemory install` 이 수행한다(매니페스트의 훅 아티팩트 → JsonHookBlock).

Second Brain v2 Phase 2a Task 5 — 옛 `recall --project`(최근 5건, 서브프로세스 재호출)를
대체했다: (a) 프로젝트 브리프(consolidation 이 롤업, 있으면) (b) 고Strength Active
메모리 top-K(있으면) (c) 미정리 Draft 가 쌓여 있으면 consolidate 안내(`memory_injection`).
"""
from __future__ import annotations

import json
import subprocess  # noqa: F401 — 실제 로직은 core.projects 로 옮겼지만(I2), 기존
                    # 테스트가 `session_start.subprocess.run` 을 monkeypatch 한다(같은
                    # sys.modules 싱글턴이라 core.projects 쪽에서도 그대로 반영된다) —
                    # 이 임포트를 지우면 그 monkeypatch 경로가 AttributeError로 깨진다.
import sys
from datetime import datetime, timezone
from pathlib import Path

from notionmemory.core import paths
from notionmemory.core.projects import resolve_project, resolve_toplevel
from notionmemory.hooks.common import capture_mode, consolidate_guard
from notionmemory.skills.memory import consolidation_queue as cq

# 훅이 안내 문구에 넣는 명령 이름 — 사용자가 그대로 따라 칠 수 있어야 하므로 맨 이름을 쓴다.
CLI = "notionmemory"
# 고Strength 게이트/상한 — 세션 헤더에 넣을 만큼 확실한 것만, 개수는 작게(노이즈 억제).
MEMORY_MIN_STRENGTH = 8
MEMORY_TOP_LIMIT = 3


def _lang() -> str:
    """config 의 language 로 훅 문구 언어를 정한다(기본 en). 실패해도 en 폴백."""
    try:
        from notionmemory.core import i18n
        from notionmemory.core.config import Config
        return i18n.language(Config.load(str(paths.config_path())))
    except Exception:
        return "en"


def _m(key: str, **fmt) -> str:
    from notionmemory.core import i18n, messages
    return i18n.t(messages.CATALOG, key, _lang(), **fmt)


# resolve_toplevel/resolve_project 는 이제 `notionmemory.core.projects` 가 원본이다
# (I2 — transcripts.collect_excerpts 도 같은 판정이 필요해져 core 로 옮겼다). 여기서는
# 재-임포트만 해 하위호환을 지킨다 — 기존 `monkeypatch.setattr(session_start,
# "resolve_toplevel", ...)` 테스트들이 그대로 동작한다.


def git_queue_reminder(toplevel: str) -> str:
    """이 리포의 미처리 커밋 큐 안내. 없으면 "".

    `toplevel` 은 main() 이 이미 구한 값을 받는다 — 여기서 다시 `git rev-parse` 를
    돌면 세션 시작마다 서브프로세스가 하나 더 는다.

    save_reminder(Stop/PreCompact)에서 옮겨왔다. Stop 에는 컨텍스트 주입 채널이 없어
    이 안내가 에이전트에게 전달된 적이 없고(사람에게만 `warning:` 으로 보였다), 그래서
    큐가 42건까지 쌓였다. SessionStart 는 주입이 실증된 유일한 채널이고, 턴 **시작**
    시점이라 에이전트가 실제로 처리할 여지가 있다.
    """
    top = toplevel
    if not top or capture_mode() != "auto":
        return ""
    try:
        from notionmemory.skills.git import queue
        entries = queue.list_entries(top)
        if not entries:
            return ""
        return _m("hook.git_queue", n=len(entries), cli=CLI, project=Path(top).name)
    except Exception:
        return ""


def maybe_install_git_hook(toplevel: str) -> str:
    """install_policy 에 따라 훅을 결정적으로 설치. 반환값 = 세션 주입 문구("" = 없음)."""
    if not toplevel:
        return ""
    try:
        import yaml
        raw = yaml.safe_load(paths.config_path().read_text(encoding="utf-8")) or {}
        opts = (raw.get("skills") or {}).get("git") or {}
        raw_policy = opts.get("install_policy")
        # YAML 1.1은 bare off/on/yes/no 를 bool로 파싱하므로(off → False),
        # `raw_policy or "auto"` 로 곧장 접으면 off가 auto로 되돌아간다 — False를 먼저 걸러낸다.
        policy = "off" if raw_policy is False else str(raw_policy or "auto")
        if policy == "off" or toplevel in (opts.get("exclude") or []):
            return ""
        from notionmemory.skills.git import hooks
        if hooks.is_installed(Path(toplevel)):
            return ""
        if policy == "ask":
            return _m("hook.git_hook_ask", toplevel=toplevel, cli=CLI)
        hooks.install(Path(toplevel), str(paths.config_path()))
        return _m("hook.git_hook_installed", toplevel=toplevel, cli=CLI)
    except Exception:
        return ""


def templates_injection() -> str:
    """등록된 템플릿 한 줄. 네트워크를 찍지 않고 프로필 파일만 읽는다.

    이 줄이 없으면 라우팅 규칙(SKILL.md)이 볼 목록이 없어 내장 스킬만 조회하고
    등록 템플릿을 조용히 누락한다 — 사용자는 그 일이 일어났다는 사실조차 모른다.
    """
    try:
        from notionmemory.skills.templates import profile
        return profile.injection_line(profile.load_all())
    except Exception:
        return ""


def library_injection() -> str:
    """library 색인 나이 한 줄. 네트워크 0 — 로컬 색인 파일만 읽는다.

    빈 색인은 무출력이 아니라 **신호**를 낸다(memory 의 suppress-when-empty 와 반대):
    설치 후 첫 세션에 에이전트가 이걸 보고 refresh 를 돌려 색인을 만든다(스펙 §4·§6).
    접두사를 고정한다 — 첫 글자가 '[' 나 '{' 이면 Claude Code 2.1.215+ 가 훅을 실패 처리한다.

    3갈래 판정(미갱신/빈/색인됨) 자체는 `core/status.py`의 `library_state()`가 계산한다
    — `notionmemory status`(에이전트 PAT 재확인·CLI)도 같은 판정을 쓰므로 여기서 다시
    구현하지 않는다(중복 구현 금지, task-3 계약).
    """
    try:
        from notionmemory.core.status import library_state
        st = library_state()
        if not st["refreshed"]:
            return _m("hook.library_empty")
        if not st["count"]:
            # refresh 는 돌았는데 공유 페이지가 0개 — 넛지하지 않는다(빈 워크스페이스를 매
            # 세션 닦달하지 않기 위해; templates/memory 의 suppress-when-empty 와 같은 침묵).
            return ""
        wm = st["watermark"] or _m("hook.watermark_unknown")
        return _m("hook.library_count", n=st["count"], watermark=wm)
    except Exception:
        return ""


def onboarding_injection() -> str:
    """코어 설정(PAT/memory)이 하나라도 비어 있고 아직 온보딩을 제안하지
    않았으면(config `onboarding.offered`) `onboard` 스킬을 **한 번** 제안하고 마커를
    set 한다. 이미 제안했거나 코어가 다 되어 있으면 "". library 미색인만으로는 제안하지
    않는다 — 그건 library_injection 의 steady-state 넛지 몫이다(돌아온 사용자에게 전체
    온보딩을 다시 들이밀지 않기 위해).

    `status.probe(config, verify=False)`(네트워크 0)만 쓴다 — 세션마다 도는 훅이라
    live HTTP 왕복 금지(task-3 계약, test_injection_makes_no_network_call)."""
    try:
        from notionmemory.core import config as cfg, status as status_mod
        from notionmemory.core.config import Config
        path = str(paths.config_path())
        config = Config.load(path)
        if config.onboarding_offered():
            return ""
        st = status_mod.probe(config, verify=False)
        missing = []
        if not st["notion"]["connected"]:
            missing.append(_m("hook.onboard_item.notion"))
        if not st["memory"]["bound"]:
            missing.append(_m("hook.onboard_item.memory"))
        if not missing:
            return ""
        cfg.save_onboarding_offered(path)
        return _m("hook.onboarding_offer", missing=", ".join(missing), cli=CLI)
    except Exception:
        return ""


LIBRARY_FULL_FLOOR_DAYS = 7      # 드리프트 관측 시: 이 간격 지나야 --full 넛지(과빈도 바닥)
LIBRARY_FULL_BACKSTOP_DAYS = 30  # 관측 없어도 이만큼 오래되면 한 번(안 건드린 유령 정리)


def _days_since(iso: str, now) -> float | None:
    """iso 시각으로부터 now 까지 일수. 파싱 불가/빈 값이면 None('해당 없음')."""
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() / 86400.0


def library_full_refresh_injection(now=None) -> str:
    """색인이 채워져 있고, 라이브 404 지연삭제가 드리프트를 관측했거나(dirty) 마지막
    `--full`(prune) 이후 너무 오래됐으면 `library refresh --full` 을 넛지. 네트워크 0
    (로컬 색인 + 벽시계만) — read-repair 의 anti-entropy 스윕 트리거이고, floor 로
    과빈도를 막는다(관측해도 최소 간격 안엔 한 번, 관측 없으면 backstop 때만).

    미갱신/빈 색인은 여기서 다루지 않는다 — 그건 `library_injection` 의 몫이라
    return "" 로 양보한다(중복 넛지 금지)."""
    try:
        from notionmemory.core.config import Config
        from notionmemory.skills.library import index as lib_index
        now = now or datetime.now(timezone.utc)
        idx = lib_index.load()
        if not lib_index.was_refreshed(idx) or not lib_index.count(idx):
            return ""
        opts = Config.load(str(paths.config_path())).skill_options("library")
        try:
            floor = int(opts.get("full_refresh_days") or LIBRARY_FULL_FLOOR_DAYS)
        except (TypeError, ValueError):
            floor = LIBRARY_FULL_FLOOR_DAYS
        backstop = max(LIBRARY_FULL_BACKSTOP_DAYS, floor)
        days = _days_since(idx.get("last_full_run", ""), now)
        dirty = bool(idx.get("dirty_since_full"))
        # 드리프트 관측 + (한 번도 full 없었음 or floor 경과) → 넛지.
        if dirty and (days is None or days >= floor):
            return _m("hook.library_full_refresh")
        # 관측 없어도 full 기준선이 있고 아주 오래됐으면 한 번(안 건드린 유령 정리).
        if days is not None and days >= backstop:
            return _m("hook.library_full_refresh")
        return ""
    except Exception:
        return ""


def memory_index_injection() -> str:
    """memory 로컬 색인(`mem_index`, Task 1/2)이 비어 있으면(파일 없음/0건) reindex
    안내. 로컬 파일만 본다(네트워크 0) — 색인이 비어 있으면 UserPromptSubmit 훅
    (task-3)은 메시지마다 절대 아무것도 못 찾는다(`mem_index.search` 는 온디스크
    색인만 봄). 색인이 있으면 침묵 — templates/memory 의 suppress-when-empty 와
    같은 규율(매 세션 닦달하지 않음).

    memory DB 가 아예 안 바인딩돼 있으면(Fix round 1) 이 넛지 자체를 건너뛴다 —
    `onboarding_injection`이 이미 "Notion 미연결/memory 미설정"을 안내하는 상황에서
    `reindex`는 바인딩된 DB가 없어 즉시 실패("Notion 조회 불가")하므로, 그 문구
    바로 아래 죽은 명령을 또 하나 얹으면 안 된다. `status.probe(verify=False)`로
    바인딩 여부만 로컬로 확인한다(onboarding_injection과 같은 패턴, 네트워크 0)."""
    try:
        from notionmemory.core import status as status_mod
        from notionmemory.core.config import Config
        from notionmemory.skills.memory import mem_index
        config = Config.load(str(paths.config_path()))
        st = status_mod.probe(config, verify=False)
        if not st["memory"]["bound"]:
            return ""
        if mem_index.count(mem_index.load()) == 0:
            return _m("hook.memory_index_empty")
        return ""
    except Exception:
        return ""


def version_drift_injection() -> str:
    """설치 미러/훅이 패키지보다 뒤처졌으면 `install` 재실행을 넛지. 로컬만 읽는다
    (네트워크 0).

    receipt 에 각인된 패키지 버전(마지막 `install` 시점)과 지금 실행 중인 패키지
    버전을 비교한다 — `pipx upgrade` 만 하고 `install` 을 안 돌리면 `~/.claude/skills`
    미러가 정적 copytree 라 조용히 구버전으로 남는데, 이걸 감지할 다른 채널이 없다.
    receipt 부재/필드 없음(구 receipt·플러그인 채널)이면 "알 수 없음 → 침묵"으로
    떨어진다 — 판단 근거가 없을 땐 닦달하지 않는다(다른 넛지들과 같은 규율)."""
    try:
        from notionmemory.core import version
        from notionmemory.core.install import receipt
        installed = receipt.package_version()
        if not installed:
            return ""
        current = version.package_version()
        if installed == current:
            return ""
        return _m("hook.version_drift", installed=installed, current=current, cli=CLI)
    except Exception:
        return ""


def _memory_store(config):
    """실 Notion 세션으로 MemoryStore 를 만든다 — 별도 함수로 뽑은 이유는 오직 하나,
    테스트가 이 지점만 몽키패치해 PAT/네트워크 없이 memory_injection 을 시험할 수
    있게 하기 위해서다(NotionSession() 은 PAT 없으면 즉시 RuntimeError)."""
    from notionmemory.core.notion_client import NotionSession
    from notionmemory.skills.memory.store import MemoryStore
    return MemoryStore(NotionSession(), config)


def memory_injection(project: str) -> str:
    """프로젝트 브리프(있으면) + 고Strength Active 메모리 top-K(있으면) + 미정리
    Draft nudge(있으면). 옛 `recall --project`(최근5, 서브프로세스) 를 대체한다.

    브리프/top_memories 조회에 Notion 왕복을 허용한다(다른 훅 섹션들의 "네트워크 0"
    과 달리 — task-5 계약). "최대 1회"는 아니다 — data_source 확인(ensure) 1회 +
    브리프 조회 1회 + top_memories 조회 1회, 최대 3왕복 정도로 작게 묶여 있다. 같은
    `store` 인스턴스로 두 조회를 다 하므로 `MemoryStore._data_source()` 의 인스턴스
    캐시(fix round 1) 덕에 ensure() 자체는 두 배가 되지 않는다. 실패/오프라인이면
    이 절만 조용히 비운다 — 세션 시작을 절대 막지 않는다. 셋 다 없으면 완전 침묵
    (노이즈 억제, templates/library 의 suppress-when-empty 와 같은 규율)."""
    lines: list[str] = []
    try:
        from notionmemory.core.config import Config
        config = Config.load(str(paths.config_path()))
        store = _memory_store(config)
        brief = store.project_brief(project)
        if brief:
            lines.append(_m("hook.memory_brief", project=project, brief=brief))
        top = store.top_memories(project, min_strength=MEMORY_MIN_STRENGTH,
                                 limit=MEMORY_TOP_LIMIT)
        if top:
            items = "; ".join(f"{m.get('title', '')} (Strength {m.get('strength', 0)})"
                              for m in top)
            lines.append(_m("hook.memory_top", project=project, items=items))
    except Exception:
        pass
    try:
        pending = [j for j in cq.list_jobs() if j.get("project") == project]
        if pending:
            lines.append(_m("hook.memory_pending_consolidation", cli=CLI))
    except Exception:
        pass
    return "\n".join(lines)


def main(harness: str = "claude") -> int:
    """`harness` 는 CLI 의 `hook --harness` 값 그대로 받는다.

    두 하네스 모두 SessionStart 에서는 평문 stdout 을 받아들인다고 실기로 확인됐다
    (원 조사 프로브). 그래서 이 훅은 harness 값에 따라 출력 형태를 바꾸지 않는다 —
    Codex 용 `hookSpecificOutput.additionalContext` 구조로 바꾸는 것도 가능하지만,
    두 하네스에서 이미 동작하는 평문을 유지하는 쪽이 더 단순해 그걸 택했다
    (Stop/PreCompact 는 반대로 이벤트별 상이함이 실기로 확인돼 save_reminder 가
    harness 를 실제로 분기한다).
    """
    # M6 — consolidate_guard 의 no-op return 보다 stdin 소비가 먼저다. 하네스는
    # 훅이 stdin 을 읽든 말든 프로세스가 끝나면 그 파이프를 정리하니 기능적으로는
    # 차이가 없어 보이지만, 순서를 훅마다 다르게 두면(어떤 훅은 읽고 어떤 훅은
    # 안 읽고) "이 훅이 stdin 을 읽는지"가 훅마다 달라 예측 불가능해진다 — 모든
    # 훅이 항상 stdin 을 먼저 비운다는 단일 규율로 통일한다.
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    if consolidate_guard():
        return 0
    try:
        payload = json.loads(raw or "{}")
        cwd = str(payload.get("cwd") or "")
        top = resolve_toplevel(cwd)
    except Exception:
        return 0
    # 여러 조각은 서로 독립이다 — 각각 따로 감싼다. 한 덩어리로 감쌌더니 앞 섹션이
    # 던지는 순간(예: 옛 recall 서브프로세스가 notionmemory PATH 미탑재로 던진
    # FileNotFoundError) 뒤의 git 훅 안내와 큐 안내까지 통째로 사라졌다. 아무 출력
    # 없이 훅은 성공으로 끝나므로 원인을 추적할 방법이 없다 — 이 프로젝트가 반복해서
    # 밟은 무음 실패다(memory_injection 자체도 내부에서 두 번 나눠 감싸 같은 규율을 지킨다).
    try:
        project = Path(top).name if top else Path(cwd or ".").resolve().name
        note = memory_injection(project)
        # 주의: 첫 글자가 '['/'{' 이면 Claude Code(2.1.215+)가 stdout을 JSON으로
        # 스니핑하다 파싱 실패로 훅을 실패 처리한다 — CATALOG 문구는 전부 평문으로 시작한다.
        if note:
            print(note)
    except Exception:
        pass
    try:
        drift = version_drift_injection()
        if drift:
            print(drift)
    except Exception:
        pass
    try:
        note = maybe_install_git_hook(top)
        if note:
            print(note)
        line = templates_injection()
        if line:
            print(line)
        onboarding = onboarding_injection()
        if onboarding:
            # onboard 제안이 나가는 세션에는 library/memory-index 빈-색인 넛지를 억제한다
            # — onboard 흐름이 library 스캔을 이미 안내하므로 중복 닦달이 된다. memory
            # reindex 는 onboard 가 직접 안내하진 않지만, 제안이 한 번 나가면 마커가 서고
            # 다음 세션(else 분기)에 그 넛지가 다시 뜨므로 유실되지 않는다.
            print(onboarding)
        else:
            # 색인이 낡아 --full 이 필요하면 그 넛지가 우선(정보성 카운트 줄은 생략).
            lib_full = library_full_refresh_injection()
            if lib_full:
                print(lib_full)
            else:
                lib = library_injection()
                if lib:
                    print(lib)
            mem_idx_note = memory_index_injection()
            if mem_idx_note:
                print(mem_idx_note)
    except Exception:
        pass
    try:
        queue_note = git_queue_reminder(top)
        if queue_note:
            print(queue_note)
    except Exception:
        pass
    # SessionEnd 는 세션이 실제로 끝날 때만 발화하지만, 세션이 오래 지속되거나
    # 하네스가 SessionEnd 를 아예 안 보내는 경우를 위한 폴백 — 세션 *시작* 시점에도
    # 이미 큐에 쌓인 미처리 job 이 있으면 스폰을 한 번 더 시도한다. 별도 try 로
    # 격리한다: 위 주입 섹션들이 이미 성공적으로 출력을 냈으면 스폰 실패가 그걸
    # 무효화하면 안 되고(첫 번째 이유), 반대로 주입 섹션 중 하나가 던져도(이미 각자
    # 감싸여 있지만 방어적으로) 스폰 시도 자체는 방해받지 않아야 한다(두 번째 이유).
    try:
        if not consolidate_guard():
            from notionmemory.skills.memory import autorun
            autorun.maybe_spawn(sys.argv[0])
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
