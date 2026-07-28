"""TemplateStore — 페이지네이션·절단·health 전이. 401/403 이 삭제 트리거가 아님을 못 박는다."""
import json

import pytest

from notionmemory.skills.templates import profile as P
from notionmemory.skills.templates import store as S


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeSession:
    """(method, path) → 응답 또는 응답 리스트(호출 순서대로 소비).

    `max_calls` 를 주면 그 이상 호출됐을 때 크게 실패한다 — 페이지네이션 회귀
    테스트가 무한루프로 CI 를 멈춰 세우는 대신, 소리나게 실패해야 한다."""

    def __init__(self, routes=None, max_calls=None):
        self.routes = routes or {}
        self.calls = []
        self.max_calls = max_calls

    def request(self, method, path, **kwargs):
        if self.max_calls is not None and len(self.calls) >= self.max_calls:
            raise AssertionError(
                f"{self.max_calls}번 넘게 호출됨 — 페이지네이션이 진행 없이 도는 중")
        self.calls.append((method, path, kwargs.get("json")))
        entry = self.routes.get((method, path))
        if entry is None:
            return FakeResp(200, {"results": [], "has_more": False})
        if isinstance(entry, list):
            return entry.pop(0) if len(entry) > 1 else entry[0]
        return entry


@pytest.fixture(autouse=True)
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _profile(slug="job-tracker"):
    return P.Profile(
        slug=slug, name="Job Tracker", page_id="pg_root", page_url="https://n/pg_root",
        summary="지원 추적", capabilities=["date", "text"],
        databases=[
            {"key": "applications", "title": "Applications", "database_id": "db_a",
             "data_source_id": "ds_a", "title_property": "Position", "missing": False,
             "properties": [
                 {"name": "Position", "type": "title", "writable": True, "filterable": True},
                 {"name": "Stage", "type": "select", "writable": True, "filterable": True,
                  "choices": ["Applied", "Offer"]},
                 {"name": "Company", "type": "relation", "writable": True,
                  "filterable": True, "relates_to": "companies"},
             ]},
            {"key": "companies", "title": "Companies", "database_id": "db_c",
             "data_source_id": "ds_c", "title_property": "Name", "missing": False,
             "properties": [
                 {"name": "Name", "type": "title", "writable": True, "filterable": True}]},
        ])


def _row(i, title="Backend"):
    return {"id": f"pg_{i}", "url": f"https://n/pg_{i}", "properties": {
        "Position": {"type": "title", "title": [{"plain_text": title}]},
        "Stage": {"type": "select", "select": {"name": "Applied"}},
        "Company": {"type": "relation", "relation": []}}}


def _page(rows, has_more=False, cursor=None):
    return FakeResp(200, {"results": rows, "has_more": has_more, "next_cursor": cursor})


# --- 조회 ---

def test_query_flattens_and_keeps_row_id():
    sess = FakeSession({("POST", "/data_sources/ds_a/query"): _page([_row(1)])})
    out = S.TemplateStore(sess).query(_profile(), "applications")
    assert out["rows"][0]["id"] == "pg_1"
    assert out["rows"][0]["Position"] == "Backend"


def test_query_default_limit_is_twenty_five():
    sess = FakeSession({("POST", "/data_sources/ds_a/query"):
                        _page([_row(i) for i in range(30)])})
    out = S.TemplateStore(sess).query(_profile(), "applications")
    assert len(out["rows"]) == 25
    assert out["capped"] is True and out["cap"] == 25


def test_query_page_size_never_exceeds_notion_max():
    sess = FakeSession({("POST", "/data_sources/ds_a/query"): _page([])})
    S.TemplateStore(sess).query(_profile(), "applications", limit=500)
    body = sess.calls[0][2]
    assert body["page_size"] <= 100


def test_query_follows_cursor_until_limit_is_reached():
    first = _page([_row(i) for i in range(100)], has_more=True, cursor="c1")
    second = _page([_row(i) for i in range(100, 150)])
    sess = FakeSession({("POST", "/data_sources/ds_a/query"): [first, second]})
    out = S.TemplateStore(sess).query(_profile(), "applications", limit=120)
    assert len(out["rows"]) == 120
    assert sess.calls[1][2]["start_cursor"] == "c1"


def test_all_stops_at_the_safety_cap_and_reports_it():
    forever = FakeResp(200, {"results": [_row(i) for i in range(100)],
                             "has_more": True, "next_cursor": "c"})
    sess = FakeSession({("POST", "/data_sources/ds_a/query"): forever})
    out = S.TemplateStore(sess).query(_profile(), "applications", fetch_all=True)
    assert len(out["rows"]) == S.ALL_CAP
    assert out["capped"] is True and out["cap"] == S.ALL_CAP


def test_query_capped_is_false_on_an_exact_landing():
    """cap 에 정확히 도달 + has_more=False — 완료이지 절단이 아니다(landing case, 미검증
    이었던 경계)."""
    sess = FakeSession({("POST", "/data_sources/ds_a/query"):
                        _page([_row(i) for i in range(25)], has_more=False)})
    out = S.TemplateStore(sess).query(_profile(), "applications", limit=25)
    assert len(out["rows"]) == 25
    assert out["capped"] is False


def test_query_page_size_on_the_tail_request_is_bounded_too():
    """기존 테스트는 calls[0] 만 본다 — tail 요청의 page_size 는 미검증이었다."""
    first = _page([_row(i) for i in range(100)], has_more=True, cursor="c1")
    second = _page([_row(i) for i in range(100, 120)])
    sess = FakeSession({("POST", "/data_sources/ds_a/query"): [first, second]})
    S.TemplateStore(sess).query(_profile(), "applications", limit=120)
    assert sess.calls[-1][2]["page_size"] == 20


def test_fetch_stops_when_has_more_is_true_but_no_cursor_is_given():
    """실기 재현: `has_more:true` 인데 `next_cursor` 가 없으면(비거나 null) 같은
    첫 페이지를 cap 까지 재요청해 1000행이 전부 같은 행이 되는 사고가 났었다 —
    진행이 불가능하면 곧장 절단으로 멈춰야 한다.

    이건 cap 도달이 아니라 서버 정체다 — `capped=True` 로 보고하면 "1000건에서
    잘림, 조건을 좁히세요"라는 확신에 찬 거짓말이 된다(실제로는 1행에서 멈췄다).
    `stalled` 로 구분해서 보고해야 한다(리뷰 지적)."""
    stuck = FakeResp(200, {"results": [_row(1)], "has_more": True, "next_cursor": None})
    sess = FakeSession({("POST", "/data_sources/ds_a/query"): stuck}, max_calls=5)
    out = S.TemplateStore(sess).query(_profile(), "applications", fetch_all=True)
    assert len(sess.calls) == 1
    assert len(out["rows"]) == 1        # 같은 행을 cap 까지 반복 수집하지 않는다
    assert out["capped"] is False       # cap(1000)엔 닿지 않았다 — 정체였을 뿐
    assert out["stalled"] is True


def test_fetch_stops_on_an_empty_page_with_has_more_true():
    """실기 재현: `has_more:true` + `results:[]` 는 행수를 전혀 늘리지 않아 cap 도달
    조건이 걸리지 않는다 — 2초에 백만 요청까지 실제로 돈 패턴이다.

    이것도 cap 도달이 아니라 서버 정체다 — 같은 이유로 `capped` 가 아니라 `stalled`
    여야 한다(리뷰 지적)."""
    empty_forever = FakeResp(200, {"results": [], "has_more": True, "next_cursor": "c"})
    sess = FakeSession({("POST", "/data_sources/ds_a/query"): empty_forever}, max_calls=5)
    out = S.TemplateStore(sess).query(_profile(), "applications", fetch_all=True)
    assert len(sess.calls) == 1
    assert out["rows"] == []
    assert out["capped"] is False
    assert out["stalled"] is True


def test_fetch_handles_results_null_without_crashing():
    """`results: null` 은 malformed 응답이지만 `render.plain` 처럼 total 해야 한다 —
    TypeError 로 죽지 않는다(§5)."""
    sess = FakeSession({("POST", "/data_sources/ds_a/query"):
                        FakeResp(200, {"results": None, "has_more": False})})
    out = S.TemplateStore(sess).query(_profile(), "applications")
    assert out["rows"] == []


def test_query_reports_whether_a_sort_was_given():
    sess = FakeSession({("POST", "/data_sources/ds_a/query"): _page([_row(1)])})
    st = S.TemplateStore(sess)
    assert st.query(_profile(), "applications")["sorted"] is False
    out = st.query(_profile(), "applications",
                   sorts=[{"property": "Position", "direction": "ascending"}])
    assert out["sorted"] is True
    assert sess.calls[-1][2]["sorts"] == [{"property": "Position", "direction": "ascending"}]


def test_query_default_fields_are_the_profile_property_names():
    sess = FakeSession({("POST", "/data_sources/ds_a/query"): _page([_row(1)])})
    out = S.TemplateStore(sess).query(_profile(), "applications")
    assert out["fields"] == ["Position", "Stage", "Company"]


def test_query_fields_projection_is_validated_against_the_profile():
    sess = FakeSession({("POST", "/data_sources/ds_a/query"): _page([_row(1)])})
    st = S.TemplateStore(sess)
    assert st.query(_profile(), "applications", fields=["Position"])["fields"] == ["Position"]
    with pytest.raises(ValueError):
        st.query(_profile(), "applications", fields=["Nope"])


def test_count_does_not_return_rows():
    sess = FakeSession({("POST", "/data_sources/ds_a/query"):
                        _page([_row(i) for i in range(7)])})
    assert S.TemplateStore(sess).count(_profile(), "applications") == 7


def test_count_reports_truncation_through_log_when_capped():
    """`count()` 는 `-> int` 계약을 유지하지만, cap 에 닿으면 `log` 로 "적어도"를
    알려야 한다 — 안 그러면 4000건짜리 DB 를 1000이라고 확신 있게 잘못 답한다."""
    forever = FakeResp(200, {"results": [_row(i) for i in range(100)],
                             "has_more": True, "next_cursor": "c"})
    sess = FakeSession({("POST", "/data_sources/ds_a/query"): forever}, max_calls=15)
    logged = []
    out = S.TemplateStore(sess, log=logged.append).count(_profile(), "applications")
    assert out == S.ALL_CAP
    assert logged and str(S.ALL_CAP) in logged[0]


def test_count_does_not_log_when_not_capped():
    sess = FakeSession({("POST", "/data_sources/ds_a/query"):
                        _page([_row(i) for i in range(7)])})
    logged = []
    S.TemplateStore(sess, log=logged.append).count(_profile(), "applications")
    assert logged == []


def test_count_reports_stall_distinctly_from_cap():
    """cap(1000)에 닿은 게 아니라 서버가 정체된 경우 — 옛 코드는 이것도 `capped`
    로 뭉뚱그려 "1000건에서 잘렸습니다, 실제로는 1000건 이상"이라고 확신에 찬
    거짓말을 했다(실제로는 1건뿐이었다). 정체는 다른 말을 해야 한다(리뷰 지적)."""
    stuck = FakeResp(200, {"results": [_row(1)], "has_more": True, "next_cursor": None})
    sess = FakeSession({("POST", "/data_sources/ds_a/query"): stuck}, max_calls=3)
    logged = []
    out = S.TemplateStore(sess, log=logged.append).count(_profile(), "applications")
    assert out == 1
    assert logged
    assert str(S.ALL_CAP) not in logged[0]     # "1000건 이상"은 이 상황에서 거짓말
    assert "1건" in logged[0]                  # 실제로 확인된 건수는 밝힌다


def test_query_on_a_missing_database_says_which():
    p = _profile()
    p.databases[0]["missing"] = True
    with pytest.raises(ValueError) as e:
        S.TemplateStore(FakeSession()).query(p, "applications")
    assert "applications" in str(e.value)


# --- relation 해석기: 쓰기와 조회가 같은 것을 쓴다 ---

def test_relation_resolver_returns_the_single_match_id():
    sess = FakeSession({("POST", "/data_sources/ds_c/query"):
                        _page([{"id": "pg_acme", "properties": {}}])})
    resolve = S.TemplateStore(sess).relation_resolver(_profile())
    assert resolve("companies", "Acme") == "pg_acme"
    assert sess.calls[0][2]["filter"] == {
        "property": "Name", "title": {"equals": "Acme"}}


def test_relation_resolver_rejects_zero_and_many_with_candidates():
    sess = FakeSession({("POST", "/data_sources/ds_c/query"): _page([])})
    with pytest.raises(ValueError) as e:
        S.TemplateStore(sess).relation_resolver(_profile())("companies", "Acme")
    assert "Acme" in str(e.value)

    many = _page([{"id": "a", "properties": {
                       "Name": {"type": "title", "title": [{"plain_text": "Acme Inc"}]}}},
                  {"id": "b", "properties": {
                       "Name": {"type": "title", "title": [{"plain_text": "Acme Ltd"}]}}}])
    sess2 = FakeSession({("POST", "/data_sources/ds_c/query"): many})
    with pytest.raises(ValueError) as e2:
        S.TemplateStore(sess2).relation_resolver(_profile())("companies", "Acme")
    assert "Acme Inc" in str(e2.value) and "Acme Ltd" in str(e2.value)


def test_relation_resolver_rejects_a_key_outside_the_profile():
    with pytest.raises(ValueError):
        S.TemplateStore(FakeSession()).relation_resolver(_profile())("nope", "Acme")


def test_relation_resolver_handles_results_null_without_crashing():
    """`_fetch` 는 `results: null` 에 대해 total 하도록 고쳐졌지만, 같은 엔드포인트를
    치는 `relation_resolver` 의 동일한 패턴은 그대로 남아 `len(None)` 으로 TypeError
    가 났다(리뷰 지적) — 결과 0건과 같은 취급을 받아야 한다."""
    sess = FakeSession({("POST", "/data_sources/ds_c/query"):
                        FakeResp(200, {"results": None})})
    with pytest.raises(ValueError) as e:
        S.TemplateStore(sess).relation_resolver(_profile())("companies", "Acme")
    assert "Acme" in str(e.value)


# --- 쓰기 ---

def test_add_posts_validated_properties_and_returns_id_and_url():
    sess = FakeSession({("POST", "/pages"):
                        FakeResp(200, {"id": "pg_new", "url": "https://n/pg_new"})})
    out = S.TemplateStore(sess).add(_profile(), "applications",
                                    [("Position", "Backend"), ("Stage", "Applied")])
    body = sess.calls[0][2]
    assert body["parent"] == {"data_source_id": "ds_a"}
    assert body["properties"]["Stage"] == {"select": {"name": "Applied"}}
    assert out["id"] == "pg_new" and out["url"] == "https://n/pg_new"


def test_add_rejects_a_bad_value_before_any_http_call():
    sess = FakeSession()
    with pytest.raises(ValueError):
        S.TemplateStore(sess).add(_profile(), "applications", [("Stage", "Nope")])
    assert sess.calls == []


def test_add_attaches_notes_as_body_blocks():
    sess = FakeSession({("POST", "/pages"): FakeResp(200, {"id": "x", "url": "u"})})
    S.TemplateStore(sess).add(_profile(), "applications",
                              [("Position", "Backend")], notes="# 메모\n내용")
    assert sess.calls[0][2]["children"]


def test_add_with_overflow_blocks_and_no_page_id_raises_cleanly_not_a_keyerror():
    """블록 오버플로 경로(§5) — 페이지는 이미 Notion 에 생성됐다. `page['id']` KeyError 로
    죽으면 이미 쓰여진 작업 결과를 잃는 유일한 크래시 경로가 된다. 명확한 RuntimeError 로
    멈춰야 한다. 그리고 그 에러는 같은 응답에 이미 들어있던 `url` 을 흘리지 않아야 한다
    — 데이터 손실에 가까운 상황에서 "Notion 에서 직접 찾아보세요"보다 손에 쥔 링크를
    건네는 쪽이 훨씬 낫다(리뷰 지적)."""
    sess = FakeSession({("POST", "/pages"): FakeResp(200, {"url": "https://n/x"})})  # id 없음
    notes = "\n\n".join(f"para {i}" for i in range(150))    # 150개 문단 블록 > 100
    with pytest.raises(RuntimeError) as e:
        S.TemplateStore(sess).add(_profile(), "applications",
                                  [("Position", "Backend")], notes=notes)
    assert "https://n/x" in str(e.value)
    assert all(m != "PATCH" for m, _, _ in sess.calls)


def test_add_with_no_overflow_and_no_page_id_raises_instead_of_returning_empty_id():
    """블록이 100개 이하라 오버플로는 아니어도, id 없는 응답을 `{'id': '', ...}` 로
    조용히 돌려주면 이어지는 update/archive 가 존재하지 않는 빈 id 를 조용히 때린다
    — 오버플로 경로만이 아니라 이 경로도 명확히 멈춰야 한다(리뷰 지적)."""
    sess = FakeSession({("POST", "/pages"): FakeResp(200, {"url": "https://n/y"})})  # id 없음
    with pytest.raises(RuntimeError) as e:
        S.TemplateStore(sess).add(_profile(), "applications", [("Position", "Backend")])
    assert "https://n/y" in str(e.value)


def test_update_patches_only_given_properties():
    sess = FakeSession({("PATCH", "/pages/pg_1"): FakeResp(200, {"id": "pg_1"})})
    S.TemplateStore(sess).update(_profile(), "applications", "pg_1", [("Stage", "Offer")])
    assert sess.calls[0][2] == {"properties": {"Stage": {"select": {"name": "Offer"}}}}


def test_update_with_no_pairs_is_rejected():
    with pytest.raises(ValueError):
        S.TemplateStore(FakeSession()).update(_profile(), "applications", "pg_1", [])


def test_archive_sends_in_trash_not_a_delete():
    sess = FakeSession({("PATCH", "/pages/pg_1"): FakeResp(200, {"id": "pg_1"})})
    assert S.TemplateStore(sess).archive(_profile(), "applications", "pg_1") is True
    assert sess.calls[0][2] == {"in_trash": True}
    assert all(m != "DELETE" for m, _, _ in sess.calls)


def test_row_404_is_a_plain_error_and_does_not_delete_the_profile():
    """행 404 는 페이지 단위 404 가 아니다 — 프로필 삭제 트리거가 아니다(스펙 §8)."""
    P.save(_profile())
    sess = FakeSession({("PATCH", "/pages/pg_gone"): FakeResp(404, {})})
    with pytest.raises(RuntimeError) as e:
        S.TemplateStore(sess).archive(_profile(), "applications", "pg_gone")
    assert not isinstance(e.value, S.ProfileGone)
    assert P.exists("job-tracker")


# --- health 전이 ---

def test_health_check_ok():
    sess = FakeSession({("GET", "/pages/pg_root"): FakeResp(200, {"id": "pg_root"})})
    assert S.TemplateStore(sess).health_check(_profile()) == "ok"


def test_health_check_detects_trash_and_keeps_the_file():
    P.save(_profile())
    sess = FakeSession({("GET", "/pages/pg_root"):
                        FakeResp(200, {"id": "pg_root", "in_trash": True})})
    assert S.TemplateStore(sess).health_check(P.load("job-tracker")) == "trashed"
    assert P.exists("job-tracker")


def test_page_404_deletes_the_profile_immediately():
    P.save(_profile())
    sess = FakeSession({("GET", "/pages/pg_root"): FakeResp(404, {})})
    with pytest.raises(S.ProfileGone) as e:
        S.TemplateStore(sess).health_check(P.load("job-tracker"))
    assert "job-tracker" in str(e.value)
    assert not P.exists("job-tracker")


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_never_delete_the_profile(status):
    """토큰 만료나 integration 제거로 등록 전체가 날아가면 재앙이다(스펙 §8 안전장치)."""
    P.save(_profile())
    sess = FakeSession({("GET", "/pages/pg_root"): FakeResp(status, {})})
    with pytest.raises(RuntimeError) as e:
        S.TemplateStore(sess).health_check(P.load("job-tracker"))
    assert not isinstance(e.value, S.ProfileGone)
    assert P.exists("job-tracker")


def test_health_check_degraded_marks_only_the_dead_database():
    P.save(_profile())
    sess = FakeSession({
        ("GET", "/pages/pg_root"): FakeResp(200, {"id": "pg_root"}),
        ("GET", "/data_sources/ds_c"): FakeResp(404, {}),
        ("GET", "/data_sources/ds_a"): FakeResp(200, {"id": "ds_a"})})
    p = P.load("job-tracker")
    assert S.TemplateStore(sess).health_check(p) == "degraded"
    by_key = {db["key"]: db for db in p.databases}
    assert by_key["companies"]["missing"] is True
    assert by_key["applications"]["missing"] is False


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_in_the_per_database_loop_never_deletes_the_profile(status):
    """루트 페이지 GET 은 통과했지만 두 번째 database 확인에서 401/403 이 나는 경우 —
    기존 테스트는 루트 GET 에서만 이걸 검증했고, 삭제 정책이 여기서도 지켜지는지는
    빈틈이었다(스펙 §8 안전장치)."""
    P.save(_profile())
    sess = FakeSession({
        ("GET", "/pages/pg_root"): FakeResp(200, {"id": "pg_root"}),
        ("GET", "/data_sources/ds_a"): FakeResp(200, {"id": "ds_a"}),
        ("GET", "/data_sources/ds_c"): FakeResp(status, {})})
    p = P.load("job-tracker")
    with pytest.raises(RuntimeError) as e:
        S.TemplateStore(sess).health_check(p)
    assert not isinstance(e.value, S.ProfileGone)
    assert P.exists("job-tracker")


def test_health_check_leaves_earlier_databases_unmutated_in_memory_when_a_later_one_raises():
    """루프 중간에 401/403 이 나면, 이미 통과한 앞선 db 도 in-memory 프로필에 플래그가
    남아선 안 된다(§4) — 훗날 뭔가가 이 객체를 그대로 저장하면 미완료 점검 결과가
    디스크로 샌다."""
    p = _profile()
    p.databases[0]["missing"] = "untouched"     # 마커 — 루프가 이 값을 덮어쓰면 버그
    sess = FakeSession({
        ("GET", "/pages/pg_root"): FakeResp(200, {"id": "pg_root"}),
        ("GET", "/data_sources/ds_a"): FakeResp(200, {"id": "ds_a"}),
        ("GET", "/data_sources/ds_c"): FakeResp(401, {})})
    with pytest.raises(RuntimeError):
        S.TemplateStore(sess).health_check(p)
    assert p.databases[0]["missing"] == "untouched"


def test_health_check_survives_a_database_dict_without_a_key_field():
    """이 모듈은 다른 곳에서는 `.get` 으로 방어적이다(`profile.find_db` 등) — `health_check`
    가 `db['key']` 로 색인하면 key 없는 db dict 는 KeyError 로 죽는다(리뷰 지적).
    리스트 인덱스로 색인하면 죽지 않는다."""
    p = _profile()
    del p.databases[0]["key"]
    P.save(p)
    sess = FakeSession({
        ("GET", "/pages/pg_root"): FakeResp(200, {"id": "pg_root"}),
        ("GET", "/data_sources/ds_a"): FakeResp(200, {"id": "ds_a"}),
        ("GET", "/data_sources/ds_c"): FakeResp(200, {"id": "ds_c"})})
    loaded = P.load("job-tracker")
    assert S.TemplateStore(sess).health_check(loaded) == "ok"


def test_health_check_duplicate_db_keys_do_not_collapse_into_one_status():
    """`db['key']` 로 색인하면 같은 key 를 가진 두 db 가 서로의 상태를 덮어써 조용히
    하나로 뭉개진다(리뷰 지적) — 리스트 인덱스로 색인하면 각자 자기 응답을 받는다."""
    p = _profile()
    p.databases[1]["key"] = "applications"     # companies 를 일부러 같은 key 로
    P.save(p)
    sess = FakeSession({
        ("GET", "/pages/pg_root"): FakeResp(200, {"id": "pg_root"}),
        ("GET", "/data_sources/ds_a"): FakeResp(200, {"id": "ds_a"}),
        ("GET", "/data_sources/ds_c"): FakeResp(404, {})})
    loaded = P.load("job-tracker")
    S.TemplateStore(sess).health_check(loaded)
    assert loaded.databases[0]["missing"] is False    # ds_a 는 200 이었다
    assert loaded.databases[1]["missing"] is True      # ds_c 는 404 였다 — 서로 안 섞인다


def test_health_check_does_not_record_a_transient_failure_as_ok():
    """200/404 도 401/403 도 아닌 상태(예: 503) 는 '정상 판정'으로 기록되면 안 된다 —
    missing=False 로 단정해 clean bill of health 를 쓰는 대신 이전 상태를 보존한다.

    기존 테스트는 프로필을 미리 `degraded` 로 세팅해두어 `result != "ok"` 가 우연히
    통과했다 — `Profile.health` 기본값이 "ok"라, 한 번도 점검한 적 없는 갓 등록된
    프로필로는 이 버그가 그대로 드러난다(리뷰 지적): 반환값이 "ok"가 되어 전체
    장애를 "정상"으로 보고한다. `log` 채널도 그동안 이 경로에서 안 쓰였다 — 이제는
    쓴다."""
    p = _profile()
    P.save(p)
    sess = FakeSession({
        ("GET", "/pages/pg_root"): FakeResp(200, {"id": "pg_root"}),
        ("GET", "/data_sources/ds_a"): FakeResp(503, {})})
    loaded = P.load("job-tracker")
    assert loaded.health == "ok"        # 기본값 — 아직 한 번도 점검한 적 없다
    logged = []
    result = S.TemplateStore(sess, log=logged.append).health_check(loaded)
    assert result != "ok"
    assert logged                       # "점검 못 함"을 알릴 채널이 이제 쓰인다
    reloaded = P.load("job-tracker")
    assert reloaded.health == "ok"              # 디스크의 이전 상태는 그대로 보존
    assert reloaded.health_checked_at == ""
