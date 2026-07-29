"""git 스킬 — 설정 전용 카드. 실행은 CLI(notionmemory git ...)가 담당."""
from __future__ import annotations

from typing import Callable

from notionmemory.core.config import Config
from notionmemory.core.skill_base import RunResult, Skill


class GitCaptureSkill(Skill):
    id = "git"
    name = "Git"
    summary = "Automatically capture commits into the memory queue (background, via a post-commit hook)."
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
                "help": "auto: automatically installs a post-commit capture hook "
                        "in the current git repo at session start (respects the "
                        "exclude list). ask: the agent asks the user. off: never "
                        "auto-installs. The repos/exclude list is managed by the CLI."},
        }

    def run(self, options: dict, log: Callable[[str], None]) -> RunResult:
        return RunResult(False, "git is used as a CLI: "
                                "notionmemory git install|status|list|ack|flush")
