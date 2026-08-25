from __future__ import annotations

from notionmemory.providers.base import ProviderSpec
from notionmemory.providers.claude import SPEC as _claude
from notionmemory.providers.codex import SPEC as _codex

_REGISTRY: dict[str, ProviderSpec] = {p.name: p for p in (_claude, _codex)}


def get(name: str) -> ProviderSpec:
    return _REGISTRY[name]


def all() -> list[ProviderSpec]:
    return list(_REGISTRY.values())


def names() -> list[str]:
    return list(_REGISTRY)
