"""ensure() 는 휴지통/아카이브된 data source(GET 200 이지만 쓰기 전부 실패)를 무효
캐시로 보고 재부트스트랩해야 한다. 라이브 e2e 가 잡은 회귀: 바인딩이 휴지통 DB 를 가리키면
스키마 진화 PATCH 가 혼란스러운 404 로 터지며 remember 가 통째로 막혔다."""
from notionmemory.skills.memory import notion_db as mem_nd
from notionmemory.skills.calendar import notion_db as cal_nd


class FakeResp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = ""

    def json(self):
        return self._body


class TrashedThenCreateSession:
    """GET /data_sources/{cached} → 200 이지만 in_trash. POST /databases → 새 DB."""
    def __init__(self):
        self.posted_databases = False

    def request(self, method, path, **kw):
        if method == "GET" and path.startswith("/data_sources/"):
            return FakeResp(200, {"in_trash": True, "properties": {}})
        if method == "POST" and path == "/databases":
            self.posted_databases = True
            return FakeResp(200, {"id": "new_db", "data_sources": [{"id": "new_ds"}]})
        raise AssertionError(f"unexpected {method} {path}")


class FakeMeta:
    def __init__(self, ds):
        self.store = {"data_source_id": ds}

    def get_meta(self, k):
        return self.store.get(k, "")

    def set_meta(self, k, v):
        self.store[k] = v


def test_memory_ensure_reboots_when_cached_ds_is_trashed():
    sess = TrashedThenCreateSession()
    meta = FakeMeta("trashed_ds")
    ds = mem_nd.SecondBrainDB(sess).ensure("", meta)
    assert sess.posted_databases is True          # 재부트스트랩(새 DB 생성)
    assert ds == "new_ds"                          # 휴지통 ds 를 그대로 안 씀
    assert meta.get_meta("data_source_id") == "new_ds"   # 새 바인딩 기록


def test_calendar_ensure_reboots_when_cached_ds_is_trashed():
    sess = TrashedThenCreateSession()
    meta = FakeMeta("trashed_ds")
    ds = cal_nd.CalendarDB(sess).ensure("", meta, create=True)
    assert sess.posted_databases is True and ds == "new_ds"


class TrashedReadOnlySession:
    def request(self, method, path, **kw):
        if method == "GET" and path.startswith("/data_sources/"):
            return FakeResp(200, {"in_trash": True, "properties": {}})
        raise AssertionError(f"must not write on create=False: {method} {path}")


def test_calendar_ensure_create_false_returns_empty_on_trashed():
    # 조회 경로(create=False)는 휴지통이어도 새 DB 를 만들지 않고 "" 를 준다.
    ds = cal_nd.CalendarDB(TrashedReadOnlySession()).ensure("", FakeMeta("trashed_ds"), create=False)
    assert ds == ""
