from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    display_name: str
    config_home_env: str
    home_dirname: str
    hook_file_name: str
    hook_format: str          # "json" | "toml"
    hook_file_dedicated: bool
    harness_token: str
    events: Callable[[str], dict]
    post_install_spec: Callable[[], object] | None = None
