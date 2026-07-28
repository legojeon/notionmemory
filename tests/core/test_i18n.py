from notionmemory.core import config as cfg
from notionmemory.core.config import Config
from notionmemory.core import i18n


def test_language_defaults_to_en_and_validates(tmp_path):
    assert i18n.language(Config({})) == "en"
    assert i18n.language(Config({"language": "ko"})) == "ko"
    assert i18n.language(Config({"language": "en"})) == "en"
    assert i18n.language(Config({"language": "fr"})) == "en"   # invalid -> en
    assert i18n.language(Config({"language": ""})) == "en"


def test_t_picks_language_formats_and_falls_back():
    cat = {"en": {"hi": "Hello {name}", "only_en": "E"}, "ko": {"hi": "안녕 {name}"}}
    assert i18n.t(cat, "hi", "ko", name="Sam") == "안녕 Sam"
    assert i18n.t(cat, "hi", "en", name="Sam") == "Hello Sam"
    assert i18n.t(cat, "only_en", "ko") == "E"                 # missing key -> en fallback


def test_save_language_writes_and_preserves_other_keys(tmp_path):
    p = str(tmp_path / "config.yaml")
    cfg.save_skill_options(p, "memory", {"database_id": "abc"})
    cfg.save_language(p, "ko")
    loaded = Config.load(p)
    assert loaded.get("language") == "ko"
    assert loaded.skill_options("memory")["database_id"] == "abc"   # untouched
