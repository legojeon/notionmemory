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


def test_add_page_posts_markdown_body():
    s = _store(lambda m, p, k: FakeResp(200, {"id": "new", "url": "http://x"}))
    r = s.add_page("parent", "Title", "# Body")
    assert r == {"id": "new", "url": "http://x"}
    method, path, kw = s.session.calls[0]
    assert (method, path) == ("POST", "/pages")
    body = kw["json"]
    assert body["parent"] == {"page_id": "parent"}
    assert body["markdown"] == "# Body"
    assert body["properties"]["title"]["title"][0]["text"]["content"] == "Title"


def test_append_uses_insert_content_end():
    s = _store(lambda m, p, k: FakeResp(200, {}))
    s.append("pid", "more text")
    method, path, kw = s.session.calls[0]
    assert (method, path) == ("PATCH", "/pages/pid/markdown")
    assert kw["json"] == {"type": "insert_content",
                          "insert_content": {"content": "more text",
                                             "position": {"type": "end"}}}


def test_replace_sends_replace_content_when_not_truncated():
    resps = [FakeResp(200, {"markdown": "old", "truncated": False}),  # _get_markdown
             FakeResp(200, {})]                                        # PATCH
    s = _store(resps)
    s.replace("pid", "brand new")
    patch_call = s.session.calls[1]
    assert patch_call[0] == "PATCH"
    assert patch_call[2]["json"] == {"type": "replace_content",
                                     "replace_content": {"new_str": "brand new"}}


def test_replace_refuses_when_truncated():
    import pytest
    s = _store([FakeResp(200, {"markdown": "partial", "truncated": True})])
    with pytest.raises(RuntimeError):
        s.replace("pid", "brand new")
    # 변이 PATCH 는 절대 나가지 않는다 — GET 하나만.
    assert len(s.session.calls) == 1
    assert s.session.calls[0][0] == "GET"
