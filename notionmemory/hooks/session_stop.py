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

import os
from datetime import datetime, timezone

from notionmemory.hooks.session_start import resolve_project
from notionmemory.skills.memory import consolidation_queue


def main(harness: str = "claude") -> int:
    """`harness` 는 CLI 의 `hook --harness` 값 그대로 받는다(다른 훅과 같은
    시그니처) — enqueue-only 라 harness 별 분기는 필요 없다."""
    try:
        cwd = os.getcwd()
        project = resolve_project(cwd)
        ts = datetime.now(timezone.utc).isoformat()
        consolidation_queue.enqueue(project, cwd, ts)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
