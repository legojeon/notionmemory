"""calendar 스킬 — 설정 전용 카드. 실행은 CLI verb(calendar list/add/update/cancel)가 담당."""
from __future__ import annotations

from typing import Callable

from notionmemory.core.config import Config
from notionmemory.core.skill_base import RunResult, Skill
from notionmemory.skills.calendar.notion_db import SETUP_STEPS


class CalendarSkill(Skill):
    id = "calendar"
    name = "Calendar"
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
                "help": "Calendar DB를 만들 부모 페이지 ID. 비우면 워크스페이스 "
                        "최상위에 직접 생성."},
            "write_target": {
                "type": "str", "default": "",
                "label": "일정 쓰기 대상",
                "help": "비우면 등록된 템플릿과 겹칠 때 매번 되묻습니다. "
                        "`calendar` = 내장 Calendar DB로 고정. "
                        "`template:<slug>/<db-key>` = 그 템플릿으로 안내 "
                        "(calendar 가 대신 쓰지는 않습니다)."},
        }

    def run(self, options: dict, log: Callable[[str], None]) -> RunResult:
        return RunResult(False, "calendar는 CLI verb로 사용합니다: "
                                "notionmemory calendar list/add/update/cancel")
