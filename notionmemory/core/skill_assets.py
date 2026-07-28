"""패키지에 동봉된 agent skill 자산(SKILL.md 등) 접근.

editable 설치와 wheel 설치 모두에서 실제 디렉터리로 존재하므로 __file__ 기준으로 찾는다.
"""
from __future__ import annotations

from pathlib import Path


def skills_root() -> Path:
    return Path(__file__).resolve().parent.parent / "agent_skills"


def skill_names() -> list[str]:
    root = skills_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and (p / "SKILL.md").is_file())
