import json
from pathlib import Path
from notionmemory.core.install.handlers import OpencodeConfigEntry
from notionmemory.core.install.spec import ArtifactSpec

ENTRY = "file:///Users/bob/.notionmemory/opencode-plugin/notionmemory.js"


def _spec(path: Path, entry: str = ENTRY) -> ArtifactSpec:
    return ArtifactSpec(id="opencode.config", owner="_core", handler="opencode_config_entry",
                        target="opencode", path=path, payload={"entry": entry},
                        markers=(entry,))


def test_install_creates_missing_file(tmp_path):
    p = tmp_path / "opencode.json"
    h = OpencodeConfigEntry()
    assert h.install(_spec(p)) is True
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw == {"plugin": [ENTRY]}
    assert h.detect(_spec(p)) is True


def test_install_is_idempotent(tmp_path):
    p = tmp_path / "opencode.json"
    h = OpencodeConfigEntry()
    h.install(_spec(p))
    assert h.install(_spec(p)) is False
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["plugin"] == [ENTRY]


def test_install_preserves_user_content(tmp_path):
    p = tmp_path / "opencode.json"
    p.write_text(json.dumps({"model": "x", "plugin": ["file://other"]}), encoding="utf-8")
    h = OpencodeConfigEntry()
    assert h.install(_spec(p)) is True
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["model"] == "x"
    assert "file://other" in raw["plugin"]
    assert ENTRY in raw["plugin"]


def test_remove_strips_only_ours(tmp_path):
    p = tmp_path / "opencode.json"
    p.write_text(json.dumps({"model": "x", "plugin": ["file://other"]}), encoding="utf-8")
    h = OpencodeConfigEntry()
    h.install(_spec(p))
    assert h.remove(_spec(p)) is True
    assert p.exists()
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["plugin"] == ["file://other"]
    assert raw["model"] == "x"
    assert h.detect(_spec(p)) is False


def test_remove_without_our_entry_is_noop(tmp_path):
    p = tmp_path / "opencode.json"
    p.write_text(json.dumps({"model": "x", "plugin": ["file://other"]}), encoding="utf-8")
    h = OpencodeConfigEntry()
    before = p.read_text(encoding="utf-8")
    assert h.remove(_spec(p)) is False
    assert p.read_text(encoding="utf-8") == before


def test_non_list_plugin_guard_does_not_clobber(tmp_path):
    p = tmp_path / "opencode.json"
    p.write_text(json.dumps({"plugin": "oops"}), encoding="utf-8")
    h = OpencodeConfigEntry()
    assert h.install(_spec(p)) is False
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["plugin"] == "oops"


def test_install_treats_unparseable_json_as_empty(tmp_path):
    p = tmp_path / "opencode.json"
    p.write_text("not { valid json", encoding="utf-8")
    h = OpencodeConfigEntry()
    assert h.install(_spec(p)) is True
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw == {"plugin": [ENTRY]}


def test_detect_and_remove_key_off_markers_not_only_entry(tmp_path):
    """Rename-safety (CLAUDE.md rule 4): a renamed marker's old entries must still be
    found and removed even though spec.payload["entry"] no longer matches them."""
    legacy_entry = "file:///Users/bob/.notionmemory/opencode-plugin-old/notionmemory.js"
    p = tmp_path / "opencode.json"
    p.write_text(json.dumps({"plugin": [legacy_entry]}), encoding="utf-8")
    spec = ArtifactSpec(id="opencode.config", owner="_core", handler="opencode_config_entry",
                        target="opencode", path=p, payload={"entry": ENTRY},
                        markers=(ENTRY, legacy_entry))
    h = OpencodeConfigEntry()
    assert h.detect(spec) is True
    assert h.remove(spec) is True
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["plugin"] == []
    assert h.detect(spec) is False


def test_install_strips_stale_marker_entries_before_appending(tmp_path):
    """A rename should clean up the old marker's stale entry, not just append the new one."""
    legacy_entry = "file:///Users/bob/.notionmemory/opencode-plugin-old/notionmemory.js"
    p = tmp_path / "opencode.json"
    p.write_text(json.dumps({"plugin": [legacy_entry, "file://other"]}), encoding="utf-8")
    spec = ArtifactSpec(id="opencode.config", owner="_core", handler="opencode_config_entry",
                        target="opencode", path=p, payload={"entry": ENTRY},
                        markers=(ENTRY, legacy_entry))
    h = OpencodeConfigEntry()
    assert h.install(spec) is True
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["plugin"] == ["file://other", ENTRY]
