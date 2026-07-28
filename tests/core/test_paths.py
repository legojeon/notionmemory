"""XDG 경로 해석 + 레포 config 마이그레이션."""
from pathlib import Path

from notionmemory.core import paths


def test_config_path_honors_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert paths.config_path() == tmp_path / "xdg" / "notionmemory" / "config.yaml"


def test_config_path_falls_back_to_home(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.config_path() == tmp_path / ".config" / "notionmemory" / "config.yaml"


def test_state_dir_and_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.state_dir() == tmp_path / ".local" / "state" / "notionmemory"
    assert paths.receipt_path() == paths.state_dir() / "install-receipt.json"


def test_migrate_copies_repo_config_once(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    legacy = tmp_path / "repo" / "config.yaml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("skills:\n  memory:\n    capture_mode: auto\n", encoding="utf-8")
    monkeypatch.setattr(paths, "legacy_repo_config", lambda: legacy)

    msg = paths.migrate_config()

    assert paths.config_path().is_file()
    assert "capture_mode: auto" in paths.config_path().read_text(encoding="utf-8")
    assert str(paths.config_path()) in msg
    # 원본은 보존한다 — 되돌릴 여지를 남긴다
    assert legacy.is_file()


def test_migrate_is_noop_when_target_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    target = tmp_path / "xdg" / "notionmemory" / "config.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("existing: true\n", encoding="utf-8")
    legacy = tmp_path / "repo" / "config.yaml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy: true\n", encoding="utf-8")
    monkeypatch.setattr(paths, "legacy_repo_config", lambda: legacy)

    assert paths.migrate_config() == ""
    # 기존 XDG config 를 덮어쓰지 않는다
    assert target.read_text(encoding="utf-8") == "existing: true\n"


def test_migrate_is_noop_without_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(paths, "legacy_repo_config", lambda: tmp_path / "nope.yaml")
    assert paths.migrate_config() == ""
    assert not paths.config_path().exists()
