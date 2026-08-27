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
