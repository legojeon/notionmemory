from notionmemory.core import detection, notion_auth, notion_broker
from notionmemory.core.config import Config
from notionmemory.core.integrations import IntegrationStatus, build_integrations


def ints_status(cfg, iid) -> IntegrationStatus:
    return build_integrations(cfg)[iid].status(cfg)


def test_all_three_integrations_registered():
    ints = build_integrations(Config({}))
    assert set(ints.keys()) == {"notion", "agent", "git"}


# ── agent ──────────────────────────────────────────────

def test_agent_config_backend_wins_without_probe():
    st = ints_status(Config({"integrations": {"agent": {"backend": "claude"}}}), "agent")
    assert st.connected is True
    assert "claude" in st.detail


def test_agent_detected_via_probe(monkeypatch):
    def fake_probe(cmd, refresh=False):
        if cmd == "claude":
            return detection.Probe(ok=True, path="/bin/claude", version="claude 2.1.0")
        return detection.Probe(ok=False, error="PATH에 없음")

    monkeypatch.setattr(detection, "probe_cli", fake_probe)
    monkeypatch.setattr(detection, "dotfolder", lambda name: True)
    st = ints_status(Config({}), "agent")
    assert st.connected is True
    assert "claude 2.1.0" in st.detail
    assert "~/.claude" in st.detail


def test_agent_falls_back_to_codex(monkeypatch):
    def fake_probe(cmd, refresh=False):
        if cmd == "codex":
            return detection.Probe(ok=True, path="/bin/codex", version="codex 1.5.0")
        return detection.Probe(ok=False, error="PATH에 없음")

    monkeypatch.setattr(detection, "probe_cli", fake_probe)
    monkeypatch.setattr(detection, "dotfolder", lambda name: False)
    st = ints_status(Config({}), "agent")
    assert st.connected is True
    assert "codex" in st.detail


def test_agent_undetected_reports_reason():
    st = ints_status(Config({}), "agent")  # 전역 안전망: which → None
    assert st.connected is False
    assert "not detected" in st.detail


def test_agent_installed_but_broken_is_disconnected(monkeypatch):
    monkeypatch.setattr(detection, "probe_cli",
                        lambda cmd, refresh=False: detection.Probe(ok=False, path="/bin/claude",
                                                                   error="실행 실패(exit 1)"))
    assert ints_status(Config({}), "agent").connected is False


# ── git (GitHub gh CLI) ────────────────────────────────

# `gh` 인증 상태로 git 연동을 판정하던 테스트 2건은 삭제했다 — 그 동작 자체가 버그였다
# (gh 없는 기계에서 정상 동작하는 연동이 "미설치"로 표시됐다). 새 판정(git CLI + 훅 설치)의
# 커버리지는 tests/core/test_git_integration_status.py 에 있다.


def test_git_not_installed():
    st = ints_status(Config({}), "git")  # 전역 안전망: which → None
    assert st.connected is False
    assert "not installed" in st.detail


# ── notion ─────────────────────────────────────────────

def test_notion_connected_via_keyring_pat():
    notion_auth.save_pat("ntn_x")
    st = ints_status(Config({}), "notion")
    assert st.connected is True
    assert "PAT" in st.detail


def test_notion_detail_shows_workspace_name():
    notion_auth.save_pat("ntn_x")
    cfg = Config({"integrations": {"notion": {"workspace_name": "WS"}}})
    assert "WS" in ints_status(cfg, "notion").detail


def test_notion_config_token_fallback():
    st = ints_status(Config({"integrations": {"notion": {"token": "t"}}}), "notion")
    assert st.connected is True


def test_notion_disconnected_without_any_token():
    assert ints_status(Config({}), "notion").connected is False


def test_notion_broker_socket_without_pat_is_not_connected(monkeypatch):
    """Disconnect leaves the broker process running but must clear connection state."""
    monkeypatch.setattr(notion_broker, "available", lambda: True)
    monkeypatch.setattr(notion_broker, "connected", lambda: False)

    assert ints_status(Config({}), "notion").connected is False


# ── ko 오버레이 (config language: ko) ─────────────────────

def test_notion_status_detail_is_korean_when_lang_ko():
    st = ints_status(Config({"language": "ko"}), "notion")
    assert st.detail == "PAT 없음 (연결 필요)"


def test_notion_status_detail_is_english_by_default():
    st = ints_status(Config({}), "notion")
    assert st.detail == "no PAT (connect required)"


def test_notion_test_verifies_via_api(monkeypatch):
    notion_auth.save_pat("ntn_x")
    monkeypatch.setattr(notion_auth, "verify_token", lambda t: {"ok": True, "name": "WS"})
    st = build_integrations(Config({}))["notion"].test(Config({}))
    assert st.connected is True
    assert "WS" in st.detail


def test_notion_test_reports_api_failure(monkeypatch):
    notion_auth.save_pat("ntn_x")
    monkeypatch.setattr(notion_auth, "verify_token",
                        lambda t: {"ok": False, "error": "검증 실패(HTTP 401)"})
    st = build_integrations(Config({}))["notion"].test(Config({}))
    assert st.connected is False
    assert "401" in st.detail


def test_notion_test_without_token_skips_api():
    st = build_integrations(Config({}))["notion"].test(Config({}))
    assert st.connected is False
