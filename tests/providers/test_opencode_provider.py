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
