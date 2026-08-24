from notionmemory.skills.templates import document as D


class FakeResp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body or {}
        self.text = text
    def json(self):
        return self._body


class FakeSession:
    """responses: callable(method, path, kwargs) -> FakeResp, or a list popped in order."""
    def __init__(self, responses):
        self.calls = []
        self._responses = responses
    def request(self, method, path, **kw):
        self.calls.append((method, path, kw))
        r = self._responses
        return r(method, path, kw) if callable(r) else r.pop(0)


def _store(responses):
    return D.DocumentStore(FakeSession(responses), log=lambda *_: None)


def test_read_returns_markdown_field():
    s = _store(lambda m, p, k: FakeResp(200, {"markdown": "# T\n\nbody", "truncated": False}))
    assert s.read("pid") == "# T\n\nbody"
    assert s.session.calls[0][0] == "GET"
    assert s.session.calls[0][1] == "/pages/pid/markdown"


def test_read_appends_truncation_marker_when_truncated():
    s = _store(lambda m, p, k: FakeResp(200, {"markdown": "partial", "truncated": True}))
    out = s.read("pid")
    assert "partial" in out
    assert D.TRUNCATION_MARKER in out


def test_current_markdown_never_adds_marker():
    s = _store(lambda m, p, k: FakeResp(200, {"markdown": "partial", "truncated": True}))
    assert s.current_markdown("pid") == "partial"
