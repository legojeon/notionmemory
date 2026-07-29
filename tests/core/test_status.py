from notionmemory.core import status
from notionmemory.core.config import Config


def test_probe_reports_unbound_when_config_empty(monkeypatch):
    monkeypatch.setattr(status.notion_auth, "load_pat", lambda: "")
    p = status.probe(Config({}))
    assert p["notion"]["connected"] is False
    assert p["calendar"]["bound"] is False and p["calendar"]["url"] == ""
    assert p["memory"]["bound"] is False


def test_probe_reports_bound_db_url_without_network(monkeypatch):
    monkeypatch.setattr(status.notion_auth, "load_pat", lambda: "")
    cfg = Config({"skills": {"memory": {"database_id": "abc123", "data_source_id": "d"}}})
    p = status.probe(cfg)
    assert p["memory"]["bound"] is True
    assert "abc123" in p["memory"]["url"]      # db_url 형식


def test_probe_verify_false_makes_no_network_call(monkeypatch):
    """SessionStart 처럼 세션마다 도는 호출부는 verify=False 로 `.status()`(presence-only,
    네트워크 0)에 떨어져야 한다 — `test_injection_makes_no_network_call` 이 강제하는
    불변식을 probe() 쪽에서도 지킨다."""
    monkeypatch.setattr(status.notion_auth, "load_pat", lambda: "secret-token")
    calls = []
    monkeypatch.setattr(status.notion_auth, "verify_token",
                        lambda token: calls.append(token) or {"ok": True, "name": "x"})
    p = status.probe(Config({}), verify=False)
    assert calls == []                      # verify_token 미호출 — 네트워크 0
    assert p["notion"]["connected"] is True  # PAT 존재만으로 connected


def test_probe_verify_true_calls_live_verify(monkeypatch):
    """기본값(verify=True)은 `.test()`로 떨어져 verify_token 을 실제로 한 번 호출한다
    — `notionmemory status` CLI·PAT 게이팅이 기대하는 live verify."""
    monkeypatch.setattr(status.notion_auth, "load_pat", lambda: "secret-token")
    calls = []

    def fake_verify(token):
        calls.append(token)
        return {"ok": True, "name": "Workspace"}

    monkeypatch.setattr(status.notion_auth, "verify_token", fake_verify)
    p = status.probe(Config({}), verify=True)
    assert calls == ["secret-token"]         # verify_token 호출됨 — live verify
    assert p["notion"]["connected"] is True
    assert "Workspace" in p["notion"]["detail"]
