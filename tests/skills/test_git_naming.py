"""이름 개정(스펙 2026-07-20): notesync/gitsync 폐기 — 한 스킬 한 이름."""
from notionmemory import cli
from notionmemory.skills.memory.notion_db import SOURCES


def test_sources_use_skill_names():
    assert SOURCES == ("manual", "claude", "codex", "pi", "opencode", "kimi", "notes", "git")


def test_remember_accepts_git_source(tmp_path, monkeypatch):
    saved = {}

    class FakeStore:
        def __init__(self, *a, **k): ...
        def remember(self, content, **kw):
            saved.update(kw)
            return {"mem_id": "mem_x", "concepts": []}

    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills: {}\n", encoding="utf-8")
    monkeypatch.setattr(cli, "MemoryStore", FakeStore)
    monkeypatch.setattr(cli, "NotionSession", lambda: object())
    rc = cli.main(["remember", "커밋 요약", "--type", "fact",
                   "--source", "git", "--config", str(cfg)])
    assert rc == 0
    assert saved["source"] == "git"
