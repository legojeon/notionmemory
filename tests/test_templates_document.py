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


def test_edit_sends_update_content():
    s = _store([FakeResp(200, {})])
    s.edit("pid", "old text", "new text")
    method, path, kw = s.session.calls[0]
    assert (method, path) == ("PATCH", "/pages/pid/markdown")
    assert kw["json"] == {"type": "update_content", "update_content":
                          {"content_updates": [{"old_str": "old text", "new_str": "new text"}]}}


def test_edit_all_sets_replace_all_matches():
    s = _store([FakeResp(200, {})])
    s.edit("pid", "x", "y", all_matches=True)
    upd = s.session.calls[0][2]["json"]["update_content"]["content_updates"][0]
    assert upd["replaceAllMatches"] is True


def test_edit_no_match_raises_markdown_edit_error():
    import pytest
    s = _store([FakeResp(400, {"message": "No matches found for zzz."})])
    with pytest.raises(D.MarkdownEditError):
        s.edit("pid", "zzz", "y")


def test_edit_multi_match_raises_markdown_edit_error():
    import pytest
    s = _store([FakeResp(400, {"message": 'Multiple matches found for "dup". Found 2 matches.'})])
    with pytest.raises(D.MarkdownEditError):
        s.edit("pid", "dup", "y")


def test_delete_sends_empty_new_str():
    s = _store([FakeResp(200, {})])
    s.delete("pid", "remove me")
    upd = s.session.calls[0][2]["json"]["update_content"]["content_updates"][0]
    assert upd == {"old_str": "remove me", "new_str": ""}


def test_dead_block_helpers_removed():
    # 블록-id 렌더/편집 표면은 제거됐다(마크다운 API 로 대체).
    assert not hasattr(D, "render_blocks")
    assert not hasattr(D, "block_markdown")
    for gone in ("get_block", "add_blocks", "set_block", "remove_block"):
        assert not hasattr(D.DocumentStore, gone)


def test_image_ops_retained():
    assert hasattr(D.DocumentStore, "upload_image")
    assert hasattr(D.DocumentStore, "add_image")
