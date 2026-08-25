from __future__ import annotations

from notionmemory.core.install import manifest
from notionmemory.providers.base import ProviderSpec

SPEC = ProviderSpec(
    name="kimi", display_name="Kimi Code",
    config_home_env="KIMI_CODE_HOME", home_dirname=".kimi-code",
    hook_file_name="config.toml", hook_format="toml",
    hook_file_dedicated=False, harness_token="kimi",
    events=manifest.KIMI_HOOK_EVENTS,
    post_install_spec=None)
