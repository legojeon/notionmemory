from __future__ import annotations
from flask import Flask
from notionmemory.core.config import Config
from notionmemory.core.integrations import build_integrations
from notionmemory.core.registry import Registry
from notionmemory.core.skill_base import Skill
from notionmemory.skills.calendar.skill import CalendarSkill
from notionmemory.skills.git.skill import GitCaptureSkill
from notionmemory.skills.library.skill import LibrarySkill
from notionmemory.skills.memory.skill import MemorySkill
from notionmemory.skills.templates.skill import TemplatesSkill
from notionmemory.web.server import create_app


def build_registry(config_path: str, skills: list[Skill] | None = None) -> Registry:
    config = Config.load(config_path)
    resolved = skills if skills is not None else [
        MemorySkill(config), GitCaptureSkill(config),
        CalendarSkill(config), TemplatesSkill(config), LibrarySkill(config)]
    return Registry(resolved, build_integrations(config), config)


def build_app(config_path: str, skills: list[Skill] | None = None) -> Flask:
    return create_app(build_registry(config_path, skills))
