from notionmemory.skills.calendar.notion_db import (
    CONNECT_HINT, DB_TITLE, PROPERTIES, SETUP_STEPS, SOURCES, STATUSES, CalendarDB, db_url, rt)


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


def test_schema_seed():
    assert DB_TITLE == "Calendar"
    assert STATUSES == ("Scheduled", "Done", "Canceled")
    assert SOURCES == ("manual", "claude", "codex")
    assert set(PROPERTIES) == {"Title", "Event ID", "Date", "Status", "Location", "Link", "Source"}
    assert PROPERTIES["Date"] == {"date": {}}
    assert [o["name"] for o in PROPERTIES["Status"]["select"]["options"]] == list(STATUSES)


def test_setup_steps_cover_three_app_steps_and_color_tip():
    text = "\n".join(SETUP_STEPS)
    # 앱 자동 설정은 불가(공개 API 없음) — 안내가 유일한 수단이므로 3단계가 모두 있어야 한다
    assert "Add Notion workspace" in text          # ① 워크스페이스 연결
    assert "Add Notion database" in text           # ② DB 추가
    assert "기본 캘린더" in text and "default" in text.lower()   # ③ 기본 캘린더 지정(핵심)
    assert "색" in text                             # 색상 변경 팁
    assert DB_TITLE in text


def test_connect_hint_is_derived_from_setup_steps():
    """부트스트랩 1회 출력·CLI setup·대시보드가 갈라지지 않도록 단일 출처."""
    for step in SETUP_STEPS:
        assert step in CONNECT_HINT
    # 웹/문서가 그대로 쓰도록 단계 문자열엔 CLI 장식(불릿)이 없어야 한다
    assert not any(s.startswith((" ", "·", "-")) for s in SETUP_STEPS)


def test_db_url_from_database_id():
    assert db_url("31981995-e160-42fe-822e-09a1786a5df0") == \
        "https://www.notion.so/31981995e16042fe822e09a1786a5df0"
    assert db_url("") == ""


def test_rt_caps_2000():
    assert rt("x" * 3000)[0]["text"]["content"] == "x" * 2000
    assert rt("")[0]["text"]["content"] == ""


def test_ensure_returns_cached_when_alive():
    meta = Meta(data_source_id="ds_c")
    fs = FakeSession([(200, {"id": "ds_c", "properties": {}})])
    assert CalendarDB(fs).ensure("", meta) == "ds_c"
    assert [c[:2] for c in fs.calls] == [("GET", "/data_sources/ds_c")]


def test_ensure_rebootstraps_on_404_and_logs_hint():
    meta = Meta(data_source_id="ds_dead")
    fs = FakeSession([
        (404, {}),
        (200, {"id": "db_1", "data_sources": [{"id": "ds_new"}]}),
    ])
    logs = []
    assert CalendarDB(fs, log=logs.append).ensure("", meta) == "ds_new"
    assert meta.d["database_id"] == "db_1" and meta.d["data_source_id"] == "ds_new"
    create = fs.calls[1]
    assert create[:2] == ("POST", "/databases")
    assert create[2]["parent"] == {"type": "workspace", "workspace": True}
    assert create[2]["initial_data_source"]["properties"] == PROPERTIES
    assert any("Notion Calendar 앱" in l for l in logs)  # 연결 안내 출력


def test_ensure_uses_page_parent_when_given():
    fs = FakeSession([(200, {"id": "db_1", "data_sources": [{"id": "ds_1"}]})])
    CalendarDB(fs).ensure("pg_parent", Meta())
    assert fs.calls[0][2]["parent"] == {"type": "page_id", "page_id": "pg_parent"}


def test_find_page_by_event_id():
    fs = FakeSession([(200, {"results": [{"id": "pg_1"}]})])
    page = CalendarDB(fs).find_page_by_event_id("ds", "evt_1")
    assert page == {"id": "pg_1"}
    assert fs.calls[0][2]["filter"] == {"property": "Event ID", "rich_text": {"equals": "evt_1"}}
    fs2 = FakeSession([(200, {"results": []})])
    assert CalendarDB(fs2).find_page_by_event_id("ds", "evt_x") is None


def test_create_page_with_and_without_notes():
    fs = FakeSession([(200, {"id": "pg_1", "url": "https://notion.so/pg1"})])
    page = CalendarDB(fs).create_page("ds", {"Title": {"title": rt("t")}})
    assert page["id"] == "pg_1"
    assert fs.calls[0][2]["children"] == []
    fs2 = FakeSession([(200, {"id": "pg_2"})])
    CalendarDB(fs2).create_page("ds", {}, notes="메모 한 줄")
    assert fs2.calls[0][2]["children"]  # markdown_to_blocks 결과가 들어간다


def test_trash_page_archives_with_optional_props():
    fs = FakeSession([(200, {})])
    CalendarDB(fs).trash_page("pg_1", {"Status": {"select": {"name": "Canceled"}}})
    assert fs.calls[0][:2] == ("PATCH", "/pages/pg_1")
    assert fs.calls[0][2] == {"in_trash": True,
                              "properties": {"Status": {"select": {"name": "Canceled"}}}}
    fs2 = FakeSession([(200, {})])
    CalendarDB(fs2).trash_page("pg_2")
    assert fs2.calls[0][2] == {"in_trash": True}


def test_ensure_without_create_returns_empty_when_there_is_no_cache():
    """조회 경로는 DB를 만들지 않는다 — 부작용은 쓰기 경로에만 있다."""
    fs = FakeSession([])
    assert CalendarDB(fs).ensure("", Meta(), create=False) == ""
    assert fs.calls == []


def test_ensure_without_create_does_not_rebootstrap_a_dead_cache():
    fs = FakeSession([(404, {})])
    assert CalendarDB(fs).ensure("", Meta(data_source_id="ds_dead"), create=False) == ""
    assert all(m != "POST" for m, _, _, _ in fs.calls)


def test_ensure_without_create_still_returns_a_live_cache():
    fs = FakeSession([(200, {"id": "ds_c"})])
    assert CalendarDB(fs).ensure("", Meta(data_source_id="ds_c"), create=False) == "ds_c"


def test_ensure_with_create_is_unchanged():
    """기본값은 그대로 — 기존 호출부(add/update/cancel)의 동작에 회귀가 없다."""
    fs = FakeSession([(200, {"id": "db_1", "data_sources": [{"id": "ds_new"}]})])
    assert CalendarDB(fs).ensure("", Meta()) == "ds_new"
    assert fs.calls[0][0] == "POST"
