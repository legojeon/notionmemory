#!/usr/bin/env python3
"""SessionEnd 훅 — 세션 종료 시 consolidate 를 detached 로 스폰(비블로킹).

Codex 는 SessionEnd 타임아웃이 기본 1초/최대 3초(공식 문서)라 이 훅은 어떤 LLM/
네트워크 작업도 하지 않는다: stdin 소비 → 게이트 확인 → 스폰 → 종료. 게이트·락은
autorun 이 쥔다. 어떤 실패도 조용히 무시한다.

`autorun` 은(여기서는 예외적으로) 모듈 상단에서 임포트한다 — 무겁다고 늦게
들여오는 다른 훅들과 달리, `autorun.py` 는 임포트 시점에 yaml/notion_client/
requests 를 전혀 건드리지 않는다(os/subprocess/time/datetime + 로컬 큐 모듈뿐,
설정 파싱은 함수 안에서만 지연 로드). 그래서 이 훅의 타임아웃 예산(최대 3초)을
갉아먹지 않으면서도 다른 훅들과 같은 방식으로(`session_end.autorun` 애트리뷰트
직접 monkeypatch) 테스트할 수 있다."""
from __future__ import annotations

import sys

from notionmemory.hooks.common import consolidate_guard
from notionmemory.skills.memory import autorun


def main(harness: str = "claude") -> int:
    try:
        sys.stdin.read()
        if consolidate_guard():
            return 0
        autorun.maybe_spawn(sys.argv[0])
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
