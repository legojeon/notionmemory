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
    summary = "Search your whole Notion by content to find where things are organized."
    kinds = ("recall",)
    surface = "agent"
    requires = ["notion"]
    usage = "notionmemory library search/read/refresh/status"
    runnable = True                 # run()=색인 갱신(액션) — 대시보드가 실행 버튼을 그린다
    run_label = "Rescan"

    def __init__(self, config: Config):
        self.config = config

    def options_schema(self) -> dict:
        return {
            "full": {"type": "bool", "default": False,
                     "label": "Full scan",
                     "help": "Checked: rescan all shared pages and prune ones no "
                             "longer shared. Unchecked: only what changed since "
                             "the last refresh (faster)."},
        }

    def run(self, options: dict, log: Callable[[str], None]) -> RunResult:
        full = bool((options or {}).get("full"))
        try:
            summary = crawl.refresh(NotionSession(log=log), full=full, log=log)
        except (RuntimeError, ValueError) as exc:
            return RunResult(False, str(exc))
        except Exception as exc:      # noqa: BLE001 — run() 은 트레이스백을 흘리지 않는다
            return RunResult(False, f"scan refresh failed: {exc}")
        return RunResult(True, f"library: {summary['total']} pages scanned "
                               f"({summary['indexed']} newly scanned this run)")
