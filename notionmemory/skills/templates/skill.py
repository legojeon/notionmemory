"""templates 스킬 — 레지스트리 카드. run() 은 등록, 나머지 verb 는 CLI 가 담당한다."""
from __future__ import annotations

from typing import Callable

from notionmemory.core.agent_runtime import AgentRuntimeError, build_runtime
from notionmemory.core.config import Config
from notionmemory.core.notion_client import NotionSession
from notionmemory.core.skill_base import RunResult, Skill
from notionmemory.skills.templates import introspect


class TemplatesSkill(Skill):
    id = "templates"
    name = "Templates"
    kinds = ("recall", "action")
    surface = "agent"
    # notion 만이다. agent 는 등록 시 본문 생성에만 쓰이고 실패해도 프로필이 저장되므로
    # 필수 의존이 아니다 — 여기 넣으면 미연결 시 카드가 blocked 가 되어 실제로는
    # 동작하는 CRUD 가 통째로 잠긴다(스펙 §2).
    requires = ["notion"]
    usage = "notionmemory templates register/list/show/query/add/update/archive/refresh/remove"
    runnable = True                 # run()=템플릿 등록(액션) — 대시보드가 실행 버튼을 그린다
    run_label = "템플릿 등록"

    def __init__(self, config: Config):
        self.config = config

    def options_schema(self) -> dict:
        return {
            "target": {"type": "str", "default": "",
                       "label": "템플릿 페이지 URL / ID / 이름",
                       "help": "Notion 에서 복제하고 integration 에 공유한 페이지."},
            "slug": {"type": "str", "default": "",
                     "label": "슬러그(선택)",
                     "help": "비우면 페이지 제목에서 유도. 명시하면 같은 이름 덮어쓰기 "
                             "(재등록)."},
        }

    def run(self, options: dict, log: Callable[[str], None]) -> RunResult:
        target = str((options or {}).get("target") or "").strip()
        if not target:
            return RunResult(False, "등록할 템플릿이 없습니다 — target 에 페이지 URL/ID/이름을 "
                                    "지정하세요")
        try:
            runtime = build_runtime(self.config)
        except AgentRuntimeError as exc:
            log(f"  ! agent 런타임 미감지({exc}) — 사용 노트 없이 등록합니다")
            runtime = None
        try:
            p = introspect.register(NotionSession(log=log), target,
                                    slug=str((options or {}).get("slug") or "").strip(),
                                    runtime=runtime, log=log)
        except (RuntimeError, ValueError) as exc:
            return RunResult(False, str(exc))
        except Exception as exc:  # noqa: BLE001 — introspect.register() 는 실제 Notion
            # HTTP 호출이라 requests.exceptions.* 등 예상 밖 예외가 나올 수 있다. run() 은
            # CLI 의 _cmd_run 에서 try/except 없이 호출되므로 여기서 삼키지 않으면 사용자에게
            # 생 traceback 이 그대로 노출된다(notes/skill.py:87 과 동일한 이유).
            return RunResult(False, f"등록 중 오류가 발생했습니다: {exc}")
        return RunResult(True, f"{p.slug} 등록 완료 — 데이터베이스 {len(p.databases)}개")
