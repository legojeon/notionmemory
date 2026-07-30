import os
from notionmemory.core import config as cfg
from notionmemory.core.config import Config


def test_offered_defaults_false(tmp_path):
    p = str(tmp_path / "config.yaml")
    assert Config.load(p).onboarding_offered() is False


def test_save_offered_sets_true_and_persists(tmp_path):
    p = str(tmp_path / "config.yaml")
    cfg.save_onboarding_offered(p)
    assert Config.load(p).onboarding_offered() is True


def test_save_offered_preserves_other_keys(tmp_path):
    p = str(tmp_path / "config.yaml")
    cfg.save_language(p, "ko")
    cfg.save_skill_options(p, "memory", {"database_id": "abc"})
    cfg.save_onboarding_offered(p)
    loaded = Config.load(p)
    assert loaded.get("language") == "ko"
    assert loaded.skill_options("memory").get("database_id") == "abc"
    assert loaded.onboarding_offered() is True
