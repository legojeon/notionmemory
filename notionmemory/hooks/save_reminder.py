#!/usr/bin/env python3
"""PreCompact 훅 — 컨텍스트가 압축돼 사라지기 직전의 저장 리마인더.

**Stop 에서는 더 이상 등록하지 않는다.** Stop 은 매 턴 끝마다 발화하는데, 그 시점엔
(a) 에이전트가 이미 턴을 끝냈고 (b) Stop 에는 컨텍스트 주입 채널이 없다 — Codex 의
훅 출력 스키마상 `hookSpecificOutput`(→ `additionalContext`)을 갖는 이벤트는
SessionStart·UserPromptSubmit·SubagentStart·PermissionRequest·Pre/PostToolUse 뿐이고
`stop.command.output` 에는 없다. 남는 `systemMessage` 는 화면 출력 전용이라 Codex 가
`warning:` 으로 렌더링한다. 결과적으로 그 문구는 **읽을 주체가 없었다**: 사람에게는
세션 중 칠 수 없는 CLI 명령을 시키고, 에이전트에게는 전달되지 않았다. 매 턴 반복되니
무시되기까지 했다(실제로 git 큐가 42건까지 쌓였다).

구체적 근거가 있는 git 큐 안내는 주입이 실증된 SessionStart 로 옮겼다
(`session_start.git_queue_reminder`). 여기 남은 것은 압축 직전 한 번뿐이다.

어떤 실패도 조용히 무시한다.
"""
from __future__ import annotations

import json
import sys

from notionmemory.hooks.common import capture_mode

CLI = "notionmemory"

REMINDER = ("이 세션에 지속 가치가 있는 결정·패턴·선호가 있으면 memory 스킬 규약대로 "
            "notionmemory remember --auto 로 저장하세요.")


def main(harness: str = "claude") -> int:
    """`harness` 는 CLI 의 `hook --harness` 값 그대로 받는다.

    실기로 확인됨: Codex 는 PreCompact 훅의 평문 stdout 을 실패로 처리한다 —
    아무것도 안 찍으면 성공, `{"systemMessage": "..."}` 를 찍으면 성공. SessionStart
    에서는 평문이 통했으니(별도 확인됨) 이 차이는 이벤트별이지 하네스 전체 규칙이
    아니다. Claude Code 는 평문을 그대로 받아들이므로 harness="claude"(기본값)에서는
    지금까지의 출력 형태를 한 글자도 바꾸지 않는다.
    """
    try:
        sys.stdin.read()
        if capture_mode() == "auto":
            if harness == "codex":
                print(json.dumps({"systemMessage": REMINDER}, ensure_ascii=False))
            else:
                print(REMINDER)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
