"""library 레지스트리 카드 — recall 스킬, run()=refresh(대시보드 버튼)."""
import pytest

from notionmemory.app import build_registry
from notionmemory.core.config import Config
from notionmemory.skills.library.skill import LibrarySkill


def _skill(tmp_path):
    return LibrarySkill(Config.load(str(tmp_path / "none.yaml")))


def test_identity(tmp_path):
    s = _skill(tmp_path)
    assert s.id == "library" and s.name == "Library"
    assert s.kinds == ("recall",) and s.surface == "agent"
    assert s.requires == ["notion"]


def test_registry_includes_library(tmp_path):
    ids = [c.id for c in build_registry(str(tmp_path / "none.yaml")).cards()]
    assert "library" in ids


def test_run_refreshes_the_index(tmp_path, monkeypatch):
    from notionmemory.skills.library import skill as mod
    seen = {}
    monkeypatch.setattr(mod, "NotionSession", lambda **kw: object())

    def fake_refresh(s, *, full=False, log=print):
        seen["ran"] = True
        return {"indexed": 5, "pruned": 0, "total": 5}
    monkeypatch.setattr(mod.crawl, "refresh", fake_refresh)
    r = _skill(tmp_path).run({}, lambda *_: None)
    assert r.ok is True and seen["ran"] and "5" in r.message
