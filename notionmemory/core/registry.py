from __future__ import annotations
from dataclasses import dataclass, field
from notionmemory.core.config import Config
from notionmemory.core.integrations import Integration
from notionmemory.core.skill_base import Skill


@dataclass
class SkillCard:
    id: str
    name: str
    kinds: list[str]
    requires: list[str]
    status: str
    missing: list[str] = field(default_factory=list)
    usage: str = ""
    setup_steps: list[str] = field(default_factory=list)
    surface: str = "agent"
    runnable: bool = False
    run_label: str = "실행"


class Registry:
    def __init__(self, skills: list[Skill], integrations: dict[str, Integration], config: Config):
        self._skills = {s.id: s for s in skills}
        self._integrations = integrations
        self._config = config

    @property
    def config(self) -> Config:
        return self._config

    def integrations(self) -> dict[str, Integration]:
        return dict(self._integrations)

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def cards(self) -> list[SkillCard]:
        return [self._card(s) for s in self._skills.values()]

    def _card(self, s: Skill) -> SkillCard:
        try:
            missing = [rid for rid in s.requires if not self._connected(rid)]
            status = "available" if not missing else "blocked"
        except Exception:
            missing, status = list(s.requires), "error"
        return SkillCard(s.id, s.name, list(s.kinds), list(s.requires), status, missing,
                         s.usage, list(s.setup_steps), s.surface, s.runnable, s.run_label)

    def _connected(self, integration_id: str) -> bool:
        integ = self._integrations.get(integration_id)
        return bool(integ and integ.status(self._config).connected)
