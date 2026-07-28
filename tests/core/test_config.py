import pytest
import yaml

from notionmemory.core.config import Config
from notionmemory.core import config as config_mod


def test_save_skill_options_merges_and_writes(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("skills:\n  notes:\n    language: ko\n", encoding="utf-8")
    config_mod.save_skill_options(str(p), "notes", {"tone": "친근하게", "limit": 3})
    raw = yaml.safe_load(p.read_text())["skills"]["notes"]
    assert raw == {"language": "ko", "tone": "친근하게", "limit": 3}


def test_save_skill_options_creates_section_when_absent(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("integrations: {}\n", encoding="utf-8")
    config_mod.save_skill_options(str(p), "notes", {"language": "en"})
    assert yaml.safe_load(p.read_text())["skills"]["notes"] == {"language": "en"}


def test_load_reads_integration_and_skill_options(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "integrations:\n"
        "  notion:\n"
        "    token: secret-123\n"
        "skills:\n"
        "  other-skill:\n"
        "    min_strength: 8\n"
    )
    cfg = Config.load(str(p))
    assert cfg.integration("notion") == {"token": "secret-123"}
    assert cfg.skill_options("other-skill") == {"min_strength": 8}
    assert cfg.integration("missing") == {}
    assert cfg.skill_options("missing") == {}

def test_load_missing_file_returns_empty(tmp_path):
    cfg = Config.load(str(tmp_path / "nope.yaml"))
    assert cfg.data == {}
    assert cfg.integration("notion") == {}

def test_load_malformed_root_list_becomes_empty(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("- a\n- b\n")
    cfg = Config.load(str(p))
    assert cfg.data == {}
    assert cfg.integration("notion") == {}

def test_load_records_path(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("{}")
    assert Config.load(str(p)).path == str(p)
    assert Config.load(str(tmp_path / "missing.yaml")).path == str(tmp_path / "missing.yaml")
    assert Config({}).path == ""


def test_write_raw_atomic_no_tmp_leftover(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("old: 1\n", encoding="utf-8")
    config_mod._write_raw(str(p), {"new": 2})
    assert yaml.safe_load(p.read_text()) == {"new": 2}
    assert [f.name for f in tmp_path.iterdir()] == ["config.yaml"]  # tmp 잔여물 없음


def test_write_raw_failure_keeps_original_and_cleans_tmp(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("keep: true\n", encoding="utf-8")

    def boom(*a, **kw):
        raise RuntimeError("dump 실패")

    monkeypatch.setattr(config_mod.yaml, "safe_dump", boom)
    with pytest.raises(RuntimeError):
        config_mod._write_raw(str(p), {"new": 2})
    assert yaml.safe_load(p.read_text()) == {"keep": True}          # 원본 무손상
    assert [f.name for f in tmp_path.iterdir()] == ["config.yaml"]  # tmp 정리됨


def test_save_skill_options_returns_merged_section(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("skills:\n  memory:\n    top_n: 5\n", encoding="utf-8")
    merged = config_mod.save_skill_options(str(p), "memory", {"data_source_id": "ds"})
    assert merged == {"top_n": 5, "data_source_id": "ds"}
