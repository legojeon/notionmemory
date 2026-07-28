import requests
import yaml

from notionmemory.core import notion_auth


def test_pat_roundtrip():
    notion_auth.save_pat("ntn_abc")
    assert notion_auth.load_pat() == "ntn_abc"
    notion_auth.delete_pat()
    assert notion_auth.load_pat() == ""


class _Resp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_verify_token_ok(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"], seen["headers"], seen["timeout"] = url, headers, timeout
        return _Resp(200, {"name": "notionmemory-bot", "bot": {"workspace_name": "WS"}})

    monkeypatch.setattr(notion_auth.requests, "get", fake_get)
    r = notion_auth.verify_token("ntn_x")
    assert r == {"ok": True, "name": "notionmemory-bot"}
    assert seen["url"] == "https://api.notion.com/v1/users/me"
    assert seen["headers"]["Authorization"] == "Bearer ntn_x"
    assert seen["headers"]["Notion-Version"] == "2026-03-11"
    assert seen["timeout"] == 10


def test_verify_token_falls_back_to_workspace_name(monkeypatch):
    monkeypatch.setattr(notion_auth.requests, "get",
                        lambda *a, **k: _Resp(200, {"bot": {"workspace_name": "WS"}}))
    assert notion_auth.verify_token("t")["name"] == "WS"


def test_verify_token_unauthorized(monkeypatch):
    monkeypatch.setattr(notion_auth.requests, "get", lambda *a, **k: _Resp(401, {}))
    r = notion_auth.verify_token("bad")
    assert r["ok"] is False
    assert "401" in r["error"]


def test_verify_token_network_error(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(notion_auth.requests, "get", boom)
    r = notion_auth.verify_token("x")
    assert r["ok"] is False
    assert "네트워크" in r["error"]


def test_save_connection_meta_never_writes_token(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("integrations:\n  notion:\n    token: old-secret\n")
    notion_auth.save_connection_meta(str(p), "WS")
    n = yaml.safe_load(p.read_text())["integrations"]["notion"]
    assert n["auth_mode"] == "pat"
    assert n["workspace_name"] == "WS"
    assert n["token"] == ""


def test_clear_connection_meta(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "integrations:\n  notion:\n    auth_mode: pat\n    workspace_name: WS\n    token: x\n"
    )
    notion_auth.clear_connection_meta(str(p))
    n = yaml.safe_load(p.read_text())["integrations"]["notion"]
    assert "auth_mode" not in n and "workspace_name" not in n
    assert n["token"] == ""


def test_save_connection_meta_missing_file(tmp_path):
    p = tmp_path / "new.yaml"
    notion_auth.save_connection_meta(str(p), "WS")
    n = yaml.safe_load(p.read_text())["integrations"]["notion"]
    assert n["workspace_name"] == "WS"


def test_save_connection_meta_handles_null_sections(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("integrations:\n  notion:\n")
    notion_auth.save_connection_meta(str(p), "WS")
    n = yaml.safe_load(p.read_text())["integrations"]["notion"]
    assert n["workspace_name"] == "WS"


def test_clear_connection_meta_handles_null_sections(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("integrations:\n")
    notion_auth.clear_connection_meta(str(p))  # must not crash
