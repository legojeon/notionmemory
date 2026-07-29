from __future__ import annotations
from dataclasses import dataclass, field
from notionmemory.core.config import Config
from notionmemory.core.i18n import tui
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
    summary: str = ""
    usage: str = ""
    setup_steps: list[str] = field(default_factory=list)
    surface: str = "agent"
    runnable: bool = False
    run_label: str = "Run"


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

    def cards(self, lang: str | None = None) -> list[SkillCard]:
        lang = lang or "en"
        return [self._card(s, lang) for s in self._skills.values()]

    def _card(self, s: Skill, lang: str) -> SkillCard:
        try:
            missing = [rid for rid in s.requires if not self._connected(rid)]
            status = "available" if not missing else "blocked"
        except Exception:
            missing, status = list(s.requires), "error"
        summary = tui(lang, f"ui.card.{s.id}.summary", s.summary)
        usage = tui(lang, f"ui.card.{s.id}.usage", s.usage)
        run_label = tui(lang, f"ui.card.{s.id}.run_label", s.run_label)
        setup_steps = [tui(lang, f"ui.card.{s.id}.setup.{i}", step)
                       for i, step in enumerate(s.setup_steps)]
        return SkillCard(s.id, s.name, list(s.kinds), list(s.requires), status, missing,
                         summary, usage, setup_steps, s.surface, s.runnable, run_label)

    def _connected(self, integration_id: str) -> bool:
        integ = self._integrations.get(integration_id)
        return bool(integ and integ.status(self._config).connected)
