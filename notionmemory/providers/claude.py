from __future__ import annotations

from notionmemory.core.install import manifest
from notionmemory.providers.base import ProviderSpec

SPEC = ProviderSpec(
    name="claude", display_name="Claude Code",
    config_home_env="CLAUDE_CONFIG_DIR", home_dirname=".claude",
    hook_file_name="settings.json", hook_format="json",
    hook_file_dedicated=False, harness_token="claude",
    events=lambda cli: manifest.HOOK_EVENTS(cli, "claude"),
    post_install_spec=None)
