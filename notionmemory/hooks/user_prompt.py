#!/usr/bin/env python3
"""UserPromptSubmit 훅 — 사용자 메시지마다 로컬 memory 색인만 검색해(네트워크 0)
관련성 게이트를 넘는 기억이 있을 때만 컴팩트 힌트 한 줄을 주입한다.

Second Brain v2 Phase 2b Task 3. `mem_index`(Task 1)와 `memory reindex`(Task 2)가
채운 온디스크 색인만 본다 — SessionStart 의 `memory_injection`(브리프·top-K)과
달리 이 훅은 **메시지마다** 돌기 때문에 Notion 왕복이 절대 금지다. `mem_index.search`
자체가 관련성 게이트(`min_score`)를 쥐고 있어 무관한 메시지는 빈 리스트를 돌려주고,
이 훅은 그 결과가 비면 완전히 침묵한다(아무 것도 출력하지 않음) — 매 메시지 무관한
메모리가 끼어들면 신뢰를 잃는다는 anti-noise 계약.

세션을 절대 막으면 안 되므로 어떤 실패도 조용히 삼키고 항상 0 을 반환한다. 등록은
`notionmemory install` 이 수행한다(매니페스트의 훅 아티팩트 → JsonHookBlock,
`notionmemory/core/install/manifest.py` 의 `HOOK_EVENTS`).
"""
from __future__ import annotations

import json
import sys

from notionmemory.hooks.session_start import resolve_project
from notionmemory.skills.memory import mem_index

CLI = "notionmemory"


def _hint(hits: list) -> str:
    """가장 관련성 높은 히트 하나만 힌트로 보여준다 — 여러 개를 나열하면 매 메시지
    긴 블록이 끼어들어 노이즈가 된다(게이트를 넘은 것 중에서도 최소한만).
    첫 글자가 '['/'{' 이면 안 된다(session_start 의 JSON-스니핑 함정과 동일 규율) —
    이 문구는 평문으로 시작한다."""
    top = hits[0]
    title = top.get("title", "")
    mem_id = top.get("mem_id", "")
    return (f'relevant memory — "{title}" (recall for detail): '
            f"{CLI} recall --get {mem_id}")


def main(harness: str = "claude") -> int:
    """`harness` 는 CLI 의 `hook --harness` 값 그대로 받는다(다른 훅과 같은
    시그니처) — 이 훅은 하네스별로 출력 형태를 바꾸지 않는다(SessionStart 와 같은
    평문-stdout 방식, 하네스가 additionalContext 로 주입)."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        prompt = str(payload.get("prompt") or "")
        cwd = str(payload.get("cwd") or "")
        project = resolve_project(cwd)
        hits = mem_index.search(mem_index.load(), prompt, project=project, limit=3)
        if hits:
            print(_hint(hits))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
