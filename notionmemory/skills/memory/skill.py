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
                "help": "auto: 에이전트가 스스로 판단한 저장(remember --auto)을 허용. "
                        "manual: --auto 저장을 CLI가 거부(exit 2) — 사용자가 직접 요청한 "
                        "저장만 통과. 설정은 CLI가 기계적으로 강제한다."},
            "top_n": {
                "type": "number", "default": 5,
                "label": "Recall top N",
                "help": "recall이 에이전트 컨텍스트로 반환하는 최대 결과 수."},
            "default_project": {
                "type": "str", "default": "",
                "label": "Default project",
                "help": "remember 시 --project 미지정이면 이 값을 사용."},
            "parent_page_id": {
                "type": "str", "default": "",
                "label": "Parent page ID",
                "help": "Second Brain DB를 만들 부모 페이지 ID. 비우면 워크스페이스 "
                        "최상위에 직접 생성."},
        }

    def run(self, options: dict, log: Callable[[str], None]) -> RunResult:
        return RunResult(False, "memory는 CLI verb로 사용합니다: notionmemory remember/recall/forget")
