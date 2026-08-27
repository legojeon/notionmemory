from __future__ import annotations

from pathlib import Path

from notionmemory.providers.base import ProviderSpec

SPEC = ProviderSpec(
    name="opencode", display_name="OpenCode",
    config_home_env="OPENCODE_CONFIG",       # best-guess override var; confirm at live-e2e (no harm if unset)
    home_dirname=".config/opencode",
    install_kind="bundle",
    bundle_source=str(Path(__file__).parent / "bundle"),
    bundle_install_subpath="plugin/notionmemory")   # subdir; confirm opencode loads it at live-e2e
