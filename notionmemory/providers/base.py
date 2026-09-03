from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    display_name: str
    config_home_env: str
    home_dirname: str
    install_kind: str = "hooks"                 # "hooks" | "bundle"
    # hooks-kind fields (unused for bundle):
    hook_file_name: str = ""
    hook_format: str = ""          # "json" | "toml"
    hook_file_dedicated: bool = False
    harness_token: str = ""
    events: Callable[[str], dict] | None = None
    post_install_spec: Callable[[], object] | None = None
    # bundle-kind fields (unused for hooks):
    bundle_source: str = ""                     # absolute path to the packaged bundle dir
    bundle_install_subpath: str = ""            # relative to home_dirname, e.g. "agent/extensions/notionmemory"
    # extra flags onboarding/detection appends to `install --<name>` (e.g. codex trust):
    install_extra_flags: tuple[str, ...] = ()
