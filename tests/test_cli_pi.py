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


def test_hook_input_file_feeds_stdin(tmp_path, monkeypatch):
    """pi shim passes the hook payload via --input-file (pi's exec has no stdin
    channel); the CLI must redirect sys.stdin to that file so hook mains read it."""
    import sys
    payload = tmp_path / "p.json"
    payload.write_text('{"prompt":"hi","cwd":"/x"}', encoding="utf-8")
    seen = {}

    def fake_main(harness="claude"):
        seen["stdin"] = sys.stdin.read()
        seen["harness"] = harness
        return 0

    monkeypatch.setattr("notionmemory.hooks.user_prompt.main", fake_main)
    rc = cli.main(["hook", "user-prompt", "--harness", "pi", "--input-file", str(payload)])
    assert rc == 0
    assert seen["stdin"] == '{"prompt":"hi","cwd":"/x"}'
    assert seen["harness"] == "pi"
