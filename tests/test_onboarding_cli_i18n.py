import pytest
from notionmemory.core import messages, config as cfg


def test_catalog_en_ko_keysets_identical_and_nonempty():
    cat = messages.CATALOG
    assert set(cat) == {"en", "ko"}
    assert set(cat["en"]) == set(cat["ko"]), "en/ko 키셋 불일치 — 온보딩 CLI 번역 누락"
    assert cat["en"] and all(v.strip() for v in cat["en"].values())
    assert all(v.strip() for v in cat["ko"].values())


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    from notionmemory.core.install import runner
    monkeypatch.setattr(runner, "resolve_cli", lambda: "/fake/bin/notionmemory")
    return tmp_path


def _config(home, lang):
    from notionmemory.core import paths
    cfg.save_language(str(paths.config_path()), lang)


def test_install_output_language(home):
    from notionmemory.core.install import runner, teardown
    _config(home, "en")
    en_lines = "\n".join(runner.install(["claude"]))
    assert "installed:" in en_lines.lower() or "receipt" in en_lines.lower()
    # teardown to reset, then ko
    teardown.run(["claude"])
    _config(home, "ko")
    ko_lines = "\n".join(runner.install(["claude"]))
    assert "설치" in ko_lines


def test_teardown_output_language(home):
    from notionmemory.core.install import runner, teardown
    _config(home, "en")
    runner.install(["claude"])
    en_td = "\n".join(teardown.run(["claude"]))
    assert "preserved" in en_td.lower() or "notion" in en_td.lower()
    _config(home, "ko")
    runner.install(["claude"])
    ko_td = "\n".join(teardown.run(["claude"]))
    assert "보존" in ko_td


def test_session_start_library_nudge_language(home, monkeypatch):
    from notionmemory.hooks import session_start
    _config(home, "en")
    assert "not scanned" in session_start.library_injection()
    _config(home, "ko")
    assert "훑어" in session_start.library_injection()
