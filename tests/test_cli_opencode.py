from notionmemory import cli
from notionmemory.skills.memory import notion_db


def test_opencode_is_a_source():
    assert "opencode" in notion_db.SOURCES


def test_install_opencode_flag_targets_only_opencode(monkeypatch, capsys):
    monkeypatch.setattr("notionmemory.cli._resolve_install_language", lambda args: None)
    monkeypatch.setattr("notionmemory.core.install.runner.install",
                        lambda targets, **kw: [f"targets={targets}"])
    assert cli.main(["install", "--opencode"]) == 0
    assert "targets=['opencode']" in capsys.readouterr().out


def test_install_no_flags_still_default(monkeypatch, capsys):
    monkeypatch.setattr("notionmemory.cli._resolve_install_language", lambda args: None)
    monkeypatch.setattr("notionmemory.core.install.runner.install",
                        lambda targets, **kw: [f"targets={targets}"])
    assert cli.main(["install"]) == 0
    assert "targets=['claude', 'codex']" in capsys.readouterr().out
