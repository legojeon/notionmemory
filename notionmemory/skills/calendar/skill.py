"""calendar 스킬 — 설정 전용 카드. 실행은 CLI verb(calendar list/add/update/cancel)가 담당."""
from __future__ import annotations

from typing import Callable

from notionmemory.core.config import Config
from notionmemory.core.skill_base import RunResult, Skill
from notionmemory.skills.calendar.notion_db import SETUP_STEPS


class CalendarSkill(Skill):
    id = "calendar"
    name = "Calendar"
    summary = "List, add, update, and cancel events in your Notion Calendar."
    kinds = ("recall", "action")
    requires = ["notion"]
    usage = "notionmemory calendar list/add/update/cancel"
    setup_steps = SETUP_STEPS

    def __init__(self, config: Config):
        self.config = config

    def options_schema(self) -> dict:
        return {
            "parent_page_id": {
                "type": "str", "default": "",
                "label": "Parent page ID",
                "help": "Parent page ID under which the Calendar DB is created. "
                        "Leave blank to create it at the workspace top level."},
            "write_target": {
                "type": "str", "default": "",
                "label": "event write target",
                "help": "If blank, asks each time a registered template overlaps. "
                        "`calendar` = pin to the built-in Calendar DB. "
                        "`template:<slug>/<db-key>` = point to that template "
                        "(calendar does not write there for you)."},
        }

    def run(self, options: dict, log: Callable[[str], None]) -> RunResult:
        return RunResult(False, "calendar is used as a CLI verb: "
                                "notionmemory calendar list/add/update/cancel")
