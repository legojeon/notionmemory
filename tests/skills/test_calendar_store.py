import pytest

from notionmemory.core.config import Config
from notionmemory.skills.calendar.store import (
    CalendarStore, build_range_filter, date_payload, event_summary,
    format_event_line, local_timezone, new_event_id, parse_when)


@pytest.fixture(autouse=True)
def no_registered_templates(tmp_path, monkeypatch):
    """쓰기 게이트가 개발기의 실제 프로필을 읽지 않게 한다 — 안 그러면 이 파일의
    결과가 그 머신에 등록된 템플릿에 따라 달라진다."""
    monkeypatch.setenv("HOME", str(tmp_path))


def test_new_event_id_format():
    eid = new_event_id(now_ms=1752624000000, rand="abcdefghijkl")
    assert eid.startswith("evt_") and eid.endswith("_abcdefghijkl")
    assert int(eid.split("_")[1], 36) == 1752624000000
    auto = new_event_id()
    assert auto.split("_")[2].isalnum() and len(auto.split("_")[2]) == 12


def test_parse_when_date_only_is_allday():
    assert parse_when("2026-07-21") == ("2026-07-21", True)


def test_parse_when_timed_normalizes_t_and_space():
    assert parse_when("2026-07-21 14:00") == ("2026-07-21T14:00:00", False)
    assert parse_when("2026-07-21T14:00") == ("2026-07-21T14:00:00", False)


def test_parse_when_rejects_bad_formats():
    for bad in ("21/07/2026", "2026-07-21 25:00", "2026-13-01", "내일", ""):
        with pytest.raises(ValueError):
            parse_when(bad)


def test_local_timezone_from_symlink(tmp_path):
    zone = tmp_path / "zoneinfo" / "Asia" / "Seoul"
    zone.parent.mkdir(parents=True)
    zone.write_text("")
    link = tmp_path / "localtime"
    link.symlink_to(zone)
    assert local_timezone(localtime_path=str(link)) == "Asia/Seoul"


def test_local_timezone_falls_back_to_tz_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Paris")
    assert local_timezone(localtime_path=str(tmp_path / "none")) == "Europe/Paris"


def test_local_timezone_rejects_junk_tz_and_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "KST-9")
    assert local_timezone(localtime_path=str(tmp_path / "none")) is None


def test_date_payload_timed_with_iana():
    p = date_payload("2026-07-21T14:00:00", "2026-07-21T15:00:00", False, "Asia/Seoul")
    assert p == {"start": "2026-07-21T14:00:00", "end": "2026-07-21T15:00:00",
                 "time_zone": "Asia/Seoul"}


def test_date_payload_timed_offset_fallback():
    p = date_payload("2026-07-21T14:00:00", "", False, None, offset="+09:00")
    assert p == {"start": "2026-07-21T14:00:00+09:00"}


def test_date_payload_allday():
    assert date_payload("2026-07-21", "", True, "Asia/Seoul") == {"start": "2026-07-21"}
    assert date_payload("2026-07-21", "2026-07-23", True, None) == {
        "start": "2026-07-21", "end": "2026-07-23"}


def _page(eid="evt_1", title="회의", start="2026-07-21T14:00:00.000+09:00",
          end="2026-07-21T15:00:00.000+09:00", status="Scheduled", location="회의실A",
          link="https://meet.example"):
    return {"id": f"pg_{eid}", "url": f"https://notion.so/{eid}", "properties": {
        "Event ID": {"rich_text": [{"plain_text": eid}]},
        "Title": {"title": [{"plain_text": title}]},
        "Date": {"date": {"start": start, "end": end} if end else {"start": start}},
        "Status": {"select": {"name": status}},
        "Location": {"rich_text": [{"plain_text": location}] if location else []},
        "Link": {"url": link or None},
    }}


def test_event_summary_extracts_fields():
    s = event_summary(_page())
    assert s == {"event_id": "evt_1", "title": "회의",
                 "start": "2026-07-21T14:00:00.000+09:00",
                 "end": "2026-07-21T15:00:00.000+09:00", "status": "Scheduled",
                 "location": "회의실A", "link": "https://meet.example",
                 "page_id": "pg_evt_1", "url": "https://notion.so/evt_1"}


def test_event_summary_tolerates_missing_props():
    s = event_summary({"id": "pg", "properties": {}})
    assert s["event_id"] == "" and s["start"] == "" and s["link"] == ""


def test_build_range_filter_excludes_canceled():
    f = build_range_filter("2026-07-20", "2026-07-27")
    assert f == {"and": [
        {"property": "Date", "date": {"on_or_after": "2026-07-20"}},
        {"property": "Date", "date": {"on_or_before": "2026-07-27"}},
        {"property": "Status", "select": {"does_not_equal": "Canceled"}},
    ]}


def test_format_event_line_same_day_timed():
    line = format_event_line(event_summary(_page()))
    assert line == ("evt_1 · 2026-07-21 14:00–15:00 · 회의 @회의실A "
                    "[Scheduled] (https://meet.example)")


def test_format_event_line_allday_minimal():
    s = event_summary(_page(start="2026-07-21", end="", location="", link=""))
    assert format_event_line(s) == "evt_1 · 2026-07-21 · 회의 [Scheduled]"


class FakeSession:
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


def _store(responses):
    cfg = Config({"skills": {"calendar": {"data_source_id": "ds_1"}}}, "")
    return CalendarStore(FakeSession([(200, {"id": "ds_1", "properties": {}})] + responses), cfg)


def test_add_timed_event_builds_props_and_returns_summary(monkeypatch):
    import notionmemory.skills.calendar.store as st
    monkeypatch.setattr(st, "local_timezone", lambda **_: "Asia/Seoul")
    store = _store([(200, {"id": "pg_1", "url": "https://notion.so/pg1"})])
    r = store.add("팀 회의", start="2026-07-21 14:00", end="2026-07-21 15:00",
                  location="회의실A", link="https://meet.example", source="claude")
    assert r["event_id"].startswith("evt_") and r["page_id"] == "pg_1"
    assert r["url"] == "https://notion.so/pg1"
    props = store.db.session.calls[-1][2]["properties"]
    assert props["Date"]["date"] == {"start": "2026-07-21T14:00:00",
                                     "end": "2026-07-21T15:00:00", "time_zone": "Asia/Seoul"}
    assert props["Status"] == {"select": {"name": "Scheduled"}}
    assert props["Source"] == {"select": {"name": "claude"}}
    assert props["Location"]["rich_text"][0]["text"]["content"] == "회의실A"
    assert props["Link"] == {"url": "https://meet.example"}


def test_add_rejects_mixed_allday_and_timed():
    store = _store([])
    with pytest.raises(ValueError):
        store.add("x", start="2026-07-21", end="2026-07-21 15:00")


def test_add_rejects_end_before_start():
    store = _store([])
    with pytest.raises(ValueError):
        store.add("x", start="2026-07-21 15:00", end="2026-07-21 14:00")


def test_list_events_default_window_sorts_and_filters(monkeypatch):
    pages = [_page("evt_b", start="2026-07-22T10:00:00.000+09:00", end=""),
             _page("evt_a", start="2026-07-21", end="")]
    store = _store([(200, {"results": pages, "has_more": False})])
    out = store.list_events(today="2026-07-20")
    assert [s["event_id"] for s in out] == ["evt_a", "evt_b"]  # 시작 오름차순
    sent = store.db.session.calls[-1][2]["filter"]
    assert sent["and"][0] == {"property": "Date", "date": {"on_or_after": "2026-07-20"}}
    assert sent["and"][1] == {"property": "Date", "date": {"on_or_before": "2026-07-27"}}


def test_list_events_timed_bounds_get_local_offset(monkeypatch):
    import notionmemory.skills.calendar.store as st
    monkeypatch.setattr(st, "_utc_offset", lambda: "+09:00")
    store = _store([(200, {"results": [], "has_more": False})])
    store.list_events(date_from="2026-07-21 09:00", date_to="2026-07-21 18:00")
    sent = store.db.session.calls[-1][2]["filter"]
    assert sent["and"][0] == {"property": "Date", "date": {"on_or_after": "2026-07-21T09:00:00+09:00"}}
    assert sent["and"][1] == {"property": "Date", "date": {"on_or_before": "2026-07-21T18:00:00+09:00"}}


def test_list_events_date_only_bounds_stay_naive():
    store = _store([(200, {"results": [], "has_more": False})])
    store.list_events(date_from="2026-07-21", date_to="2026-07-27")
    sent = store.db.session.calls[-1][2]["filter"]
    assert sent["and"][0] == {"property": "Date", "date": {"on_or_after": "2026-07-21"}}


def test_update_start_only_keeps_end(monkeypatch):
    import notionmemory.skills.calendar.store as st
    monkeypatch.setattr(st, "local_timezone", lambda **_: "Asia/Seoul")
    page = _page("evt_1", start="2026-07-21T14:00:00.000+09:00",
                 end="2026-07-21T16:00:00.000+09:00")
    store = _store([(200, {"results": [page]}), (200, {})])
    r = store.update("evt_1", start="2026-07-21 15:00")
    assert r == {"event_id": "evt_1", "warning": ""}
    props = store.db.session.calls[-1][2]["properties"]
    assert props["Date"]["date"] == {"start": "2026-07-21T15:00:00",
                                     "end": "2026-07-21T16:00:00", "time_zone": "Asia/Seoul"}


def test_update_start_after_end_drops_end_with_warning(monkeypatch):
    import notionmemory.skills.calendar.store as st
    monkeypatch.setattr(st, "local_timezone", lambda **_: "Asia/Seoul")
    page = _page("evt_1", start="2026-07-21T14:00:00.000+09:00",
                 end="2026-07-21T15:00:00.000+09:00")
    store = _store([(200, {"results": [page]}), (200, {})])
    r = store.update("evt_1", start="2026-07-21 16:00")
    assert "end" not in store.db.session.calls[-1][2]["properties"]["Date"]["date"]
    assert r["warning"]


def test_update_clear_end_with_empty_string(monkeypatch):
    import notionmemory.skills.calendar.store as st
    monkeypatch.setattr(st, "local_timezone", lambda **_: "Asia/Seoul")
    page = _page("evt_1")
    store = _store([(200, {"results": [page]}), (200, {})])
    store.update("evt_1", end="")
    assert "end" not in store.db.session.calls[-1][2]["properties"]["Date"]["date"]


def test_update_unknown_id_returns_none():
    store = _store([(200, {"results": []})])
    assert store.update("evt_x", title="t") is None


def test_update_title_only_does_not_touch_date():
    page = _page("evt_1")
    store = _store([(200, {"results": [page]}), (200, {})])
    store.update("evt_1", title="새 제목")
    props = store.db.session.calls[-1][2]["properties"]
    assert "Date" not in props and props["Title"]["title"][0]["text"]["content"] == "새 제목"


def test_cancel_trashes_page_with_status_in_one_patch():
    page = _page("evt_1")
    store = _store([(200, {"results": [page]}), (200, {})])
    assert store.cancel("evt_1") is True
    method, path, body, _ = store.db.session.calls[-1]
    assert (method, path) == ("PATCH", "/pages/pg_evt_1")
    assert body == {"in_trash": True,
                    "properties": {"Status": {"select": {"name": "Canceled"}}}}


def test_cancel_unknown_returns_false():
    store = _store([(200, {"results": []})])
    assert store.cancel("evt_x") is False


def test_list_events_on_a_fresh_install_creates_nothing():
    """오늘의 버그: 아무것도 안 한 사용자가 `calendar list` 를 치면 빈 DB 가 생겼다."""
    sess = FakeSession([])
    store = CalendarStore(sess, Config({"skills": {"calendar": {}}}, ""))
    assert store.list_events(today="2026-07-20") == []
    assert sess.calls == []


def test_list_events_with_a_dead_cache_creates_nothing():
    sess = FakeSession([(404, {})])
    store = CalendarStore(sess, Config({"skills": {"calendar": {"data_source_id": "ds_x"}}}, ""))
    assert store.list_events(today="2026-07-20") == []
    assert all(m != "POST" for m, _, _, _ in sess.calls)


def test_add_still_bootstraps_on_first_use():
    """생성은 사라진 게 아니라 쓰기 경로로 옮겨졌을 뿐이다."""
    sess = FakeSession([(200, {"id": "db_1", "data_sources": [{"id": "ds_new"}]}),
                        (200, {"id": "pg_1", "url": "https://notion.so/pg1"})])
    store = CalendarStore(sess, Config({"skills": {"calendar": {}}}, ""))
    assert store.add("첫 일정", start="2026-07-21")["page_id"] == "pg_1"
    assert sess.calls[0][0] == "POST" and sess.calls[0][1] == "/databases"
