import pytest
from notionmemory.skills.memory.notion_db import (
    ALL_TYPES, PROPERTIES, SecondBrainDB, page_id_from_url)

MEM = {"id": "mem_1", "title": "T", "content": "# H\nbody", "type": "fact",
       "concepts": ["a,b", "jwt-refresh"], "strength": 7, "source": "claude",
       "version": 1, "project": "notionmemory", "files": ["a.py"],
       "relatedIds": ["mem_9"], "linkPageIds": [],
       "createdAt": "2026-07-16T00:00:00+00:00", "updatedAt": "2026-07-16T01:00:00+00:00"}


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
    """get_meta/set_meta 프로토콜의 최소 구현 (SQLite → config 전환 후 계약)."""
    def __init__(self, **kv):
        self.d = dict(kv)

    def get_meta(self, key):
        return self.d.get(key, "")

    def set_meta(self, key, value):
        self.d[key] = value


def test_all_types_owned_here():
    assert ALL_TYPES == ("pattern", "preference", "architecture", "bug", "workflow", "fact")


def test_properties_include_excerpt():
    assert PROPERTIES["Excerpt"] == {"rich_text": {}}


def test_page_id_from_url_variants():
    hex32 = "a488cdd5b1e24f0e8b1cdd5b1e24f0e8"
    uuid = "a488cdd5-b1e2-4f0e-8b1c-dd5b1e24f0e8"
    assert page_id_from_url(f"https://www.notion.so/My-Note-{hex32}") == uuid
    assert page_id_from_url(f"https://www.notion.so/{hex32}?v=abc") == uuid
    with pytest.raises(ValueError):
        page_id_from_url("https://www.notion.so/no-id-here")


def test_ensure_returns_cached_when_alive_and_has_excerpt():
    meta = Meta(data_source_id="ds_cached")
    fs = FakeSession([(200, {"id": "ds_cached",
                             "properties": {"Excerpt": {"rich_text": {}}, "Link": {"url": {}}}})])
    assert SecondBrainDB(fs).ensure("", meta) == "ds_cached"
    assert [c[:2] for c in fs.calls] == [("GET", "/data_sources/ds_cached")]


def test_ensure_patches_missing_excerpt_schema_evolution():
    meta = Meta(data_source_id="ds_old")
    fs = FakeSession([
        (200, {"id": "ds_old", "properties": {"Title": {"title": {}}}}),  # Excerpt/Link 둘 다 없음
        (200, {}),                                                        # PATCH /data_sources/ds_old
    ])
    assert SecondBrainDB(fs).ensure("", meta) == "ds_old"
    method, path, payload, _ = fs.calls[1]
    assert (method, path) == ("PATCH", "/data_sources/ds_old")
    # 없는 속성을 모두 모아 한 번의 PATCH로 보낸다 (Excerpt/Link 진화 분기 일반화)
    assert payload == {"properties": {"Excerpt": {"rich_text": {}}, "Link": {"url": {}}}}


def test_ensure_creates_database_under_parent():
    meta = Meta()
    fs = FakeSession([(200, {"id": "db_1", "data_sources": [{"id": "ds_new"}]})])
    ds = SecondBrainDB(fs).ensure("parent_page", meta)
    assert ds == "ds_new" and meta.get_meta("data_source_id") == "ds_new"
    assert meta.get_meta("database_id") == "db_1"
    method, path, payload, _ = fs.calls[0]
    assert (method, path) == ("POST", "/databases")
    assert payload["parent"] == {"type": "page_id", "page_id": "parent_page"}
    assert payload["initial_data_source"]["properties"] == PROPERTIES


def test_ensure_without_parent_creates_at_workspace_root():
    # parent_page_id 미지정 시 래퍼 페이지 없이 워크스페이스 최상위에 DB 직접 생성.
    # (2025-09 API가 database의 workspace parent를 지원함 — 실 API로 확인)
    meta = Meta()
    fs = FakeSession([(200, {"id": "db_1", "data_sources": [{"id": "ds_new"}]})])
    assert SecondBrainDB(fs).ensure("", meta) == "ds_new"
    method, path, payload, _ = fs.calls[0]  # /search·페이지 생성 없이 단일 호출
    assert (method, path) == ("POST", "/databases")
    assert payload["parent"] == {"type": "workspace", "workspace": True}


def test_ensure_rebootstraps_when_cached_dead():
    meta = Meta(data_source_id="ds_dead")
    fs = FakeSession([
        (404, {}),
        (200, {"id": "db_2", "data_sources": [{"id": "ds_fresh"}]}),
    ])
    assert SecondBrainDB(fs).ensure("parent_page", meta) == "ds_fresh"
    assert meta.get_meta("data_source_id") == "ds_fresh"


def test_ensure_raises_on_transient_error():
    meta = Meta(data_source_id="ds_cached")
    fs = FakeSession([(429, {})])
    with pytest.raises(RuntimeError):
        SecondBrainDB(fs).ensure("", meta)
    assert meta.get_meta("data_source_id") == "ds_cached"  # meta 불변


def test_create_page_props_excerpt_and_source():
    fs = FakeSession([(200, {"id": "pg_1"})])
    page_id = SecondBrainDB(fs).create_page("ds_1", MEM)
    assert page_id == "pg_1"
    _, _, payload, _ = fs.calls[0]
    props = payload["properties"]
    assert payload["parent"] == {"data_source_id": "ds_1"}
    assert props["Mem ID"]["rich_text"][0]["text"]["content"] == "mem_1"
    assert props["Source"]["select"]["name"] == "claude"          # 명시 인자 (derive 아님)
    assert props["Excerpt"]["rich_text"][0]["text"]["content"] == "# H\nbody"
    assert props["Strength"]["number"] == 7
    assert props["Status"]["select"]["name"] == "Active"
    names = [o["name"] for o in props["Concepts"]["multi_select"]]
    assert "a·b" in names                                          # 콤마 치환 유지


def test_create_page_excerpt_truncated_to_2000():
    mem = dict(MEM, content="x" * 5000)
    fs = FakeSession([(200, {"id": "pg_1"})])
    SecondBrainDB(fs).create_page("ds_1", mem)
    excerpt = fs.calls[0][2]["properties"]["Excerpt"]["rich_text"][0]["text"]["content"]
    assert len(excerpt) == 2000


def test_create_page_related_mixes_ids_and_mentions():
    mem = dict(MEM, relatedIds=["mem_9", "mem_8"],
               linkPageIds=["11111111-2222-3333-4444-555555555555"])
    fs = FakeSession([(200, {"id": "pg_1"})])
    SecondBrainDB(fs).create_page("ds_1", mem)
    related = fs.calls[0][2]["properties"]["Related"]["rich_text"]
    assert related[0]["text"]["content"] == "mem_9, mem_8"
    mentions = [r for r in related if "mention" in r]
    assert mentions[0]["mention"]["page"]["id"] == "11111111-2222-3333-4444-555555555555"


def test_create_page_chunks_blocks_over_100():
    long_content = "\n\n".join(f"para {i}" for i in range(150))  # 150 블록 → 100+50
    mem = dict(MEM, content=long_content)
    fs = FakeSession([
        (200, {"id": "pg_1"}),   # POST /pages (앞 100)
        (200, {}),               # PATCH /blocks/pg_1/children (나머지 50)
    ])
    SecondBrainDB(fs).create_page("ds_1", mem)
    assert len(fs.calls[0][2]["children"]) == 100
    assert len(fs.calls[1][2]["children"]) == 50


def test_find_page_by_mem_id_returns_full_page():
    page = {"id": "pg_9", "properties": {"Title": {"title": []}}}
    fs = FakeSession([(200, {"results": [page]})])
    assert SecondBrainDB(fs).find_page_by_mem_id("ds_1", "mem_9") == page
    _, path, payload, _ = fs.calls[0]
    assert path == "/data_sources/ds_1/query"
    assert payload["filter"]["rich_text"]["equals"] == "mem_9"


def test_find_page_by_mem_id_none_when_missing():
    fs = FakeSession([(200, {"results": []})])
    assert SecondBrainDB(fs).find_page_by_mem_id("ds_1", "mem_x") is None


def test_query_paginates_with_cursor():
    fs = FakeSession([
        (200, {"results": [{"id": "p1"}], "has_more": True, "next_cursor": "c2"}),
        (200, {"results": [{"id": "p2"}], "has_more": False}),
    ])
    filt = {"and": []}
    pages = SecondBrainDB(fs).query("ds_1", filt)
    assert [p["id"] for p in pages] == ["p1", "p2"]
    assert fs.calls[0][2] == {"filter": filt, "page_size": 100}
    assert fs.calls[1][2]["start_cursor"] == "c2"


def test_page_content_joins_plain_text():
    fs = FakeSession([
        (200, {"results": [
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "hello "},
                                                              {"plain_text": "world"}]}},
            {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "H"}]}},
        ], "has_more": False}),
    ])
    assert SecondBrainDB(fs).page_content("pg_1") == "hello world\nH"


def test_page_content_skips_textless_blocks_keeps_empty_paragraph():
    fs = FakeSession([
        (200, {"results": [
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "위"}]}},
            {"type": "divider", "divider": {}},                       # 텍스트 없는 블록 — 줄 안 냄
            {"type": "image", "image": {"file": {"url": "http://x"}}},
            {"type": "paragraph", "paragraph": {"rich_text": []}},    # 의도된 빈 문단 — 빈 줄 유지
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "아래"}]}},
        ], "has_more": False}),
    ])
    assert SecondBrainDB(fs).page_content("pg_1") == "위\n\n아래"


def test_set_status_patches_select_only():
    fs = FakeSession([(200, {})])
    SecondBrainDB(fs).set_status("pg_1", "Forgotten")
    _, path, payload, _ = fs.calls[0]
    assert path == "/pages/pg_1"
    assert payload == {"properties": {"Status": {"select": {"name": "Forgotten"}}}}


def test_error_raises():
    fs = FakeSession([(400, {"message": "bad"})])
    with pytest.raises(RuntimeError):
        SecondBrainDB(fs).set_status("pg_1", "Stale")
