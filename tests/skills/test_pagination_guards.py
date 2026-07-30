"""calendar/memory 페이지네이션 진행 불변식 — templates `_fetch`(실기 재현 2건)와
library crawl 엔 있던 가드가 형제 모듈엔 없어, `has_more:true`+`next_cursor:null`(또는
빈 results)에서 무한 요청 루프가 됐다(opus 스윕 실측: 5초에 요청 수백만). 계약:
서버가 진행을 못 시켜주면 지금까지 모은 것을 돌려주고 멈춘다. `results: null` 도
빈 목록으로 총체 처리한다(.get(key, []) 는 명시적 null 에 무력)."""
import pytest

from notionmemory.skills.calendar.notion_db import CalendarDB
from notionmemory.skills.memory.notion_db import SecondBrainDB


class _Resp:
    def __init__(self, body):
        self._body = body
        self.status_code = 200
        self.text = ""

    def json(self):
        return self._body


class _StallSession:
    """항상 has_more=true, next_cursor=null — 예전 코드는 여기서 영원히 돈다."""
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.calls = 0

    def request(self, method, path, **kw):
        self.calls += 1
        if self.calls > 50:                      # 가드 실패 시 테스트가 유한하게 실패
            raise AssertionError("pagination guard missing — runaway request loop")
        body = self.bodies[min(self.calls - 1, len(self.bodies) - 1)]
        return _Resp(body)


_PAGE = {"id": "pg1", "properties": {}}


@pytest.mark.parametrize("db_cls", [CalendarDB, SecondBrainDB])
def test_query_stops_on_null_cursor_stall(db_cls):
    sess = _StallSession([{"results": [_PAGE], "has_more": True, "next_cursor": None}])
    pages = db_cls(sess).query("ds1", {"property": "X", "rich_text": {"equals": "y"}})
    assert pages == [_PAGE]
    assert sess.calls <= 2


@pytest.mark.parametrize("db_cls", [CalendarDB, SecondBrainDB])
def test_query_stops_on_empty_results_stall(db_cls):
    sess = _StallSession([{"results": [], "has_more": True, "next_cursor": "c-static"}])
    pages = db_cls(sess).query("ds1", {"property": "X", "rich_text": {"equals": "y"}})
    assert pages == []
    assert sess.calls <= 2


@pytest.mark.parametrize("db_cls", [CalendarDB, SecondBrainDB])
def test_query_results_null_is_empty_not_typeerror(db_cls):
    sess = _StallSession([{"results": None, "has_more": False}])
    assert db_cls(sess).query("ds1", {}) == []


def test_page_content_stops_on_stall_and_null_results():
    sess = _StallSession([
        {"results": [{"type": "paragraph", "paragraph": {"rich_text": [
            {"plain_text": "줄"}]}}], "has_more": True, "next_cursor": None}])
    assert SecondBrainDB(sess).page_content("pg1") == "줄"
    assert sess.calls <= 2
    sess2 = _StallSession([{"results": None, "has_more": False}])
    assert SecondBrainDB(sess2).page_content("pg1") == ""


def test_replace_content_enumeration_stops_on_stall():
    # 열거(GET children) 단계가 정체돼도 멈추고 진행한다 — DELETE/append 는 이어짐.
    sess = _StallSession([{"results": [], "has_more": True, "next_cursor": None}])
    SecondBrainDB(sess).replace_content("pg1", "새 본문")
    assert sess.calls <= 10          # 열거 1회 + append 호출들(50 미만이면 가드 작동)


def test_find_page_results_null_is_none_not_typeerror():
    sess = _StallSession([{"results": None}])
    assert CalendarDB(sess).find_page_by_event_id("ds1", "ev1") is None
    sess2 = _StallSession([{"results": None}])
    assert SecondBrainDB(sess2).find_page_by_mem_id("ds1", "m1") is None
