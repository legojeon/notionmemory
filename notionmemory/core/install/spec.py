"""설치 아티팩트 명세 — 설치물을 데이터로 표현한다.

install 은 이 목록을 정방향으로, teardown 은 역방향으로 훑는다. 새 스킬이 시스템에
무언가를 심는다면 여기에 항목을 추가하는 것이 완료 조건이다(백로그 teardown 설계 원칙).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ArtifactSpec:
    id: str                              # "codex.hooks"
    owner: str                           # 소유 스킬 id ("memory" | "git" | "_core")
    handler: str                         # HANDLERS 의 키
    target: str                          # "claude" | "codex" | "shared"
    path: Path
    payload: dict = field(default_factory=dict)
    markers: tuple[str, ...] = ()        # 현행 + 레거시 소유권 식별자
