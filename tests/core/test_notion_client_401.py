"""NotionSession 이 401(만료·회전·폐기된 토큰)을 만나면 일반 실패가 아니라 명확한
재연결 안내를 담은 NotionAuthError 를 낸다(detect-on-use). 404 등 다른 코드는 그대로
resp 를 돌려줘야 한다(ensure() 의 휴지통/404 부트스트랩 로직 보존)."""
import pytest

from notionmemory.core import notion_client


class _Resp:
    def __init__(self, code):
        self.status_code = code
        self.headers = {}

    def json(self):
        return {"object": "error", "status": self.status_code}


def _session_with(monkeypatch, code):
    monkeypatch.setattr(notion_client.requests, "request",
                        lambda *a, **k: _Resp(code))
    return notion_client.NotionSession(token="ntn_fake")


def test_401_raises_notion_auth_error(monkeypatch):
    sess = _session_with(monkeypatch, 401)
    with pytest.raises(notion_client.NotionAuthError) as ei:
        sess.request("GET", "/users/me")
    msg = str(ei.value)
    low = msg.lower()
    assert "401" in msg
    # 재연결 경로를 명확히 가리켜야 한다(일반 "API 요청 실패" 가 아님)
    assert "settings" in low or "reconnect" in low or "재연결" in low


def test_notion_auth_error_is_runtimeerror():
    # CLI 의 기존 `except RuntimeError` 블록들이 그대로 잡아 str(e) 를 출력하도록.
    assert issubclass(notion_client.NotionAuthError, RuntimeError)


def test_404_still_returns_response_not_raise(monkeypatch):
    sess = _session_with(monkeypatch, 404)
    resp = sess.request("GET", "/data_sources/x")   # ensure() 의 404 부트스트랩 경로
    assert resp.status_code == 404


def test_200_returns_response(monkeypatch):
    sess = _session_with(monkeypatch, 200)
    resp = sess.request("GET", "/users/me")
    assert resp.status_code == 200
