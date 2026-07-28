import pytest
from notionmemory.core import notion_client
from notionmemory.core.notion_client import NotionSession


class FakeResp:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body


def test_requires_token(fake_keyring):
    with pytest.raises(RuntimeError):
        NotionSession()


def test_request_sets_headers_and_relative_path(monkeypatch):
    seen = {}

    def fake_request(method, url, headers=None, timeout=None, **kw):
        seen.update(method=method, url=url, headers=headers)
        return FakeResp(200)
    monkeypatch.setattr(notion_client.requests, "request", fake_request)
    s = NotionSession(token="tk")
    assert s.request("GET", "/pages/abc").status_code == 200
    assert seen["url"] == "https://api.notion.com/v1/pages/abc"
    assert seen["headers"]["Authorization"] == "Bearer tk"
    assert seen["headers"]["Notion-Version"] == notion_client.VERSION


def test_request_retries_on_429(monkeypatch):
    calls = []

    def fake_request(method, url, headers=None, timeout=None, **kw):
        calls.append(1)
        return FakeResp(429, headers={"Retry-After": "0"}) if len(calls) < 3 else FakeResp(200)
    monkeypatch.setattr(notion_client.requests, "request", fake_request)
    monkeypatch.setattr(notion_client._time, "sleep", lambda s: None)
    assert NotionSession(token="tk").request("POST", "/pages").status_code == 200
    assert len(calls) == 3


def test_request_retries_on_http_date_retry_after(monkeypatch):
    """Retry-After with HTTP-date (RFC 7231) should fall back to exponential delay, not crash."""
    calls = []
    sleep_calls = []

    def fake_request(method, url, headers=None, timeout=None, **kw):
        calls.append(1)
        if len(calls) == 1:
            return FakeResp(429, headers={"Retry-After": "Fri, 31 Dec 2026 23:59:59 GMT"})
        return FakeResp(200)

    def fake_sleep(s):
        sleep_calls.append(s)

    monkeypatch.setattr(notion_client.requests, "request", fake_request)
    monkeypatch.setattr(notion_client._time, "sleep", fake_sleep)

    # Should succeed without ValueError
    assert NotionSession(token="tk").request("POST", "/pages").status_code == 200
    assert len(calls) == 2
    # Should sleep with exponential fallback (2^0 = 1)
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == 1


def test_request_exhausts_retries_returns_last_response(monkeypatch):
    """When all retries are exhausted, return the last 429 response without exception."""
    calls = []

    def fake_request(method, url, headers=None, timeout=None, **kw):
        calls.append(1)
        return FakeResp(429, headers={"Retry-After": "0"})

    monkeypatch.setattr(notion_client.requests, "request", fake_request)
    monkeypatch.setattr(notion_client._time, "sleep", lambda s: None)

    resp = NotionSession(token="tk").request("POST", "/pages")
    # Should return the final 429 response
    assert resp.status_code == 429
    # Should have attempted exactly MAX_RETRIES times
    assert len(calls) == notion_client.MAX_RETRIES


def test_notion_version_single_source():
    """API 버전 리터럴은 notion_auth.py 한 곳에만 존재해야 한다."""
    import pathlib
    pkg = pathlib.Path(notion_client.__file__).resolve().parents[1]
    hits = sorted(p for p in pkg.rglob("*.py") if "2026-03-11" in p.read_text(encoding="utf-8"))
    assert hits == [pkg / "core" / "notion_auth.py"]


def test_request_timeout_override(monkeypatch):
    seen = {}

    def fake_request(method, url, headers=None, timeout=None, **kw):
        seen["timeout"] = timeout
        return FakeResp(200)
    monkeypatch.setattr(notion_client.requests, "request", fake_request)
    s = NotionSession(token="tk")
    s.request("GET", "/x")
    assert seen["timeout"] == 60
    s.request("POST", "/y", timeout=120)
    assert seen["timeout"] == 120


def test_request_retries_resend_same_files_body(monkeypatch):
    """429 재시도 시 files= 바디(bytes)가 그대로 재사용돼야 한다(빈 파트 방지 회귀 가드)."""
    calls = []

    def fake_request(method, url, headers=None, timeout=None, **kw):
        calls.append({"headers": headers, "timeout": timeout, "kw": kw})
        if len(calls) == 1:
            return FakeResp(429, headers={"Retry-After": "0"})
        return FakeResp(200)

    monkeypatch.setattr(notion_client.requests, "request", fake_request)
    monkeypatch.setattr(notion_client._time, "sleep", lambda s: None)

    resp = NotionSession(token="tk").request(
        "POST", "/file_uploads/x/send",
        files={"file": ("a.png", b"PAYLOAD", "image/png")}, timeout=120)

    assert resp.status_code == 200
    assert len(calls) == 2
    for call in calls:
        assert "Content-Type" not in call["headers"]
        assert call["kw"]["files"]["file"][1] == b"PAYLOAD"
        assert call["timeout"] == 120


def test_request_files_drops_content_type(monkeypatch):
    """multipart는 requests가 boundary 포함 Content-Type을 스스로 설정해야 한다."""
    seen = {}

    def fake_request(method, url, headers=None, timeout=None, **kw):
        seen["headers"] = headers
        return FakeResp(200)
    monkeypatch.setattr(notion_client.requests, "request", fake_request)
    NotionSession(token="tk").request(
        "POST", "https://files.example/send", files={"file": ("a.png", b"x", "image/png")})
    assert "Content-Type" not in seen["headers"]
    assert seen["headers"]["Authorization"] == "Bearer tk"
    assert seen["headers"]["Notion-Version"] == notion_client.VERSION
