"""git 스킬 — 설정 전용 카드. 실행은 CLI(notionmemory git ...)가 담당."""
from __future__ import annotations

from typing import Callable

from notionmemory.core.config import Config
from notionmemory.core.skill_base import RunResult, Skill


class GitCaptureSkill(Skill):
    id = "git"
    name = "Git"
    kinds = ("capture",)
    usage = "notionmemory git install/status/list/ack/flush"
    requires = ["notion"]
    surface = "service"

    def __init__(self, config: Config):
        self.config = config

    def options_schema(self) -> dict:
        return {
            "install_policy": {
                "type": "select", "default": "auto",
                "choices": ["auto", "ask", "off"],
                "label": "Hook install policy",
                "help": "auto: 세션 시작 시 현재 git 리포에 post-commit 캡처 훅을 "
                        "자동 설치(제외 목록 존중). ask: 에이전트가 사용자에게 물어봄. "
                        "off: 자동 설치 안 함. repos/exclude 목록은 CLI가 관리."},
        }

    def run(self, options: dict, log: Callable[[str], None]) -> RunResult:
        return RunResult(False, "git은 CLI로 사용합니다: "
                                "notionmemory git install|status|list|ack|flush")
