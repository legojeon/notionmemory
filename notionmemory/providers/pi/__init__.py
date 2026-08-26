from __future__ import annotations

from pathlib import Path

from notionmemory.providers.base import ProviderSpec

SPEC = ProviderSpec(
    name="pi", display_name="pi",
    config_home_env="PI_HOME",           # best-guess override var; verify at live-test (no harm if unset)
    home_dirname=".pi",
    install_kind="bundle",
    bundle_source=str(Path(__file__).parent / "bundle"),
    bundle_install_subpath="agent/extensions/notionmemory")
