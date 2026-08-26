from notionmemory import providers
from notionmemory.providers.base import ProviderSpec


def test_existing_providers_default_to_hooks_kind():
    for name in ("claude", "codex", "kimi"):
        assert providers.get(name).install_kind == "hooks"


def test_bundle_spec_can_omit_hook_fields():
    p = ProviderSpec(
        name="x", display_name="X", config_home_env="X_HOME", home_dirname=".x",
        install_kind="bundle", bundle_source="/pkg/x/bundle",
        bundle_install_subpath="ext/x")
    assert p.install_kind == "bundle"
    assert p.bundle_source == "/pkg/x/bundle"
    assert p.bundle_install_subpath == "ext/x"
    assert p.hook_file_name == ""          # defaulted, unused for bundle
    assert p.events is None
