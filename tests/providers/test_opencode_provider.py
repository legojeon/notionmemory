from pathlib import Path
import pytest
from notionmemory import providers
from notionmemory.core.install import manifest


def test_opencode_registered_as_bundle():
    assert "opencode" in providers.names()
    p = providers.get("opencode")
    assert p.install_kind == "bundle"
    assert p.bundle_source.endswith("providers/opencode/bundle")
    assert Path(p.bundle_source).is_dir()
    assert p.bundle_install_subpath  # non-empty


def test_opencode_config_home_env_is_the_live_verified_var():
    assert providers.get("opencode").config_home_env == "OPENCODE_CONFIG_DIR"


@pytest.fixture
def fixed_home(tmp_path, monkeypatch):
    monkeypatch.setattr("notionmemory.core.paths.home", lambda: tmp_path)
    return tmp_path


def test_build_and_sweep_emit_opencode_bundle(fixed_home):
    from notionmemory.core.install import teardown
    p = providers.get("opencode")
    expected_path = manifest.harness_home("opencode") / p.bundle_install_subpath
    built = {s.id: s for s in manifest.build(["opencode"], "notionmemory")}
    swept = {s.id: s for s in teardown._sweep(["opencode"])}
    for specs in (built, swept):
        b = specs["opencode.bundle"]
        assert b.handler == "bundle_mirror"
        assert b.path == expected_path
    # build carries source+cli_path; sweep carries empty payload (removal needs only path+handler)
    assert built["opencode.bundle"].payload["cli_path"] == "notionmemory"
    assert Path(built["opencode.bundle"].payload["source"]).is_dir()
    assert "opencode.hooks" not in built
    assert not any(i.startswith("opencode.skills.") for i in built)


def test_build_and_sweep_also_register_config_entry(fixed_home):
    from notionmemory.core.install import teardown
    p = providers.get("opencode")
    expected_entry = "file://" + str(
        manifest.harness_home("opencode") / p.bundle_install_subpath / "plugin.ts")
    built = {s.id: s for s in manifest.build(["opencode"], "notionmemory")}
    swept = {s.id: s for s in teardown._sweep(["opencode"])}

    b = built["opencode.config"]
    assert b.handler == "opencode_config_entry"
    assert Path(b.path).name == "opencode.json"
    assert b.payload["entry"] == expected_entry
    assert b.markers == (expected_entry,)

    s = swept["opencode.config"]
    assert s.handler == "opencode_config_entry"
    assert Path(s.path).name == "opencode.json"


def test_pi_bundle_is_unaffected_by_the_generalization(fixed_home):
    """pi.post_install_spec is None -> the bundle branch generalization must be a no-op for pi."""
    built = manifest.build(["pi"], "notionmemory")
    ids = {s.id for s in built}
    assert ids == {"pi.bundle", "shared.git_hooks", "shared.notion_broker"}
