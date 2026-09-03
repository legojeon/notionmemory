from pathlib import Path

import pytest

from notionmemory import providers
from notionmemory.core.install import harnesses, manifest


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    """Resolve every harness home under a throwaway HOME, with no override envs,
    so detection sees only the dirs/markers the test creates."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for env in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "KIMI_CODE_HOME",
                "PI_HOME", "OPENCODE_CONFIG_DIR"):
        monkeypatch.delenv(env, raising=False)
    return tmp_path


def test_present_but_unwired_harness_is_pending(tmp_path):
    # kimi's config home exists, but notionmemory is not wired into it.
    (tmp_path / ".kimi-code").mkdir()

    pending = {h.name for h in harnesses.pending()}

    assert "kimi" in pending          # present + unwired -> offer it
    assert "pi" not in pending        # no ~/.pi home -> not present -> not offered


def test_wired_harness_is_installed_and_not_pending(tmp_path):
    # hooks-kind: kimi's config.toml carries our hook marker
    kimi = tmp_path / ".kimi-code"
    kimi.mkdir()
    (kimi / "config.toml").write_text(manifest.HOOK_MARKERS[0] + "\n", encoding="utf-8")
    # bundle-kind: opencode's bundle dir AND its opencode.json plugin entry exist
    oc = providers.get("opencode")
    (tmp_path / ".config" / "opencode" / oc.bundle_install_subpath).mkdir(parents=True)
    art = oc.post_install_spec()
    Path(art.path).write_text(art.markers[0], encoding="utf-8")

    by = {h.name: h for h in harnesses.detect()}
    assert by["kimi"].installed is True
    assert by["opencode"].installed is True

    pending = {h.name for h in harnesses.pending()}
    assert "kimi" not in pending
    assert "opencode" not in pending


def test_bundle_partial_install_is_not_wired(tmp_path):
    # opencode's bundle dir exists, but its opencode.json plugin entry is missing —
    # OpenCode won't actually load the plugin, so this must NOT count as wired.
    oc = providers.get("opencode")
    (tmp_path / ".config" / "opencode" / oc.bundle_install_subpath).mkdir(parents=True)

    by = {h.name: h for h in harnesses.detect()}
    assert by["opencode"].installed is False
    assert "opencode" in {h.name for h in harnesses.pending()}   # still offered


def test_install_cmd_carries_provider_extra_flags():
    by = {h.name: h.install_cmd for h in harnesses.detect()}
    # codex needs the trust flag; it must come from the provider spec, not be hardcoded here
    assert by["codex"] == "notionmemory install --codex --trust-codex-hooks"
    assert by["kimi"] == "notionmemory install --kimi"
