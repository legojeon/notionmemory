"""Task 2: Link url 속성 + store.remember(url=) + CLI --url (외부 URL, 예: GitHub 커밋)."""
from notionmemory import cli
from notionmemory.skills.memory.notion_db import PROPERTIES, SecondBrainDB

MEM = {"id": "mem_1", "title": "T", "content": "본문", "type": "fact",
       "concepts": [], "strength": 7, "source": "git",
       "version": 1, "project": "", "files": [],
       "relatedIds": [], "linkPageIds": [],
       "createdAt": "2026-07-20T00:00:00+00:00", "updatedAt": "2026-07-20T00:00:00+00:00"}


class FakeSession:
    """(method, path) → 응답 목록을 순서대로 소비하는 페이크. 호출 기록을 남긴다."""
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs.get("json"), kwargs.get("params")))
        status, body = self.responses.pop(0)

        class R:
            status_code = status
            text = ""
            def json(self):
                return body
        return R()


class Meta:
    def __init__(self, **kv):
        self.d = dict(kv)

    def get_meta(self, key):
        return self.d.get(key, "")

    def set_meta(self, key, value):
        self.d[key] = value


# 1) PROPERTIES에 Link url 존재
def test_properties_include_link():
    assert PROPERTIES["Link"] == {"url": {}}


# 2) create_page: url이 있으면 POST /pages payload에 Link 포함
def test_create_page_includes_link_when_url_present():
    mem = dict(MEM, url="https://github.com/u/r/commit/abc")
    fs = FakeSession([(200, {"id": "pg_1"})])
    SecondBrainDB(fs).create_page("ds_1", mem)
    props = fs.calls[0][2]["properties"]
    assert props["Link"] == {"url": "https://github.com/u/r/commit/abc"}


# 3) url="" 이면 Link 속성 자체를 보내지 않는다
def test_create_page_omits_link_when_url_empty():
    mem = dict(MEM, url="")
    fs = FakeSession([(200, {"id": "pg_1"})])
    SecondBrainDB(fs).create_page("ds_1", mem)
    props = fs.calls[0][2]["properties"]
    assert "Link" not in props


def test_create_page_omits_link_when_url_absent():
    fs = FakeSession([(200, {"id": "pg_1"})])
    SecondBrainDB(fs).create_page("ds_1", MEM)  # url 키 자체가 없는 memory dict
    props = fs.calls[0][2]["properties"]
    assert "Link" not in props


# 4) ensure(): 기존 data source에 Link만 없으면 PATCH로 Link만 추가
def test_ensure_patches_missing_link_only():
    meta = Meta(data_source_id="ds_old")
    fs = FakeSession([
        (200, {"id": "ds_old", "properties": {"Excerpt": {"rich_text": {}}}}),  # Link 없음
        (200, {}),
    ])
    assert SecondBrainDB(fs).ensure("", meta) == "ds_old"
    method, path, payload, _ = fs.calls[1]
    assert (method, path) == ("PATCH", "/data_sources/ds_old")
    assert payload == {"properties": {"Link": {"url": {}}}}


# Excerpt와 Link가 모두 없으면 한 번의 PATCH에 함께 실어 보낸다
def test_ensure_patches_missing_excerpt_and_link_together():
    meta = Meta(data_source_id="ds_old")
    fs = FakeSession([
        (200, {"id": "ds_old", "properties": {"Title": {"title": {}}}}),  # 둘 다 없음
        (200, {}),
    ])
    assert SecondBrainDB(fs).ensure("", meta) == "ds_old"
    method, path, payload, _ = fs.calls[1]
    assert (method, path) == ("PATCH", "/data_sources/ds_old")
    assert payload == {"properties": {"Excerpt": {"rich_text": {}}, "Link": {"url": {}}}}


def test_ensure_no_patch_when_excerpt_and_link_present():
    meta = Meta(data_source_id="ds_ok")
    fs = FakeSession([
        (200, {"id": "ds_ok", "properties": {"Excerpt": {"rich_text": {}}, "Link": {"url": {}}}}),
    ])
    assert SecondBrainDB(fs).ensure("", meta) == "ds_ok"
    assert len(fs.calls) == 1  # PATCH 없음


# 5a) store.remember(url=...) 가 memory dict에 url을 실어 db.create_page에 전달
class FakeDB:
    def __init__(self):
        self.created = []

    def ensure(self, parent, meta, *, create=True):
        meta.set_meta("data_source_id", "ds_1")
        return "ds_1"

    def create_page(self, ds, memory):
        self.created.append(memory)
        return "pg_new"


def _store(db):
    from notionmemory.core.config import Config
    from notionmemory.skills.memory.store import ConfigMeta, MemoryStore
    s = MemoryStore.__new__(MemoryStore)
    s.db, s.config = db, Config({}, "")
    s.meta = ConfigMeta(s.config)
    return s


def test_remember_threads_url_into_memory():
    db = FakeDB()
    _store(db).remember("커밋 요약", mem_type="fact",
                        url="https://github.com/u/r/commit/abc")
    assert db.created[0]["url"] == "https://github.com/u/r/commit/abc"


def test_remember_default_url_is_empty():
    db = FakeDB()
    _store(db).remember("본문", mem_type="fact")
    assert db.created[0]["url"] == ""


# 5b) CLI: remember --url ... 이 FakeStore.remember에 url= 로 전달됨
def test_cli_remember_passes_url(tmp_path, monkeypatch):
    saved = {}

    class FakeStore:
        def __init__(self, *a, **k): ...
        def remember(self, content, **kw):
            saved.update(kw)
            return {"mem_id": "mem_x", "concepts": []}

    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills: {}\n", encoding="utf-8")
    monkeypatch.setattr(cli, "MemoryStore", FakeStore)
    monkeypatch.setattr(cli, "NotionSession", lambda: object())
    rc = cli.main(["remember", "커밋 요약", "--type", "fact",
                   "--source", "git", "--url", "https://github.com/u/r/commit/abc",
                   "--config", str(cfg)])
    assert rc == 0
    assert saved["url"] == "https://github.com/u/r/commit/abc"
