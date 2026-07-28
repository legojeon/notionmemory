from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

VALID_KINDS = {"capture", "recall", "action"}

# 표면 구분: agent = 에이전트가 SKILL.md 로 호출하는 스킬,
# service = SKILL.md 없이 훅·큐로 도는 백그라운드 캡처 서비스(git).
# 레지스트리·대시보드가 둘을 섞어 보여주면 "왜 얘만 스킬 같지 않지?"가 계속 남는다.
VALID_SURFACES = {"agent", "service"}


@dataclass
class RunResult:
    ok: bool
    message: str = ""


class Skill(ABC):
    id: str = ""
    name: str = ""
    kinds: tuple[str, ...] = ()
    requires: list[str] = []
    # 사용법 한 줄 — verb 스킬(memory/calendar/git)은 `run`으로 실행되지 않으므로
    # 대시보드가 일괄 안내 대신 이 값을 보여준다. 비우면 기본 `run` 안내로 폴백.
    usage: str = ""
    # 사람이 손으로 해야 하는 외부 설정 절차(예: Notion Calendar 앱 연결) — API로
    # 자동화 불가능한 단계를 설치자가 대시보드에서 그대로 볼 수 있게 한다.
    setup_steps: tuple[str, ...] = ()
    surface: str = "agent"
    # run() 이 실제 액션을 수행하는가(library=재색인, templates=등록). True 면 대시보드가
    # 설정 저장 폼 대신 **실행 패널**(파라미터 입력 + 실행 버튼 + 진행표시)을 그린다.
    # False(기본, memory/calendar/git)면 run() 은 no-op 이고 options 는 저장 설정이다.
    runnable: bool = False
    run_label: str = "Run"

    @abstractmethod
    def options_schema(self) -> dict: ...

    def clean_options(self, options: dict) -> dict:
        """웹/CLI 원본 옵션을 options_schema() 타입으로 정규화.

        - 빈 문자열("")은 미입력으로 취급해 드롭
        - bool: "1/true/on/yes"(대소문자 무관) → True
        - number: int 변환, 실패 시 ValueError — 값 없는 `--limit`("true")이
          조용히 기본값/0으로 둔갑해 전량 실행되는 사고를 막는다
        - select: choices 밖의 값은 ValueError — 정책 토글(capture_mode 등)이
          오타/임의 POST 값으로 조용히 다른 의미로 해석되는 것을 막는다
        - 스키마에 없는 키는 그대로 통과(웹 저장 경로의 whitelist가 걸러줌)
        """
        schema = self.options_schema()
        cleaned: dict = {}
        for key, value in (options or {}).items():
            if value == "":
                continue
            field = schema.get(key) or {}
            field_type = field.get("type")
            if field_type == "bool":
                if isinstance(value, str):
                    value = value.strip().lower() in {"1", "true", "on", "yes"}
                cleaned[key] = value
            elif field_type == "number":
                try:
                    cleaned[key] = int(value)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"option --{key} value is not a number: {value!r} "
                        f"(pass a value like --{key} 5)")
            elif field_type == "select":
                choices = field.get("choices") or []
                if choices and value not in choices:
                    raise ValueError(
                        f"option --{key} value is not an allowed choice: {value!r} "
                        f"(allowed: {', '.join(choices)})")
                cleaned[key] = value
            else:
                cleaned[key] = value
        return cleaned

    @abstractmethod
    def run(self, options: dict, log: Callable[[str], None]) -> RunResult: ...
