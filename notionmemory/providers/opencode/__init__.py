from __future__ import annotations

from pathlib import Path

from notionmemory.core.install import manifest
from notionmemory.core.install.spec import ArtifactSpec
from notionmemory.providers.base import ProviderSpec


def _config_entry_spec() -> ArtifactSpec:
    """`<config>/opencode.json` 의 `plugin` 배열 항목.

    OpenCode 는 플러그인 디렉터리를 자동 발견하지 않는다(2026-08-27 실측) — 셸에
    번들을 심는 것만으로는 로드되지 않고, 이 JSON 항목이 있어야 한다.
    """
    home = manifest.harness_home("opencode")
    shim = home / "plugin" / "notionmemory" / "plugin.ts"   # = bundle_install_subpath / plugin.ts
    entry = "file://" + str(shim)
    return ArtifactSpec(
        id="opencode.config", owner="_core", handler="opencode_config_entry",
        target="opencode", path=home / "opencode.json",
        payload={"entry": entry}, markers=(entry,))


SPEC = ProviderSpec(
    name="opencode", display_name="OpenCode",
    config_home_env="OPENCODE_CONFIG_DIR",   # live-verified (2026-08-27): the real override var opencode honors
    home_dirname=".config/opencode",
    install_kind="bundle",
    bundle_source=str(Path(__file__).parent / "bundle"),
    bundle_install_subpath="plugin/notionmemory",
    post_install_spec=_config_entry_spec)
