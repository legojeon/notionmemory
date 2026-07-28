"""library 스킬 — 레지스트리 카드. run() 은 색인 갱신(대시보드에서 실행),
검색·읽기는 CLI verb 가 담당."""
from __future__ import annotations

from typing import Callable

from notionmemory.core.config import Config
from notionmemory.core.notion_client import NotionSession
from notionmemory.core.skill_base import RunResult, Skill
from notionmemory.skills.library import crawl


class LibrarySkill(Skill):
    id = "library"
    name = "Library"
    kinds = ("recall",)
    surface = "agent"
    requires = ["notion"]
    usage = "notionmemory library search/read/refresh/status"
    runnable = True                 # run()=색인 갱신(액션) — 대시보드가 실행 버튼을 그린다
    run_label = "재색인 실행"

    def __init__(self, config: Config):
        self.config = config

    def options_schema(self) -> dict:
        return {
            "full": {"type": "bool", "default": False,
                     "label": "전체 재색인",
                     "help": "체크하면 공유 페이지 전량을 다시 훑고 공유 해제분을 정리합니다. "
                             "비우면 마지막 갱신 이후 변경분만(빠름)."},
        }

    def run(self, options: dict, log: Callable[[str], None]) -> RunResult:
        full = bool((options or {}).get("full"))
        try:
            summary = crawl.refresh(NotionSession(log=log), full=full, log=log)
        except (RuntimeError, ValueError) as exc:
            return RunResult(False, str(exc))
        except Exception as exc:      # noqa: BLE001 — run() 은 트레이스백을 흘리지 않는다
            return RunResult(False, f"색인 갱신 실패: {exc}")
        return RunResult(True, f"library 색인: {summary['total']}건 "
                               f"(이번에 {summary['indexed']}건 색인)")
