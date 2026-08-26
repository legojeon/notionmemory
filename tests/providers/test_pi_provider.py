from pathlib import Path
import pytest
from notionmemory import providers
from notionmemory.core.install import manifest


def test_pi_registered_as_bundle():
    assert "pi" in providers.names()
    p = providers.get("pi")
    assert p.install_kind == "bundle"
    assert p.home_dirname == ".pi"
    assert p.bundle_install_subpath == "agent/extensions/notionmemory"
    assert p.bundle_source.endswith("providers/pi/bundle")
    assert Path(p.bundle_source).is_dir()          # ships in the tree


@pytest.fixture
def fixed_home(tmp_path, monkeypatch):
    monkeypatch.setattr("notionmemory.core.paths.home", lambda: tmp_path)
    return tmp_path


def test_build_pi_emits_bundle_spec_only(fixed_home):
    specs = {s.id: s for s in manifest.build(["pi"], "notionmemory")}
    bundle = specs["pi.bundle"]
    assert bundle.handler == "bundle_mirror"
    assert bundle.path == fixed_home / ".pi" / "agent" / "extensions" / "notionmemory"
    assert bundle.payload["cli_path"] == "notionmemory"
    assert Path(bundle.payload["source"]).is_dir()
    # a bundle provider gets NO hooks spec and NO skill mirrors
    assert "pi.hooks" not in specs
    assert not any(i.startswith("pi.skills.") for i in specs)


def test_sweep_pi_matches_build(fixed_home):
    from notionmemory.core.install import teardown
    swept = {s.id: s for s in teardown._sweep(["pi"])}
    assert swept["pi.bundle"].handler == "bundle_mirror"
    assert swept["pi.bundle"].path == fixed_home / ".pi" / "agent" / "extensions" / "notionmemory"
    assert "pi.hooks" not in swept
