"""memory 스킬 — 설정 전용 카드. 실행은 CLI verb(remember/recall/forget)가 담당."""
from __future__ import annotations

from typing import Callable

from notionmemory.core.config import Config
from notionmemory.core.skill_base import RunResult, Skill


class MemorySkill(Skill):
    id = "memory"
    name = "Memory"
    kinds = ("capture", "recall")
    requires = ["notion"]
    usage = "notionmemory remember/recall/forget"

    def __init__(self, config: Config):
        self.config = config

    def options_schema(self) -> dict:
        return {
            "capture_mode": {
                "type": "select", "default": "auto", "choices": ["auto", "manual"],
                "label": "Capture mode",
                "help": "auto: allows the agent to save on its own judgment "
                        "(remember --auto). manual: the CLI rejects --auto saves "
                        "(exit 2) — only saves the user explicitly requested go "
                        "through. The CLI mechanically enforces this setting."},
            "top_n": {
                "type": "number", "default": 5,
                "label": "Recall top N",
                "help": "Maximum number of results recall returns into the agent's context."},
            "default_project": {
                "type": "str", "default": "",
                "label": "Default project",
                "help": "Used when remember is called without --project."},
            "parent_page_id": {
                "type": "str", "default": "",
                "label": "Parent page ID",
                "help": "Parent page ID under which the Second Brain DB is created. "
                        "Leave blank to create it at the workspace top level."},
        }

    def run(self, options: dict, log: Callable[[str], None]) -> RunResult:
        return RunResult(False, "memory is used as a CLI verb: notionmemory remember/recall/forget")
