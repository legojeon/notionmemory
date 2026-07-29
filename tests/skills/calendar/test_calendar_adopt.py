import pytest
from notionmemory.skills.calendar import notion_db as nd


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


def _cal_props(over=None):
    base = {"Title": {"type": "title"}, "Event ID": {"type": "rich_text"},
            "Date": {"type": "date"}, "Status": {"type": "select"},
            "Location": {"type": "rich_text"}, "Link": {"type": "url"},
            "Source": {"type": "select"}}
    base.update(over or {})
    return base


def test_adopt_reconnect_identical_schema_adds_nothing():
    sess = FakeSession(_cal_props()); meta = FakeMeta()
    added = nd.CalendarDB(sess).adopt("DB", meta)
    assert added == []
    assert meta.get_meta("data_source_id") == "DS"


def test_adopt_foreign_db_adds_missing_columns():
    props = {"Title": {"type": "title"}, "Date": {"type": "date"}}  # Event ID 등 누락
    sess = FakeSession(props)
    added = nd.CalendarDB(sess).adopt("DB", FakeMeta())
    assert "Event ID" in added and "Status" in added


def test_adopt_hard_conflict_wrong_type_refuses():
    sess = FakeSession(_cal_props({"Date": {"type": "rich_text"}}))  # Date 타입 충돌
    with pytest.raises(nd.SchemaConflictError):
        nd.CalendarDB(sess).adopt("DB", FakeMeta())
