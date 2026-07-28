"""등록 파이프라인 — 신뢰 경계가 코드가 되는 곳.

핵심 불변식: 에이전트가 죽어도 프로필은 저장되고 CRUD 는 전부 동작한다(스펙 §1).
"""
import hashlib

import pytest

from notionmemory.skills.templates import introspect as I
from notionmemory.skills.templates import profile as P
from tests.skills.test_templates_store import FakeResp, FakeSession


@pytest.fixture(autouse=True)
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


# 32자리 hex — C1 이후 `register()` 가 `resolve_target()` 을 거치므로, 대상 문자열은
# `extract_page_id()` 가 실제로 id 로 인식하는 형태여야 한다(그래야 fast-path 로
# 빠져 `/search` 없이 그대로 쓰인다). "pgroot"/"pgnew" 같은 임의 문자열은 이제
# 이름으로 취급돼 `/search` 를 태우므로, 그 라우트가 없으면 0건 → `AmbiguousTarget`
# 이 나 테스트가 의도한 분기(404 등)를 더는 밟지 못한다.
PGROOT = "2a1b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
PGNEW = "1111222233334444555566667777888a"


def _title(text):
    return [{"type": "text", "plain_text": text}]


def _db_resp(db_id, ds_id, title):
    """`GET /databases/{id}` — 제목과 data source 목록만. 속성은 안 담는다(C3)."""
    return FakeResp(200, {"id": db_id, "title": _title(title),
                          "data_sources": [{"id": ds_id}]})


def _ds_resp(props):
    """`GET /data_sources/{id}` — 속성은 여기서만 온다(C3)."""
    return FakeResp(200, {"properties": props})


APP_PROPS = {
    "Position": {"type": "title", "title": {}},
    "Stage": {"type": "select",
              "select": {"options": [{"name": "Applied"}, {"name": "Offer"}]}},
    "Applied On": {"type": "date", "date": {}},
    "Days Open": {"type": "formula", "formula": {"expression": "x"}},
    "Approve": {"type": "button", "button": {}},
}


def _routes():
    return {
        ("GET", f"/pages/{PGROOT}"): FakeResp(200, {
            "id": PGROOT, "url": "https://n/pgroot",
            "properties": {"title": {"type": "title", "title": _title("Job Tracker")}}}),
        ("GET", f"/blocks/{PGROOT}/children"): FakeResp(200, {"results": [
            {"id": "b1", "type": "child_database", "has_children": False,
             "child_database": {"title": "Applications"}},
            {"id": "col", "type": "column_list", "has_children": True}]}),
        ("GET", "/blocks/col/children"): FakeResp(200, {"results": [
            {"id": "b2", "type": "child_database", "has_children": False,
             "child_database": {"title": "Companies"}}]}),
        ("GET", "/databases/b1"): _db_resp("b1", "ds_a", "Applications"),
        ("GET", "/data_sources/ds_a"): _ds_resp(APP_PROPS),
        ("GET", "/databases/b2"): _db_resp("b2", "ds_c", "Companies"),
        ("GET", "/data_sources/ds_c"): _ds_resp({"Name": {"type": "title", "title": {}}}),
        ("POST", "/data_sources/ds_a/query"): FakeResp(200, {"results": [], "has_more": False}),
        ("POST", "/data_sources/ds_c/query"): FakeResp(200, {"results": [], "has_more": False}),
    }


class FakeRuntime:
    def __init__(self, text="요약: 지원 추적\n\n## 노트\n본문"):
        self.text = text
        self.calls = 0

    def generate(self, system, user, image_paths=None):
        self.calls += 1
        if isinstance(self.text, Exception):
            raise self.text
        return self.text


# --- 대상 해석 ---

def test_slugify_makes_a_stable_identifier():
    assert I.slugify("Job Application Tracker") == "job-application-tracker"
    assert I.slugify("읽은 책 기록 📚") == "읽은-책-기록"
    assert I.slugify("  --Weird__Name--  ") == "weird-name"
    assert I.slugify("") == "template"


def test_slugify_keeps_non_ascii_non_korean_scripts():
    """I8 — `\\w` 대신 `[0-9a-z가-힣]` 로 좁혔던 회귀. 악센트 라틴·일본어·키릴이
    통째로 `template` 로 뭉개지면 안 된다."""
    assert I.slugify("Café Notes") == "café-notes"
    assert I.slugify("日本語ノート") == "日本語ノート"
    assert I.slugify("Проекты") == "проекты"


def test_extract_page_id_from_url_and_bare_id():
    url = "https://www.notion.so/me/Job-Tracker-2a1b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
    assert I.extract_page_id(url) == "2a1b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
    assert I.extract_page_id("2a1b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d") == \
        "2a1b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
    assert I.extract_page_id("Job Tracker") == ""


def test_extract_page_id_ignores_the_view_id_in_the_query_string():
    """I4 — Notion 의 "Copy link" 는 DB 뷰가 있는 페이지에 `?v=<view-id>` 를 붙인다.
    쿼리까지 스캔하면 마지막 매치인 뷰 id 를 페이지 id 로 착각한다."""
    url = (f"https://www.notion.so/me/Job-Tracker-{PGROOT}"
           f"?v={PGNEW}&pvs=4")
    assert I.extract_page_id(url) == PGROOT


def test_extract_page_id_ignores_a_fragment_only_block_id():
    """마이너 리뷰 지적 5 — `?` 없이 `#<blockid>` 만 붙은 링크("Copy link to
    block")도 있다. `?` 로만 자르면 프래그먼트의 블록 id 까지 스캔해 마지막
    매치인 블록 id 를 페이지 id 로 착각한다."""
    url = f"https://www.notion.so/me/Job-Tracker-{PGROOT}#{PGNEW}"
    assert I.extract_page_id(url) == PGROOT


def test_extract_page_id_when_the_title_ends_in_a_year():
    """CRITICAL, 확인 리뷰 실기 재현 — 제목이 연도로 끝나면(전부 hex 숫자) 대시
    제거 후 그 숫자들이 id 앞에 들러붙는다. earliest-window 매칭은 32자 윈도우가
    오른쪽으로 밀려 진짜 id 의 마지막 글자를 잘라먹었다(`20242a1b...3a4b`, 마지막
    `5c6d` 소실). 앵커 매칭은 제목이 무엇으로 끝나든 흔들리지 않아야 한다."""
    url = f"https://www.notion.so/Roadmap-2024-{PGROOT}"
    assert I.extract_page_id(url) == PGROOT


def test_extract_page_id_when_the_title_ends_in_a_hex_word():
    """`Q4-Plan-2025-<id>` 처럼 제목 마지막 조각이 숫자여도 같은 클래스의 실패다."""
    url = f"https://www.notion.so/Q4-Plan-2025-{PGROOT}"
    assert I.extract_page_id(url) == PGROOT


def test_extract_page_id_when_the_title_ends_in_a_hex_letter():
    """`My-Data-<id>` — 제목이 `a`-`f` 하나로 끝나기만 해도(단어 전체가 hex 일
    필요 없다) 대시 제거 후 그 글자가 id 의 첫 글자인 것처럼 뭉친다."""
    url = f"https://www.notion.so/My-Data-{PGROOT}"
    assert I.extract_page_id(url) == PGROOT


def test_extract_page_id_when_the_title_ends_in_a_single_hex_letter():
    """`Beta-<id>` — 리뷰가 지목한 가장 짧은 재현. 이전 두 테스트(`Job Tracker`)는
    제목이 `r`(hex 아님)로 끝나 이 회귀에 눈이 멀어 있었다."""
    url = f"https://www.notion.so/Beta-{PGROOT}"
    assert I.extract_page_id(url) == PGROOT


def test_resolve_target_by_name_with_one_hit():
    sess = FakeSession({("POST", "/search"): FakeResp(200, {"results": [
        {"id": PGROOT, "object": "page",
         "properties": {"title": {"type": "title", "title": _title("Job Tracker")}}}]})})
    assert I.resolve_target(sess, "Job Tracker") == PGROOT


def test_resolve_target_zero_hits_mentions_sharing():
    sess = FakeSession({("POST", "/search"): FakeResp(200, {"results": []})})
    with pytest.raises(I.AmbiguousTarget) as e:
        I.resolve_target(sess, "Nope")
    assert "공유" in str(e.value)
    assert e.value.candidates == []


def test_resolve_target_many_hits_returns_candidates():
    sess = FakeSession({("POST", "/search"): FakeResp(200, {"results": [
        {"id": "a", "object": "page", "url": "https://n/a",
         "properties": {"title": {"type": "title", "title": _title("Tracker A")}}},
        {"id": "b", "object": "page", "url": "https://n/b",
         "properties": {"title": {"type": "title", "title": _title("Tracker B")}}}]})})
    with pytest.raises(I.AmbiguousTarget) as e:
        I.resolve_target(sess, "Tracker")
    assert [c["id"] for c in e.value.candidates] == ["a", "b"]


# --- 스키마 추출: 프론트매터는 API 원문이다 ---

def test_fetch_database_copies_types_and_choices_verbatim():
    db = I.fetch_database(FakeSession(_routes()), "b1")
    by_name = {p["name"]: p for p in db["properties"]}
    assert by_name["Stage"]["type"] == "select"
    assert by_name["Stage"]["choices"] == ["Applied", "Offer"]
    assert db["title_property"] == "Position"
    assert db["data_source_id"] == "ds_a"
    assert db["key"] == "applications"


def test_fetch_database_marks_writable_and_filterable_from_the_type_table():
    by_name = {p["name"]: p for p in I.fetch_database(FakeSession(_routes()), "b1")["properties"]}
    assert by_name["Days Open"] == {"name": "Days Open", "type": "formula",
                                    "writable": False, "filterable": True}
    assert by_name["Approve"]["filterable"] is False
    assert by_name["Applied On"]["writable"] is True


def test_fetch_database_reads_properties_from_the_data_source_not_the_database():
    """C3 — `GET /databases/{id}` 에는 `properties` 가 없다. 한 홉만 읽으면
    `sess.calls` 에 `/data_sources/ds_a` 요청이 없을 것이다."""
    sess = FakeSession(_routes())
    I.fetch_database(sess, "b1")
    assert ("GET", "/databases/b1", None) in sess.calls
    assert ("GET", "/data_sources/ds_a", None) in sess.calls


def test_fetch_database_skips_linked_views_quietly():
    """linked database view 는 child_database 처럼 보이지만 실제 DB 가 아니다."""
    sess = FakeSession({("GET", "/databases/ghost"): FakeResp(404, {})})
    assert I.fetch_database(sess, "ghost") is None


def test_fetch_database_uses_the_first_data_source_and_logs_when_there_are_more():
    """C3 — 프로필 형식은 DB 당 data_source 하나만 담는다. 여러 개면 조용히
    첫 번째만 쓰지 않고 로그를 남긴다."""
    routes = {
        ("GET", "/databases/multi"): FakeResp(200, {
            "id": "multi", "title": _title("Multi"),
            "data_sources": [{"id": "ds1"}, {"id": "ds2"}]}),
        ("GET", "/data_sources/ds1"): FakeResp(200, {
            "properties": {"Name": {"type": "title", "title": {}}}}),
    }
    logs = []
    db = I.fetch_database(FakeSession(routes), "multi", log=logs.append)
    assert db["data_source_id"] == "ds1"
    assert len(logs) == 1


def test_fetch_database_refuses_to_return_a_schema_less_database():
    """C3 — 빈 속성 dict 는 `_build` 가 `None` 이 아니라서 못 걸러낸다. 여기서
    아예 등록 후보에서 빠져야 한다(경고 로그 + None)."""
    routes = {
        ("GET", "/databases/empty"): FakeResp(200, {
            "id": "empty", "title": _title("Empty"),
            "data_sources": [{"id": "ds_empty"}]}),
        ("GET", "/data_sources/ds_empty"): FakeResp(200, {"properties": {}}),
    }
    logs = []
    assert I.fetch_database(FakeSession(routes), "empty", log=logs.append) is None
    assert logs


def test_fetch_database_raises_instead_of_guessing_on_a_non_404_failure():
    """I5 — 429/5xx 를 404 처럼 "linked view 일 수 있음"으로 삼키면 등록 시점에만
    잡을 수 있는 실패가 조용히 불완전한 프로필로 굳는다. 원인이 확인 안 됐으면
    추측하지 말고 그대로 던진다."""
    sess = FakeSession({("GET", "/databases/rate"): FakeResp(429, {})})
    with pytest.raises(RuntimeError) as e:
        I.fetch_database(sess, "rate")
    assert "429" in str(e.value)


def test_fetch_database_skips_when_the_body_code_is_object_not_found_even_off_404():
    """마이너 리뷰 지적 6 — 이 리포 선례(`notion_exporter.py`의 `_notion_error`)는
    상태 코드뿐 아니라 body 의 `object_not_found` 코드도 같은 조건으로 인정한다.
    상태만 보면, Notion 이 같은 상황을 다른 status(예: 400)로 답할 때 linked
    view 하나가 낀 템플릿 전체가 등록 불가능해진다."""
    sess = FakeSession({("GET", "/databases/ghost"):
                         FakeResp(400, {"code": "object_not_found"})})
    assert I.fetch_database(sess, "ghost") is None


def test_fetch_database_reads_relation_target_from_data_source_id_fallback():
    """마이너 리뷰 지적 4 — C3 이후 관계 설정도 data source 응답에서 온다. 이
    환경에서는 실 워크스페이스로 확인하지 못했지만, Notion 이 `database_id`
    대신 `data_source_id` 만 주는 모양이면 기존 코드는 빈 문자열을 읽어 모든
    관계를 "템플릿 밖"으로 조용히 강등시킨다 — 방어적으로 두 필드 다 인정한다."""
    routes = {
        ("GET", "/databases/b1"): _db_resp("b1", "ds_a", "Applications"),
        ("GET", "/data_sources/ds_a"): _ds_resp({
            "Position": {"type": "title", "title": {}},
            "Company": {"type": "relation", "relation": {"data_source_id": "ds_c"}}}),
    }
    db = I.fetch_database(FakeSession(routes), "b1")
    prop = next(p for p in db["properties"] if p["name"] == "Company")
    assert prop["_relation_db"] == "ds_c"


# --- 등록 ---

def test_register_builds_a_complete_profile():
    sess = FakeSession(_routes())
    p = I.register(sess, PGROOT, runtime=FakeRuntime(), log=lambda *_: None)
    assert p.slug == "job-tracker" and p.page_id == PGROOT
    assert [db["key"] for db in p.databases] == ["applications", "companies"]
    assert p.capabilities == ["date", "text"]
    assert p.health == "ok" and p.schema_fetched_at
    assert P.exists("job-tracker")


def test_register_resolves_a_name_target_through_search():
    """C1 — 이름으로 등록하면 `resolve_target()` 을 거쳐 `POST /search` 가 실제로
    나가야 한다. 이전엔 `extract_page_id(target) or target` 라 이름이 그대로
    `GET /pages/Job Tracker` 로 나가 400 이 됐다(실기 재현)."""
    routes = _routes()
    routes[("POST", "/search")] = FakeResp(200, {"results": [
        {"id": PGROOT, "object": "page",
         "properties": {"title": {"type": "title", "title": _title("Job Tracker")}}}]})
    sess = FakeSession(routes)
    p = I.register(sess, "Job Tracker", runtime=None, log=lambda *_: None)
    assert ("POST", "/search", {
        "query": "Job Tracker", "filter": {"property": "object", "value": "page"},
        "page_size": 10}) in sess.calls
    assert p.page_id == PGROOT


def test_register_propagates_ambiguous_name_search_for_the_cli_to_catch():
    """C1 — 후보가 여럿/0건이면 `AmbiguousTarget` 이 `register()` 밖으로 그대로
    던져진다. 되묻기(exit 2)는 CLI 책임이지 이 함수 책임이 아니다."""
    routes = {("POST", "/search"): FakeResp(200, {"results": []})}
    with pytest.raises(I.AmbiguousTarget):
        I.register(FakeSession(routes), "Nope", log=lambda *_: None)


def test_register_resolves_relation_targets_within_the_profile():
    routes = _routes()
    routes[("GET", "/databases/b1")] = _db_resp("b1", "ds_a", "Applications")
    routes[("GET", "/data_sources/ds_a")] = _ds_resp({
        "Position": {"type": "title", "title": {}},
        "Company": {"type": "relation", "relation": {"database_id": "b2"}},
        "Vendor": {"type": "relation", "relation": {"database_id": "outside"}}})
    p = I.register(FakeSession(routes), PGROOT, runtime=FakeRuntime(), log=lambda *_: None)
    by_name = {prop["name"]: prop for prop in p.databases[0]["properties"]}
    assert by_name["Company"]["relates_to"] == "companies"
    assert by_name["Vendor"]["relates_to"] is None
    assert by_name["Vendor"]["writable"] is False       # 템플릿 밖 → 쓰기 불가로 강등


def test_register_deduplicates_colliding_database_keys():
    """I7 — 두 DB 제목이 같은 슬러그로 뭉치면(여기선 둘 다 "Applications") 그룹
    구성원 전원이 접미사를 받아야 한다(확인 리뷰 3번째 재발 — 첫 번째도 예외
    없이). 안 그러면 `profile.find_db` 가 첫 번째만 돌려주고 `samples` dict 가
    한쪽 행을 조용히 지운다. 접미사는 `database_id` 해시라(재리뷰 Important 1)
    정확한 문자열이 아니라 유일성/안정성만 검증한다."""
    routes = _routes()
    routes[("GET", "/databases/b2")] = _db_resp("b2", "ds_c", "Applications")
    p = I.register(FakeSession(routes), PGROOT, runtime=None, log=lambda *_: None)
    keys = [db["key"] for db in p.databases]
    # 둘 다 접미사를 받는다 — 어느 쪽도 맨살 "applications" 를 갖지 않는다.
    assert keys[0] != "applications" and keys[0].startswith("applications-")
    assert keys[1] != "applications" and keys[1].startswith("applications-")
    assert len(keys) == len(set(keys))


def test_register_dedupes_keys_stably_when_the_positional_suffix_would_collide():
    """재리뷰 Important 1, 실기 재현 — `Notes`, `Notes 2`, `Notes` 세 개면 위치
    기반 접미사는 세 번째에 `notes-2` 를 주는데 그건 두 번째("Notes 2")가 이미
    쓰고 있다. 그 상태에서 세 번째 DB 를 가리키는 relation 은 `profile.find_db`
    를 통해 두 번째로 조용히 라우팅된다 — "관계 쓰기가 엉뚱한 DB 를 겨냥한다"는
    바로 그 사고다.

    (확인 리뷰 3번째 재발) `Notes` 그룹(n1/n3)의 첫 번째도 이제 접미사를 받는다
    — "첫 등장은 맨살"이라는 이전 규칙 자체가 위치 의존이었다(어느 DB 가
    "첫 번째"인지는 등록 순서에 달려 있다)."""
    routes = {
        ("GET", f"/pages/{PGROOT}"): FakeResp(200, {
            "id": PGROOT, "url": "https://n/pgroot",
            "properties": {"title": {"type": "title", "title": _title("Notes Hub")}}}),
        ("GET", f"/blocks/{PGROOT}/children"): FakeResp(200, {"results": [
            {"id": "n1", "type": "child_database", "has_children": False,
             "child_database": {}},
            {"id": "n2", "type": "child_database", "has_children": False,
             "child_database": {}},
            {"id": "n3", "type": "child_database", "has_children": False,
             "child_database": {}}]}),
        ("GET", "/databases/n1"): _db_resp("n1", "ds_n1", "Notes"),
        ("GET", "/data_sources/ds_n1"): _ds_resp({"Name": {"type": "title", "title": {}}}),
        ("GET", "/databases/n2"): _db_resp("n2", "ds_n2", "Notes 2"),
        ("GET", "/data_sources/ds_n2"): _ds_resp({
            "Name": {"type": "title", "title": {}},
            "Link": {"type": "relation", "relation": {"database_id": "n3"}}}),
        ("GET", "/databases/n3"): _db_resp("n3", "ds_n3", "Notes"),
        ("GET", "/data_sources/ds_n3"): _ds_resp({"Name": {"type": "title", "title": {}}}),
    }
    p = I.register(FakeSession(routes), PGROOT, runtime=None, log=lambda *_: None)
    keys = [db["key"] for db in p.databases]
    assert len(keys) == len(set(keys))          # 유일해야 한다
    # "Notes" 그룹(n1, n3) 은 첫 번째도 접미사를 받는다 — 맨살 "notes" 는 아무도
    # 갖지 않는다(확인 리뷰 3번째 재발: 이전엔 keys[0] == "notes" 였고, 그건
    # "어느 DB 가 첫 번째로 왔는가"라는 위치에 의존하는 보장이었다).
    assert keys[0] != "notes" and keys[0].startswith("notes-")
    assert keys[2] != "notes" and keys[2].startswith("notes-")
    assert keys[2] != keys[1]                    # 세 번째가 두 번째의 키를 뺏으면 안 된다
    assert keys[2] != keys[0]
    link_prop = next(prop for prop in p.databases[1]["properties"]
                     if prop["name"] == "Link")
    # relation 은 실제로 세 번째 DB(n3)를 가리켜야 한다 — 두 번째가 아니라.
    assert link_prop["relates_to"] == keys[2]
    assert P.find_db(p, keys[2])["database_id"] == "n3"


def _db(key, database_id):
    return {"key": key, "database_id": database_id, "title": key,
            "data_source_id": "", "title_property": "", "missing": False,
            "properties": []}


def test_dedupe_keys_suffixes_a_bare_first_occurrence_that_collides_with_a_later_slug():
    """Important, 확인 리뷰 3번째 재발, 실기 재현 — "첫 등장은 검사 없이 맨살 키를
    가져간다"는 예전 규칙의 구멍. 세 번째 DB 의 *자연* 슬러그("Notes 402434")가
    두 번째 "Notes" 의 해시 접미사와 우연히 같다(`database_id="n2"` 의 sha1 앞
    6자리가 정확히 "402434" — 리뷰 원문의 숫자 그대로). 세 번째는 자기 그룹에서
    "첫 등장"(그 슬러그로는 유일)이라 예전 코드는 `used` 확인 없이 그걸 그대로
    가져가 두 번째의 접미사 키와 충돌했다: `['notes', 'notes-402434',
    'notes-402434']`. 지금은 모든 후보(맨살이든 접미사든)가 같은 `used` 검사를
    거친다."""
    assert hashlib.sha1(b"n2").hexdigest()[:6] == "402434"
    databases = [_db("notes", "n1"), _db("notes", "n2"), _db("notes-402434", "n3")]
    I._dedupe_keys(databases)
    keys = [db["key"] for db in databases]
    assert len(keys) == len(set(keys)), keys


def test_dedupe_keys_is_independent_of_registration_order():
    """확인 리뷰 3번째 재발 — 이전 문서(둘 다)는 "순서 무관"을 주장했지만 실제로는
    거짓이었다: 맨살 키를 "몇 번째 등장인가"로 매겼으므로 DB 하나가 빠지거나
    순서가 바뀌면 어느 DB 가 맨살 키를 갖는지 바뀌었다. 지금은 그룹에 속한 DB
    는 전원 자기 `database_id` 해시로만 접미사를 받으므로, 같은 DB 집합을 다른
    순서로 넣어도 `database_id` → `key` 매핑이 그대로여야 한다."""
    forward = [_db("notes", "n1"), _db("notes", "n2"), _db("notes", "n3")]
    backward = [_db("notes", "n3"), _db("notes", "n2"), _db("notes", "n1")]
    I._dedupe_keys(forward)
    I._dedupe_keys(backward)
    by_id_forward = {db["database_id"]: db["key"] for db in forward}
    by_id_backward = {db["database_id"]: db["key"] for db in backward}
    assert by_id_forward == by_id_backward
    # 그리고 아무도 맨살 "notes" 를 갖지 않는다 — 그룹 전원이 접미사를 받는다.
    assert "notes" not in by_id_forward.values()


def test_dedupe_keys_terminates_when_the_digest_saturates():
    """Minor, 확인 리뷰 3번째 재발, 실기 재현 — `database_id` 가 비어 있으면
    (응답이 `id` 를 빠뜨린 폴백) 같은 슬러그를 가진 여러 DB 가 전부 같은
    digest(`sha1("")`)를 공유한다. 접미사 길이를 계속 늘려도 `digest[:length]`
    는 `length > len(digest)`(40)부터 digest 전체로 고정돼 후보가 더는 안
    바뀐다 — 예전 `while candidate in used` 는 여기서 영원히 돈다(실기 재현:
    동일 `database_id` 20개 공유). 이 테스트가 그 자체로 회귀 가드다: 고쳐지지
    않았으면 이 테스트가 멈추지 않는다."""
    databases = [_db("same", "") for _ in range(20)]
    I._dedupe_keys(databases)
    keys = [db["key"] for db in databases]
    assert len(keys) == len(set(keys)), keys


def test_register_resolves_relation_targets_via_data_source_id_shape():
    """마이너 리뷰 지적 4 — `by_db_id` 맵도 `data_source_id` 로 찾을 수 있어야
    관계 config 가 그 필드만 줄 때 해석이 된다."""
    routes = _routes()
    routes[("GET", "/data_sources/ds_a")] = _ds_resp({
        "Position": {"type": "title", "title": {}},
        "Company": {"type": "relation", "relation": {"data_source_id": "ds_c"}}})
    p = I.register(FakeSession(routes), PGROOT, runtime=None, log=lambda *_: None)
    by_name = {prop["name"]: prop for prop in p.databases[0]["properties"]}
    assert by_name["Company"]["relates_to"] == "companies"
    assert by_name["Company"]["writable"] is True


def test_register_survives_a_dead_agent_runtime():
    """이 스킬의 핵심 불변식 — 에이전트는 편의지 필수 조건이 아니다."""
    boom = FakeRuntime(RuntimeError("agent 없음"))
    p = I.register(FakeSession(_routes()), PGROOT, runtime=boom, log=lambda *_: None)
    assert P.exists("job-tracker")
    assert p.summary == "" and p.body == ""
    assert [db["key"] for db in p.databases] == ["applications", "companies"]


def test_register_works_with_no_runtime_at_all():
    p = I.register(FakeSession(_routes()), PGROOT, runtime=None, log=lambda *_: None)
    assert P.exists("job-tracker") and p.body == ""


def test_register_survives_a_non_string_agent_reply():
    """마이너 리뷰 지적 — `runtime` 은 덕타이핑이라 str 이 아닌 걸 돌려줄 수 있다.
    파싱이 try 밖에 있으면 `AttributeError` 가 `register()` 까지 새어나가
    `profile.save()` 자체가 실행되지 않는다 — 핵심 불변식 위반."""
    p = I.register(FakeSession(_routes()), PGROOT, runtime=FakeRuntime(None),
                   log=lambda *_: None)
    assert P.exists("job-tracker")
    assert p.summary == "" and p.body == ""


def test_register_treats_a_dict_agent_reply_as_no_reply_not_prose():
    """마이너 리뷰 지적 8 — `runtime` 이 str 이 아닌 걸 돌려주면(덕타이핑이라
    가능하다) `str(raw)` 로 감싸는 예전 코드는 `"{'a': 1}"` 같은 프로즈를 그대로
    저장한다. "응답 없음"과 동일하게 다뤄야 한다."""
    p = I.register(FakeSession(_routes()), PGROOT, runtime=FakeRuntime({"a": 1}),
                   log=lambda *_: None)
    assert p.summary == "" and p.body == ""


def test_register_treats_a_whitespace_only_agent_reply_as_no_notes():
    """마이너 리뷰 지적 — `body == "\\n"` 은 "본문 없음"과 구별이 안 된다."""
    rt = FakeRuntime("요약: 지원 추적\n\n   \n  ")
    p = I.register(FakeSession(_routes()), PGROOT, runtime=rt, log=lambda *_: None)
    assert p.body == ""


def test_register_uses_agent_output_for_summary_and_body_only():
    rt = FakeRuntime("요약: 지원한 회사를 추적\n\n## 흔한 요청\n- 지원했어 → 행 추가")
    p = I.register(FakeSession(_routes()), PGROOT, runtime=rt, log=lambda *_: None)
    assert p.summary == "지원한 회사를 추적"
    assert "흔한 요청" in p.body
    assert rt.calls == 1           # 등록당 1회만 — 요청 때마다 재해석하지 않는다


def test_register_page_404_gives_the_sharing_hint():
    sess = FakeSession({("GET", f"/pages/{PGROOT}"): FakeResp(404, {})})
    with pytest.raises(RuntimeError) as e:
        I.register(sess, PGROOT, log=lambda *_: None)
    assert "공유" in str(e.value)


def test_register_with_no_databases_at_all_says_none_were_found():
    """Nit, 확인 리뷰 — 이 테스트는 예전에
    `test_register_with_no_databases_explains_linked_views` 로 불렸는데, 페이지
    아래 블록이 아예 없는(하위 DB 후보 자체가 없는) 경우라 실제로 나가는 문구는
    "하위에서 데이터베이스를 찾지 못했습니다"이지 linked view 설명이 아니다 —
    이름이 코드가 하지 않는 행동을 주장하고 있었다."""
    routes = _routes()
    routes[("GET", f"/blocks/{PGROOT}/children")] = FakeResp(200, {"results": []})
    with pytest.raises(RuntimeError) as e:
        I.register(FakeSession(routes), PGROOT, log=lambda *_: None)
    assert "데이터베이스" in str(e.value)


def test_build_warns_when_the_node_budget_caps_the_block_walk(monkeypatch):
    """Minor, 확인 리뷰 — `store.py::_fetch` 가 cap/stall 을 조용히 삼키지 않는 것과
    같은 규율. 노드 예산에 걸리면 트리 일부를 못 본 채 프로필이 `health: ok` 로
    저장된다 — 최소한 경고는 남겨야 한다."""
    monkeypatch.setattr(I, "MAX_NODES", 2)
    routes = {
        ("GET", f"/pages/{PGROOT}"): FakeResp(200, {
            "id": PGROOT, "url": "https://n/pgroot",
            "properties": {"title": {"type": "title", "title": _title("Big")}}}),
        ("GET", f"/blocks/{PGROOT}/children"): FakeResp(200, {"results": [
            {"id": "d1", "type": "child_database", "has_children": False,
             "child_database": {}},
            {"id": "d2", "type": "child_database", "has_children": False,
             "child_database": {}},
            {"id": "d3", "type": "child_database", "has_children": False,
             "child_database": {}}], "has_more": False}),
    }
    logs = []
    with pytest.raises(RuntimeError):
        # 예산 2 로는 실제 DB 를 하나도 못 얻어 결국 "데이터베이스 없음"으로
        # 던진다 — 그래도 경고 로그는 그 전에 이미 남아 있어야 한다.
        I._build(FakeSession(routes), PGROOT, logs.append)
    assert any("예산" in m for m in logs)


def test_register_with_no_databases_names_the_real_skip_reason_not_linked_views():
    """마이너 리뷰 지적 7 — 발견된 DB 가 전부 빈 스키마라 걸러졌는데도 최종
    메시지가 "linked view" 를 원인으로 지목하면 안 된다(오귀속). 이전 리뷰에서도
    같은 패턴이 한 번 지적됐다.

    walk_structure 로 일반화된 뒤로는(Task 2) DB 없는 페이지도 등록될 수 있어
    "데이터베이스가 전부 걸러졌다" 는 더는 그 자체로 거부 사유가 아니다 — 여기선
    헤딩·하위 페이지도 전혀 없어 결국 "빈 페이지" 로 거부되는데, 그 문구도
    여전히 "linked" 를 원인으로 지목하지 않는다는 불변식만 지키면 된다. 개별
    스킵 사유("스키마가 비어 있어 건너뜁니다")는 `log()` 로는 여전히 남는다 —
    최종 예외 메시지에 접히지 않을 뿐이다."""
    routes = _routes()
    routes[("GET", "/data_sources/ds_a")] = _ds_resp({})
    routes[("GET", "/data_sources/ds_c")] = _ds_resp({})
    logs = []
    with pytest.raises(RuntimeError) as e:
        I.register(FakeSession(routes), PGROOT, log=logs.append)
    assert "linked" not in str(e.value).lower()
    assert any("스키마" in m for m in logs)


def test_register_surfaces_a_non_404_database_failure_instead_of_guessing():
    """I5 — 429/5xx 는 "linked view" 로 오진되면 안 된다. 등록은 스키마를 확정
    하는 유일한 순간이라 일시 장애를 조용히 삼키면 불완전한 프로필이 영구 저장된다."""
    routes = _routes()
    routes[("GET", "/databases/b1")] = FakeResp(503, {})
    with pytest.raises(RuntimeError) as e:
        I.register(FakeSession(routes), PGROOT, log=lambda *_: None)
    assert "503" in str(e.value)


def test_register_refuses_to_clobber_an_auto_derived_slug():
    sess = FakeSession(_routes())
    I.register(sess, PGROOT, runtime=None, log=lambda *_: None)
    with pytest.raises(ValueError) as e:
        I.register(FakeSession(_routes()), PGROOT, runtime=None, log=lambda *_: None)
    assert "--slug" in str(e.value)


def test_explicit_slug_overwrites_for_re_registration():
    """템플릿을 다시 복제하면 page_id 가 바뀐다 — 익힌 이름은 유지돼야 한다(스펙 §8)."""
    I.register(FakeSession(_routes()), PGROOT, runtime=None, log=lambda *_: None)
    routes = _routes()
    routes[("GET", f"/pages/{PGNEW}")] = FakeResp(200, {
        "id": PGNEW, "url": "https://n/pgnew",
        "properties": {"title": {"type": "title", "title": _title("Job Tracker")}}})
    routes[("GET", f"/blocks/{PGNEW}/children")] = routes[("GET", f"/blocks/{PGROOT}/children")]
    p = I.register(FakeSession(routes), PGNEW, slug="job-tracker", runtime=None,
                   log=lambda *_: None)
    assert p.page_id == PGNEW
    assert P.list_slugs() == ["job-tracker"]


def test_register_with_slug_keeps_agent_notes_and_enabled_when_no_runtime_is_given():
    """I6, 실기 재현 — `runtime` 없이 `--slug` 재등록하면 (claude/codex 미설치인
    흔한 경우) 예전엔 새 `Profile()` 을 그냥 만들어서 학습된 summary/body 를
    지우고 `enabled` 까지 True 로 되돌렸다. `refresh()` 는 이미 이 상황을
    올바르게 다룬다 — `register()` 도 같은 규율을 따라야 한다."""
    I.register(FakeSession(_routes()), PGROOT, runtime=FakeRuntime(), log=lambda *_: None)
    before = P.load("job-tracker")
    before.enabled = False
    P.save(before)

    routes = _routes()
    routes[("GET", f"/pages/{PGNEW}")] = FakeResp(200, {
        "id": PGNEW, "url": "https://n/pgnew",
        "properties": {"title": {"type": "title", "title": _title("Job Tracker")}}})
    routes[("GET", f"/blocks/{PGNEW}/children")] = routes[("GET", f"/blocks/{PGROOT}/children")]
    p = I.register(FakeSession(routes), PGNEW, slug="job-tracker", runtime=None,
                   log=lambda *_: None)
    assert p.page_id == PGNEW
    assert p.summary == before.summary and p.body == before.body
    assert p.enabled is False


def test_register_with_slug_keeps_agent_notes_when_the_runtime_is_installed_but_broken():
    """재리뷰 Important 2, 실기 재현 — 이전 패치는 `runtime is None` 분기에만
    보존 로직을 넣었다. `runtime` 이 설치는 됐지만 호출할 때마다 죽는 경우
    (`--slug` 재등록)는 `runtime is not None` 분기를 무조건 타고, `_generate_body`
    가 실패 시에도 `("", "")` 를 돌려줬으므로 학습된 summary/body 가 영구
    삭제됐다 — "agent 없음"보다 흔한 실패 모드("설치는 됐지만 고장남")를 통해
    똑같은 사고가 재발한다."""
    I.register(FakeSession(_routes()), PGROOT, runtime=FakeRuntime(), log=lambda *_: None)
    before = P.load("job-tracker")
    assert before.summary == "지원 추적" and before.body == "## 노트\n본문\n"

    routes = _routes()
    routes[("GET", f"/pages/{PGNEW}")] = FakeResp(200, {
        "id": PGNEW, "url": "https://n/pgnew",
        "properties": {"title": {"type": "title", "title": _title("Job Tracker")}}})
    routes[("GET", f"/blocks/{PGNEW}/children")] = routes[("GET", f"/blocks/{PGROOT}/children")]
    broken = FakeRuntime(RuntimeError("설치는 됐지만 죽어있음"))
    p = I.register(FakeSession(routes), PGNEW, slug="job-tracker", runtime=broken,
                   log=lambda *_: None)
    assert p.page_id == PGNEW
    assert p.summary == before.summary and p.body == before.body


def test_register_with_slug_keeps_agent_notes_when_the_runtime_replies_with_a_non_string():
    """Minor, 확인 리뷰 3번째 재발 — 재리뷰 Important 2 가 고친 "실패=None, 기존
    보존" 규율이 마이너 리뷰 지적 8(비-str 응답을 프로즈로 저장하지 않기)의
    이전 구현으로 다시 뚫렸었다: 비-str 응답을 `""`(빈 성공)로 강제하면
    `("", "")` 는 "agent 가 실제로 판단해서 빈 결과를 냈다"는 신호가 되어 버려,
    `--slug` 재등록에서 학습된 프로즈가 지워졌다 — dict/None 을 돌려주는 덕타입
    런타임(마이너 리뷰 지적 8)에서 finding-2 의 삭제 사고가 finding-8 의 고침을
    통해 재입성한다. 비-str 응답은 예외 경로와 동일하게(`None`, "기존 프로필
    보존") 다뤄야 한다."""
    I.register(FakeSession(_routes()), PGROOT, runtime=FakeRuntime(), log=lambda *_: None)
    before = P.load("job-tracker")
    assert before.summary == "지원 추적" and before.body == "## 노트\n본문\n"

    routes = _routes()
    routes[("GET", f"/pages/{PGNEW}")] = FakeResp(200, {
        "id": PGNEW, "url": "https://n/pgnew",
        "properties": {"title": {"type": "title", "title": _title("Job Tracker")}}})
    routes[("GET", f"/blocks/{PGNEW}/children")] = routes[("GET", f"/blocks/{PGROOT}/children")]
    for bad_reply in (None, {"a": 1}):
        duck = FakeRuntime(bad_reply)
        p = I.register(FakeSession(routes), PGNEW, slug="job-tracker", runtime=duck,
                       log=lambda *_: None)
        assert p.page_id == PGNEW
        assert p.summary == before.summary and p.body == before.body


def test_register_preserves_prompt_of_existing_profile(monkeypatch):
    """프롬프트 전용 청사진(page_id="")을 같은 슬러그로 register 하면 인스턴스로
    전환된다 — 이때 프로필의 구조는 새로 채워지지만, 사람이 적어둔 `prompt` 는
    청사진에만 있고 Notion 에서 다시 얻을 수 없으므로 반드시 이어받아야 한다."""
    # 프롬프트 전용 청사진이 이미 있다
    P.save(P.Profile(slug="lecture", name="강의노트", page_id="", prompt="개념별 헤딩"))
    # register 의 Notion 조회 부분을 대체 — page/databases/pages 만 반환
    monkeypatch.setattr(I, "resolve_target", lambda s, t: "new_pg")
    monkeypatch.setattr(I, "_build", lambda s, pid, log: (
        {"id": "new_pg", "url": "https://n/new_pg",
         "properties": {"title": {"type": "title", "title": [{"plain_text": "강의 DB"}]}}},
        [{"key": "notes", "title": "Notes", "properties": [], "data_source_id": "ds"}],
        []))
    p = I.register(object(), "https://n/new_pg", slug="lecture", log=lambda *_: None)
    assert p.page_id == "new_pg"                 # 승격 — page_id 채워짐
    assert p.databases and p.databases[0]["key"] == "notes"
    assert p.prompt == "개념별 헤딩"              # 프롬프트 보존


def test_refresh_keeps_the_body_when_the_runtime_is_installed_but_broken():
    """재리뷰 Important 2 의 `refresh()` 대응 짝 — 브리프가 "`refresh()` 도 같은
    모양이니 둘 다 고쳐라"라고 명시했다."""
    I.register(FakeSession(_routes()), PGROOT, runtime=FakeRuntime(), log=lambda *_: None)
    before = P.load("job-tracker")
    assert before.summary == "지원 추적" and before.body == "## 노트\n본문\n"

    broken = FakeRuntime(RuntimeError("설치는 됐지만 죽어있음"))
    after = I.refresh(FakeSession(_routes()), "job-tracker", runtime=broken,
                      log=lambda *_: None)
    assert after.summary == before.summary and after.body == before.body
    assert after.schema_fetched_at


def test_refresh_keeps_the_body_when_notes_are_not_regenerated():
    I.register(FakeSession(_routes()), PGROOT, runtime=FakeRuntime(), log=lambda *_: None)
    before = P.load("job-tracker")
    after = I.refresh(FakeSession(_routes()), "job-tracker", runtime=None,
                      log=lambda *_: None)
    assert after.body == before.body and after.summary == before.summary
    assert after.schema_fetched_at


# --- 구조 순회: pages[] 개요 + child_page 재귀 ---

def _children(*blocks, has_more=False):
    from tests.skills.test_templates_store import FakeResp
    return FakeResp(200, {"results": list(blocks), "has_more": has_more})


def _hb(bid, level, text):   # heading block
    return {"id": bid, "type": f"heading_{level}",
            f"heading_{level}": {"rich_text": [{"plain_text": text}]},
            "has_children": False}


def _child_page(bid, title):
    return {"id": bid, "type": "child_page", "child_page": {"title": title},
            "has_children": True}


def _child_db(bid, title):
    return {"id": bid, "type": "child_database", "child_database": {"title": title},
            "has_children": False}


def test_walk_captures_headings_per_page():
    from notionmemory.skills.templates import introspect as I
    from tests.skills.test_templates_store import FakeSession
    sess = FakeSession({("GET", "/blocks/root/children"):
                        _children(_hb("h1", 2, "소개"), _hb("h2", 2, "본론"))})
    pages, db_ids = I.walk_structure(sess, "root")
    assert len(pages) == 1
    assert pages[0]["page_id"] == "root" and pages[0]["depth"] == 0
    assert pages[0]["headings"] == ["소개", "본론"]
    assert db_ids == []


def test_walk_recurses_into_child_pages():
    from notionmemory.skills.templates import introspect as I
    from tests.skills.test_templates_store import FakeSession
    sess = FakeSession({
        ("GET", "/blocks/root/children"): _children(_hb("h1", 1, "허브"),
                                                    _child_page("sub", "논문 A")),
        ("GET", "/blocks/sub/children"): _children(_hb("h2", 2, "요약"))})
    pages, _ = I.walk_structure(sess, "root")
    by_id = {p["page_id"]: p for p in pages}
    assert set(by_id) == {"root", "sub"}
    assert by_id["sub"]["depth"] == 1 and by_id["sub"]["parent"] == "root"
    assert by_id["sub"]["title"] == "논문 A"
    assert by_id["sub"]["headings"] == ["요약"]


def test_walk_records_child_database_block_ids_per_page_and_flat():
    from notionmemory.skills.templates import introspect as I
    from tests.skills.test_templates_store import FakeSession
    sess = FakeSession({("GET", "/blocks/root/children"):
                        _children(_child_db("db1", "Papers"))})
    pages, db_ids = I.walk_structure(sess, "root")
    assert db_ids == ["db1"]
    assert pages[0]["databases"] == ["db1"]     # 임시로 블록 id (나중에 key 로 치환)


def test_register_accepts_a_document_only_page(monkeypatch, tmp_path):
    """DB 없는 페이지도 등록된다 — 예전엔 '데이터베이스가 없습니다'로 거부했다."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import introspect as I
    from notionmemory.skills.templates import profile as P
    from tests.skills.test_templates_store import FakeResp, FakeSession
    sess = FakeSession({
        ("GET", "/pages/2a1b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"):
            FakeResp(200, {"id": "2a1b3c4d5e6f7a8b9c0d1e2f3a4b5c6d", "url": "u",
                           "properties": {"title": {"type": "title",
                                                    "title": [{"plain_text": "내 CV"}]}}}),
        ("GET", "/blocks/2a1b3c4d5e6f7a8b9c0d1e2f3a4b5c6d/children"):
            _children(_hb("h1", 1, "경력"), _hb("h2", 2, "학력"))})
    p = I.register(sess, "2a1b3c4d5e6f7a8b9c0d1e2f3a4b5c6d", runtime=None, log=lambda *_: None)
    assert p.databases == []
    assert p.pages[0]["headings"] == ["경력", "학력"]
    assert "document" in p.capabilities
    assert P.exists(p.slug)


def test_register_still_refuses_a_truly_empty_page(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import pytest
    from notionmemory.skills.templates import introspect as I
    from tests.skills.test_templates_store import FakeResp, FakeSession
    pid = "1111222233334444555566667777888a"
    sess = FakeSession({
        ("GET", f"/pages/{pid}"): FakeResp(200, {"id": pid, "url": "u",
            "properties": {"title": {"type": "title", "title": [{"plain_text": "빈페이지"}]}}}),
        ("GET", f"/blocks/{pid}/children"): _children()})
    with pytest.raises(RuntimeError) as e:
        I.register(sess, pid, runtime=None, log=lambda *_: None)
    assert "빈" in str(e.value) or "없습니다" in str(e.value)


# --- 순회 가드 (collect_database_ids 에서 walk_structure 로 이식) ---
# walk_structure 는 collect_database_ids 를 대체한다(_build 의 유일한 호출처를 가져갔다).
# collect_database_ids 와 그 전용 테스트는 Step 3 에서 삭제한다 — 아래는 그 하드-원
# 회귀 커버리지(순환·깊이·노드예산·무진행 커서)를 새 함수로 옮긴 것이다.

def _db_block(bid):
    return {"id": bid, "type": "child_database", "has_children": False,
            "child_database": {}}


def test_walk_finds_databases_nested_in_containers():
    from notionmemory.skills.templates import introspect as I
    from tests.skills.test_templates_store import FakeResp, FakeSession
    sess = FakeSession({
        ("GET", "/blocks/root/children"): FakeResp(200, {"results": [
            {"id": "col", "type": "column_list", "has_children": True}]}),
        ("GET", "/blocks/col/children"): FakeResp(200, {"results": [_db_block("b1")]})})
    pages, db_ids = I.walk_structure(sess, "root")
    assert db_ids == ["b1"]
    assert len(pages) == 1          # 컨테이너는 페이지 노드가 아니다


def test_walk_is_cycle_safe_and_does_not_crash_on_self_reference():
    from notionmemory.skills.templates import introspect as I
    from tests.skills.test_templates_store import FakeResp, FakeSession
    sess = FakeSession({("GET", "/blocks/root/children"): FakeResp(200, {"results": [
        {"id": "root", "type": "toggle", "has_children": True}]})}, max_calls=10)
    pages, db_ids = I.walk_structure(sess, "root")
    assert db_ids == []


def test_walk_does_not_recurse_python_stack_on_deeply_nested_containers():
    """컨테이너를 재귀로 소비하면 깊은 토글에서 RecursionError 가 난다 — 반복이어야 한다."""
    from notionmemory.skills.templates import introspect as I
    from tests.skills.test_templates_store import FakeResp, FakeSession
    routes = {("GET", f"/blocks/t{i}/children"): FakeResp(200, {"results": [
                  {"id": f"t{i + 1}", "type": "toggle", "has_children": True}]})
              for i in range(600)}
    routes[("GET", "/blocks/root/children")] = FakeResp(200, {"results": [
        {"id": "t0", "type": "toggle", "has_children": True}]})
    sess = FakeSession(routes)
    pages, db_ids = I.walk_structure(sess, "root", max_nodes=500)   # RecursionError 나면 안 됨
    assert db_ids == []


def test_walk_respects_the_child_page_depth_ceiling():
    from notionmemory.skills.templates import introspect as I
    from tests.skills.test_templates_store import FakeResp, FakeSession
    def _cp(bid):
        return {"id": bid, "type": "child_page", "has_children": True,
                "child_page": {"title": bid}}
    routes = {("GET", f"/blocks/p{i}/children"): FakeResp(200, {"results": [_cp(f"p{i + 1}")]})
              for i in range(12)}
    routes[("GET", "/blocks/root/children")] = FakeResp(200, {"results": [_cp("p0")]})
    sess = FakeSession(routes)
    pages, _ = I.walk_structure(sess, "root", max_depth=3)
    assert max(p["depth"] for p in pages) <= 3


def test_walk_stops_on_has_more_without_cursor():
    from notionmemory.skills.templates import introspect as I
    from tests.skills.test_templates_store import FakeResp, FakeSession
    routes = {("GET", "/blocks/root/children"): FakeResp(200, {
        "results": [_db_block("b1")], "has_more": True, "next_cursor": None})}
    sess = FakeSession(routes, max_calls=5)
    _, db_ids = I.walk_structure(sess, "root")
    assert db_ids == ["b1"] and len(sess.calls) == 1


def test_walk_stops_on_fresh_cursor_every_time_but_repeated_blocks():
    """진행 불변식: 매번 새 커서라도 새 블록을 못 늘리면 멈춘다(실기 재현 200회+)."""
    from notionmemory.skills.templates import introspect as I
    from tests.skills.test_templates_store import FakeResp, FakeSession
    pages_resp = [FakeResp(200, {"results": [_db_block("b1")],
                                 "has_more": True, "next_cursor": f"fresh-{i}"})
                  for i in range(50)]
    sess = FakeSession({("GET", "/blocks/root/children"): pages_resp}, max_calls=5)
    _, db_ids = I.walk_structure(sess, "root")
    assert db_ids == ["b1"] and len(sess.calls) == 2


def test_walk_respects_a_total_node_budget():
    from notionmemory.skills.templates import introspect as I
    from tests.skills.test_templates_store import FakeResp, FakeSession
    def _page(i, has_more):
        return FakeResp(200, {"results": [_db_block(f"db{i}_{j}") for j in range(100)],
                              "has_more": has_more, "next_cursor": f"c{i}" if has_more else None})
    resp = [_page(0, True), _page(1, True), _page(2, True), _page(3, False)]
    sess = FakeSession({("GET", "/blocks/root/children"): resp}, max_calls=6)
    stats: dict = {}
    _, db_ids = I.walk_structure(sess, "root", max_nodes=250, stats=stats)
    assert len(db_ids) == 250 and stats.get("capped") is True
