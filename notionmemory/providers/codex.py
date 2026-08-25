from __future__ import annotations

from notionmemory.core.install import manifest
from notionmemory.providers.base import ProviderSpec

SPEC = ProviderSpec(
    name="codex", display_name="Codex CLI",
    config_home_env="CODEX_HOME", home_dirname=".codex",
    hook_file_name="hooks.json", hook_format="json",
    hook_file_dedicated=True, harness_token="codex",
    events=lambda cli: manifest.HOOK_EVENTS(cli, "codex"),
    post_install_spec=manifest.codex_trust_spec)
