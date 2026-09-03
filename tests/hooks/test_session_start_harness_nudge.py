import io
import json

from notionmemory.core.install.harnesses import HarnessState
from notionmemory.hooks import session_start


def _pending_opencode():
    return [HarnessState("opencode", "OpenCode", True, False,
                         "notionmemory install --opencode")]


def _silence_main(monkeypatch, tmp_path):
    """Neutralize every other main() output source + isolate config, so a test can
    assert only whether the harness nudge is printed via main()'s real wiring."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("", encoding="utf-8")
    monkeypatch.setattr("notionmemory.core.paths.config_path", lambda: cfg)
    monkeypatch.setattr("notionmemory.core.install.harnesses.pending", _pending_opencode)
    monkeypatch.setattr(session_start, "resolve_toplevel", lambda cwd: "")
    for name in ("maybe_install_git_hook", "templates_injection", "library_injection",
                 "memory_index_injection", "library_full_refresh_injection",
                 "version_drift_injection", "memory_injection", "git_queue_reminder"):
        monkeypatch.setattr(session_start, name, lambda *a, **k: "")
    monkeypatch.setattr(session_start.cq, "list_jobs", lambda: [])
    monkeypatch.setattr("notionmemory.skills.memory.autorun.maybe_spawn", lambda *a, **k: None)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": "/x/proj"})))


def test_main_prints_nudge_when_onboarding_not_offered(tmp_path, monkeypatch, capsys):
    _silence_main(monkeypatch, tmp_path)
    monkeypatch.setattr(session_start, "onboarding_injection", lambda: "")
    assert session_start.main() == 0
    assert "opencode" in capsys.readouterr().out          # nudge reaches the agent


def test_main_suppresses_nudge_during_onboarding_offer(tmp_path, monkeypatch, capsys):
    _silence_main(monkeypatch, tmp_path)
    monkeypatch.setattr(session_start, "onboarding_injection", lambda: "SETUP-OFFER")
    assert session_start.main() == 0
    out = capsys.readouterr().out
    assert "SETUP-OFFER" in out                            # onboarding offer wins
    assert "opencode" not in out                           # harness nudge suppressed


def test_harness_nudge_fires_then_gates(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("", encoding="utf-8")
    monkeypatch.setattr("notionmemory.core.paths.config_path", lambda: cfg)
    monkeypatch.setattr("notionmemory.core.install.harnesses.pending", _pending_opencode)

    first = session_start.harness_wiring_injection()
    assert "opencode" in first                     # names the pending harness

    second = session_start.harness_wiring_injection()
    assert second == ""                            # gate recorded -> no re-nag


def test_harness_nudge_silent_when_already_seen(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("onboarding:\n  harness_nudges_seen: [opencode]\n", encoding="utf-8")
    monkeypatch.setattr("notionmemory.core.paths.config_path", lambda: cfg)
    monkeypatch.setattr("notionmemory.core.install.harnesses.pending", _pending_opencode)

    assert session_start.harness_wiring_injection() == ""
