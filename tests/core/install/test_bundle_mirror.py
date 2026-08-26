import json
from pathlib import Path
import pytest
from notionmemory.core.install.handlers import BundleMirror, OwnershipConflict, OWNED_MARKER_FILE
from notionmemory.core.install.spec import ArtifactSpec


def _src(tmp_path):
    src = tmp_path / "pkg" / "bundle"
    src.mkdir(parents=True)
    (src / "index.ts").write_text("export default function(){}\n", encoding="utf-8")
    return src


def _spec(src, dest, cli="/opt/bin/notionmemory"):
    return ArtifactSpec(id="pi.bundle", owner="_core", handler="bundle_mirror",
                        target="pi", path=dest,
                        payload={"source": str(src), "cli_path": cli},
                        markers=("notionmemory pi",))


def test_install_copies_bundle_and_writes_cli_json(tmp_path):
    src = _src(tmp_path)
    dest = tmp_path / "home" / "agent" / "extensions" / "notionmemory"
    h = BundleMirror()
    assert h.install(_spec(src, dest)) is True
    assert (dest / "index.ts").is_file()
    assert (dest / OWNED_MARKER_FILE).is_file()
    assert json.loads((dest / "notionmemory.json").read_text())["cli"] == "/opt/bin/notionmemory"
    assert h.detect(_spec(src, dest)) is True


def test_reinstall_refreshes(tmp_path):
    src = _src(tmp_path)
    dest = tmp_path / "home" / "ext" / "notionmemory"
    h = BundleMirror()
    h.install(_spec(src, dest, cli="/old/notionmemory"))
    (src / "index.ts").write_text("export default function(){/*v2*/}\n", encoding="utf-8")
    h.install(_spec(src, dest, cli="/new/notionmemory"))
    assert "v2" in (dest / "index.ts").read_text()
    assert json.loads((dest / "notionmemory.json").read_text())["cli"] == "/new/notionmemory"


def test_refuses_unowned_existing_dir(tmp_path):
    src = _src(tmp_path)
    dest = tmp_path / "home" / "ext" / "notionmemory"
    dest.mkdir(parents=True)
    (dest / "user-file.ts").write_text("mine\n", encoding="utf-8")   # no sidecar
    with pytest.raises(OwnershipConflict):
        BundleMirror().install(_spec(src, dest))


def test_remove_only_when_owned(tmp_path):
    src = _src(tmp_path)
    dest = tmp_path / "home" / "ext" / "notionmemory"
    h = BundleMirror()
    h.install(_spec(src, dest))
    assert h.remove(_spec(src, dest)) is True
    assert not dest.exists()
    # a non-owned dir is left alone
    dest.mkdir(parents=True)
    (dest / "x").write_text("y", encoding="utf-8")
    assert h.remove(ArtifactSpec(id="pi.bundle", owner="_core", handler="bundle_mirror",
                                 target="pi", path=dest, payload={}, markers=())) is False
    assert dest.exists()
