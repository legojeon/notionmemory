from notionmemory import cli
from notionmemory.core.install.harnesses import HarnessState


def test_harnesses_lists_pending_with_install_cmd(monkeypatch, capsys):
    monkeypatch.setattr(
        "notionmemory.core.install.harnesses.pending",
        lambda: [HarnessState("opencode", "OpenCode", True, False,
                              "notionmemory install --opencode")])
    assert cli.main(["harnesses"]) == 0
    out = capsys.readouterr().out
    assert "OpenCode" in out
    assert "notionmemory install --opencode" in out


def test_harnesses_none_pending_says_nothing_to_wire(monkeypatch, capsys):
    monkeypatch.setattr("notionmemory.core.install.harnesses.pending", lambda: [])
    assert cli.main(["harnesses"]) == 0
    out = capsys.readouterr().out
    assert "install --" not in out          # nothing offered
