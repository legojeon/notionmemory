from notionmemory import cli
from notionmemory.skills.memory import notion_db


def test_pi_is_a_source():
    assert "pi" in notion_db.SOURCES


def test_install_pi_flag_targets_only_pi(monkeypatch, capsys):
    monkeypatch.setattr("notionmemory.cli._resolve_install_language", lambda args: None)
    monkeypatch.setattr("notionmemory.core.install.runner.install",
                        lambda targets, **kw: [f"targets={targets}"])
    assert cli.main(["install", "--pi"]) == 0
    assert "targets=['pi']" in capsys.readouterr().out


def test_install_no_flags_still_default(monkeypatch, capsys):
    monkeypatch.setattr("notionmemory.cli._resolve_install_language", lambda args: None)
    monkeypatch.setattr("notionmemory.core.install.runner.install",
                        lambda targets, **kw: [f"targets={targets}"])
    assert cli.main(["install"]) == 0
    assert "targets=['claude', 'codex']" in capsys.readouterr().out    # pi opt-in only
