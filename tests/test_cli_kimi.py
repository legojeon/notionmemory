import pytest
from notionmemory import cli


def test_hook_accepts_kimi_harness(monkeypatch):
    seen = {}
    monkeypatch.setattr("notionmemory.hooks.user_prompt.main",
                        lambda harness="claude": seen.update(h=harness) or 0)
    rc = cli.main(["hook", "user-prompt", "--harness", "kimi"])
    assert rc == 0
    assert seen["h"] == "kimi"


def test_hook_rejects_unknown_harness():
    with pytest.raises(SystemExit):            # argparse rejects invalid choice
        cli.main(["hook", "user-prompt", "--harness", "nope"])


def test_install_kimi_flag_targets_only_kimi(monkeypatch, capsys):
    monkeypatch.setattr("notionmemory.cli._resolve_install_language", lambda args: None)
    monkeypatch.setattr("notionmemory.core.install.runner.install",
                        lambda targets, **kw: [f"targets={targets}"])
    rc = cli.main(["install", "--kimi", "--skip-skills"])
    assert rc == 0
    assert "targets=['kimi']" in capsys.readouterr().out


def test_install_no_flags_keeps_default(monkeypatch, capsys):
    monkeypatch.setattr("notionmemory.cli._resolve_install_language", lambda args: None)
    monkeypatch.setattr("notionmemory.core.install.runner.install",
                        lambda targets, **kw: [f"targets={targets}"])
    rc = cli.main(["install", "--skip-skills"])
    assert rc == 0
    assert "targets=['claude', 'codex']" in capsys.readouterr().out   # kimi is opt-in
