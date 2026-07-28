import sys
import types
import pytest
from notionmemory.core.config import Config


@pytest.fixture
def cfgpath(tmp_path, monkeypatch):
    from notionmemory.core import paths
    p = tmp_path / ".config" / "notionmemory" / "config.yaml"
    p.parent.mkdir(parents=True)
    monkeypatch.setattr(paths, "config_path", lambda: p)
    return p


def _resolve(monkeypatch, args_language=None, isatty=False, answer="1"):
    from notionmemory import cli
    monkeypatch.setattr(sys.stdin, "isatty", lambda: isatty)
    if isatty:
        monkeypatch.setattr("builtins.input", lambda *_: answer)
    args = types.SimpleNamespace(language=args_language)
    cli._resolve_install_language(args)


def test_flag_writes_config(cfgpath, monkeypatch):
    _resolve(monkeypatch, args_language="ko")
    assert Config.load(str(cfgpath)).get("language") == "ko"


def test_existing_config_not_reprompted(cfgpath, monkeypatch):
    from notionmemory.core import config as cfg
    cfg.save_language(str(cfgpath), "ko")
    _resolve(monkeypatch, args_language=None, isatty=True, answer="1")  # would pick en if prompted
    assert Config.load(str(cfgpath)).get("language") == "ko"           # kept, not reprompted


def test_headless_no_tty_does_not_prompt_or_block(cfgpath, monkeypatch):
    # isatty False, no flag: must not call input(), must not write
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(AssertionError("prompted in headless")))
    _resolve(monkeypatch, args_language=None, isatty=False)
    assert Config.load(str(cfgpath)).get("language") is None           # unset -> resolver defaults en


def test_tty_prompt_writes_choice(cfgpath, monkeypatch):
    _resolve(monkeypatch, args_language=None, isatty=True, answer="2")  # 2 = 한국어
    assert Config.load(str(cfgpath)).get("language") == "ko"
