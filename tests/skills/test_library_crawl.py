"""library 크롤 — POST /search 발견 + 증분(watermark) + full 재열거·prune."""
import pytest

from notionmemory.skills.library import crawl as C
from notionmemory.skills.library import index as I
from tests.skills.test_templates_store import FakeResp, FakeSession


@pytest.fixture(autouse=True)
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _page(pid, title, edited):
    return {"id": pid, "object": "page", "url": f"https://n/{pid}",
            "last_edited_time": edited,
            "properties": {"title": {"type": "title",
                                     "title": [{"plain_text": title}]}}}


def _heading(text, level=2):
    return {"id": f"h_{text}", "type": f"heading_{level}",
            f"heading_{level}": {"rich_text": [{"plain_text": text}]}}


def _search(results, has_more=False, cursor=None):
    return FakeResp(200, {"results": results, "has_more": has_more,
                          "next_cursor": cursor})


def _children(*blocks):
    return FakeResp(200, {"results": list(blocks), "has_more": False})


def test_full_refresh_indexes_title_and_headings():
    sess = FakeSession({
        ("POST", "/search"): _search([_page("pg1", "논문정리", "2026-07-24T10:00:00.000Z")]),
        ("GET", "/blocks/pg1/children"): _children(_heading("요약"), _heading("핵심"))})
    summary = C.refresh(sess, full=True)
    idx = I.load()
    assert idx["pages"]["pg1"]["title"] == "논문정리"
    assert idx["pages"]["pg1"]["headings"] == ["요약", "핵심"]
    assert summary["indexed"] == 1 and summary["total"] == 1


def test_refresh_stamps_last_run_even_on_empty_workspace():
    """빈 워크스페이스라 아무것도 색인 안 돼도 last_run 은 찍혀야 한다(→ was_refreshed True,
    빈-워크스페이스 넛지 억제). watermark(last_refreshed)만으론 미갱신과 구분이 안 된다."""
    sess = FakeSession({("POST", "/search"): _search([])})
    C.refresh(sess, full=True)
    idx = I.load()
    assert I.count(idx) == 0
    assert idx["last_run"]                     # 벽시계 마커가 찍혔다
    assert I.was_refreshed(idx) is True


def test_refresh_sets_watermark_to_max_edited_time():
    sess = FakeSession({
        ("POST", "/search"): _search([
            _page("pg2", "새것", "2026-07-24T12:00:00.000Z"),
            _page("pg1", "옛것", "2026-07-20T09:00:00.000Z")]),
        ("GET", "/blocks/pg1/children"): _children(),
        ("GET", "/blocks/pg2/children"): _children()})
    C.refresh(sess, full=True)
    assert I.watermark(I.load()) == "2026-07-24T12:00:00.000Z"


def test_incremental_stops_at_watermark():
    """증분: 정렬(edited desc)에서 watermark 보다 오래된 페이지를 만나면 멈춘다."""
    idx = I.load()
    idx["last_refreshed"] = "2026-07-22T00:00:00.000Z"
    I.upsert(idx, "old", title="이미", headings=[], url="u", last_edited_time="2026-07-20T00:00:00.000Z")
    I.save(idx)
    sess = FakeSession({
        ("POST", "/search"): _search([
            _page("new", "새것", "2026-07-24T00:00:00.000Z"),          # > watermark → 색인
            _page("old", "옛것", "2026-07-20T00:00:00.000Z")]),        # <= watermark → 멈춤
        ("GET", "/blocks/new/children"): _children(_heading("메모"))})
    summary = C.refresh(sess, full=False)
    assert summary["indexed"] == 1                    # new 만
    assert "new" in I.load()["pages"]
    # old/children 는 안 불렀다(watermark 에서 멈춤)
    assert all(c[1] != "/blocks/old/children" for c in sess.calls)


def test_full_prunes_pages_no_longer_shared():
    idx = I.load()
    I.upsert(idx, "gone", title="사라짐", headings=[], url="u", last_edited_time="t")
    I.upsert(idx, "keep", title="유지", headings=[], url="u", last_edited_time="t")
    I.save(idx)
    sess = FakeSession({    # search 에 keep 만 나옴 → gone 은 공유 해제됨
        ("POST", "/search"): _search([_page("keep", "유지", "2026-07-24T00:00:00.000Z")]),
        ("GET", "/blocks/keep/children"): _children()})
    summary = C.refresh(sess, full=True)
    pages = I.load()["pages"]
    assert "keep" in pages and "gone" not in pages
    assert summary["pruned"] == 1


def test_incremental_does_not_prune():
    """증분은 삭제·공유해제를 못 본다(검색에 안 나옴) — prune 은 --full 만."""
    idx = I.load()
    idx["last_refreshed"] = "2026-07-22T00:00:00.000Z"
    I.upsert(idx, "gone", title="사라짐", headings=[], url="u", last_edited_time="t")
    I.save(idx)
    sess = FakeSession({("POST", "/search"): _search([])})
    summary = C.refresh(sess, full=False)
    assert "gone" in I.load()["pages"]                # 증분은 안 지움
    assert summary["pruned"] == 0


def test_search_pagination_follows_cursor():
    first = _search([_page("p1", "A", "2026-07-24T02:00:00.000Z")], has_more=True, cursor="c1")
    second = _search([_page("p2", "B", "2026-07-24T01:00:00.000Z")])
    sess = FakeSession({("POST", "/search"): [first, second],
                        ("GET", "/blocks/p1/children"): _children(),
                        ("GET", "/blocks/p2/children"): _children()})
    C.refresh(sess, full=True)
    assert set(I.load()["pages"]) == {"p1", "p2"}
    # calls 는 search·children 이 섞이므로(첫 검색 뒤 곧장 children GET) POST /search 만 추린다.
    searches = [c for c in sess.calls if c[0] == "POST" and c[1] == "/search"]
    assert searches[0][2].get("start_cursor") is None    # 첫 검색엔 커서 없음
    assert searches[1][2]["start_cursor"] == "c1"          # 둘째 검색이 커서를 이어받음


def test_non_page_search_results_are_skipped():
    sess = FakeSession({("POST", "/search"): _search([
        {"id": "db1", "object": "database", "last_edited_time": "t"},
        _page("pg1", "페이지", "2026-07-24T00:00:00.000Z")]),
        ("GET", "/blocks/pg1/children"): _children()})
    C.refresh(sess, full=True)
    assert set(I.load()["pages"]) == {"pg1"}       # database 객체는 건너뜀


def test_search_stops_on_stalled_pagination():
    """has_more=true 인데 결과가 없거나 커서가 정체되면 무한루프 대신 멈춘다
    (진행 불변식 가드 — 실기 재현된 128만 요청 회귀 방지)."""
    stall = _search([], has_more=True, cursor="stuck")
    sess = FakeSession({("POST", "/search"): stall}, max_calls=5)
    summary = C.refresh(sess, full=True)     # 멈추지 않으면 max_calls 로 시끄럽게 실패
    assert summary["indexed"] == 0 and summary["total"] == 0


def test_stalled_full_refresh_does_not_prune():
    """full 재열거가 정체 가드로 조기 종료되면(불완전 열거) 아직 공유 중인 페이지를
    지우면 안 된다 — prune 은 완전한 재열거(has_more=False 로 정상 종료)에서만."""
    idx = I.load()
    I.upsert(idx, "keep", title="유지", headings=[], url="u", last_edited_time="t")
    I.save(idx)
    stall = _search([], has_more=True, cursor="stuck")   # 진행 없이 정체
    sess = FakeSession({("POST", "/search"): stall}, max_calls=5)
    summary = C.refresh(sess, full=True)
    pages = I.load()["pages"]
    assert "keep" in pages
    assert summary["pruned"] == 0
