#!/usr/bin/env python3
"""Stop 훅 — 세션 종료 시 이 프로젝트의 Draft memory consolidation 을 큐에 적재.

**큐잉만 한다.** LLM pass(별도 명령 `notionmemory memory consolidate`, Task 4)는
여기서 절대 돌지 않는다 — 이 파일은 `agent_runtime`/`build_runtime` 을 임포트도
호출도 하지 않는다(회귀 가드: `tests/hooks/test_session_stop.py`).

세션 종료를 막으면 안 되므로 어떤 실패도 조용히 삼키고 항상 0 을 반환한다.
등록은 `notionmemory install` 이 수행한다(매니페스트의 훅 아티팩트 →
JsonHookBlock, `notionmemory/core/install/manifest.py` 의 `HOOK_EVENTS`).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from notionmemory.hooks.common import capture_mode, consolidate_guard
from notionmemory.hooks.session_start import resolve_project
from notionmemory.skills.memory import consolidation_queue, transcripts


def main(harness: str = "claude") -> int:
    """`harness` 는 CLI 의 `hook --harness` 값 그대로 받는다(다른 훅과 같은
    시그니처). Claude Code 는 Stop 훅 stdin 으로 `{"session_id", "transcript_path",
    "cwd", ...}` JSON 을 준다 — codex 는 transcript_path 를 안 주므로 세션 id 로
    rollout 파일을 글롭 폴백한다(`transcripts.find_codex_rollout`).

    `capture_mode() != "auto"`(off/manual) 면 stdin 만 비우고 아무것도 큐에 넣지
    않는다 — 사용자가 자동 캡처를 껐는데 훅이 조용히 잡을 쌓으면 안 된다."""
    # M6 — stdin 소비가 consolidate_guard 의 no-op return 보다 먼저다(모든 훅이
    # 항상 stdin 을 먼저 비운다는 단일 규율, session_start/user_prompt 와 동일).
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    if consolidate_guard():
        return 0
    try:
        if capture_mode() != "auto":
            return 0
        payload = json.loads(raw or "{}")
        cwd = str(payload.get("cwd") or "") or os.getcwd()
        project = resolve_project(cwd)
        ts = datetime.now(timezone.utc).isoformat()
        session = None
        sid = str(payload.get("session_id") or "")
        path = str(payload.get("transcript_path") or "")
        if sid and not path and harness == "codex":
            path = transcripts.find_codex_rollout(sid)
        if sid and path:
            session = {"session_id": sid, "transcript_path": path,
                       "harness": harness, "ts": ts}
        consolidation_queue.enqueue(project, cwd, ts, session=session)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
