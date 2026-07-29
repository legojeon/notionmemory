import pytest
from notionmemory.skills.memory import notion_db as nd


class FakeResp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = ""
    def json(self):
        return self._body


class FakeSession:
    """calls 를 기록하고 경로별 응답을 돌려주는 최소 세션."""
    def __init__(self, ds_props):
        self.ds_props = ds_props
        self.patched = None
    def request(self, method, path, **kw):
        if method == "GET" and path.startswith("/databases/"):
            return FakeResp(body={"id": "DB", "data_sources": [{"id": "DS"}]})
        if method == "GET" and path.startswith("/data_sources/"):
            return FakeResp(body={"properties": self.ds_props})
        if method == "PATCH" and path.startswith("/data_sources/"):
            self.patched = kw.get("json", {}).get("properties", {})
            return FakeResp(body={})
        raise AssertionError(f"unexpected {method} {path}")


class FakeMeta:
    def __init__(self): self.store = {}
    def get_meta(self, k): return self.store.get(k, "")
    def set_meta(self, k, v): self.store[k] = v


def _sb_props(extra=None):
    p = {"Title": {"type": "title"}, "Mem ID": {"type": "rich_text"}}
    p.update(extra or {})
    return p


def test_adopt_binds_a_valid_second_brain_and_reports_added():
    sess = FakeSession(_sb_props())          # Title+Mem ID 만 — 나머지는 누락
    meta = FakeMeta()
    db = nd.SecondBrainDB(sess)
    added = db.adopt("DB", meta)
    assert meta.get_meta("database_id") == "DB"
    assert meta.get_meta("data_source_id") == "DS"
    assert "Excerpt" in added and "Type" in added        # PROPERTIES 누락분 추가
    assert set(added) == set(sess.patched.keys())


def test_adopt_refuses_a_db_without_mem_id():
    sess = FakeSession({"Title": {"type": "title"}})      # Mem ID 없음
    with pytest.raises(nd.NotASecondBrainError):
        nd.SecondBrainDB(sess).adopt("DB", FakeMeta())


def test_adopt_refuses_wrong_typed_identifier():
    sess = FakeSession({"Title": {"type": "title"}, "Mem ID": {"type": "number"}})
    with pytest.raises(nd.NotASecondBrainError):
        nd.SecondBrainDB(sess).adopt("DB", FakeMeta())
