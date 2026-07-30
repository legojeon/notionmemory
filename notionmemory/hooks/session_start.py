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
import subprocess
import sys
from pathlib import Path

from notionmemory.core import paths
from notionmemory.hooks.common import capture_mode
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


def resolve_toplevel(cwd: str) -> str:
    """git toplevel 절대경로, git 리포가 아니거나 실패하면 ""."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=cwd or None,
            capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:
        return ""


def resolve_project(cwd: str) -> str:
    """git toplevel basename, 실패 시 cwd basename."""
    top = resolve_toplevel(cwd)
    if top:
        return Path(top).name
    return Path(cwd or ".").resolve().name


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
    """코어 설정(PAT/memory/calendar)이 하나라도 비어 있고 아직 온보딩을 제안하지
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
        if not st["calendar"]["bound"]:
            missing.append(_m("hook.onboard_item.calendar"))
        if not missing:
            return ""
        cfg.save_onboarding_offered(path)
        return _m("hook.onboarding_offer", missing=", ".join(missing), cli=CLI)
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
        if not mem_index.load():
            return _m("hook.memory_index_empty")
        return ""
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
    try:
        payload = json.loads(sys.stdin.read() or "{}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
