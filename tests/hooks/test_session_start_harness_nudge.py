from notionmemory.core.install.harnesses import HarnessState
from notionmemory.hooks import session_start


def _pending_opencode():
    return [HarnessState("opencode", "OpenCode", True, False,
                         "notionmemory install --opencode")]


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
