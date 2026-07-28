"""필터 컴파일 — 연산자 13종이 타입별 Notion 조건으로 정확히 번역되는가."""
import pytest

from notionmemory.skills.templates import filters


def _db():
    return {"key": "applications", "title_property": "Position", "properties": [
        {"name": "Position", "type": "title", "writable": True, "filterable": True},
        {"name": "Notes", "type": "rich_text", "writable": True, "filterable": True},
        {"name": "Salary", "type": "number", "writable": True, "filterable": True},
        {"name": "Remote", "type": "checkbox", "writable": True, "filterable": True},
        {"name": "Site", "type": "url", "writable": True, "filterable": True},
        {"name": "Applied On", "type": "date", "writable": True, "filterable": True},
        {"name": "Stage", "type": "select", "writable": True, "filterable": True,
         "choices": ["Applied", "Interview", "Offer"]},
        {"name": "Tags", "type": "multi_select", "writable": True, "filterable": True,
         "choices": ["remote"]},
        {"name": "Company", "type": "relation", "writable": True, "filterable": True,
         "relates_to": "companies"},
        {"name": "Days Open", "type": "formula", "writable": False, "filterable": True},
        {"name": "Approve", "type": "button", "writable": False, "filterable": False},
    ]}


def _resolver(key, title):
    if title == "Acme":
        return "pg_acme"
    raise ValueError(f"'{key}'에서 '{title}'를 찾지 못했습니다")


def where(*clauses):
    return filters.build_where(_db(), [filters.parse_where(c) for c in clauses],
                               resolve_relation=_resolver)


# --- 파싱 ---

def test_parse_where_symbolic_with_and_without_spaces():
    assert filters.parse_where("Days Open>30") == ("Days Open", ">", "30")
    assert filters.parse_where("Days Open >= 30") == ("Days Open", ">=", "30")
    assert filters.parse_where("Stage=Offer") == ("Stage", "=", "Offer")
    assert filters.parse_where("Stage != Offer") == ("Stage", "!=", "Offer")


def test_parse_where_word_operators_require_spaces():
    assert filters.parse_where("Notes contains 쿠버네티스") == ("Notes", "contains", "쿠버네티스")
    assert filters.parse_where("Notes !contains 광고") == ("Notes", "!contains", "광고")
    assert filters.parse_where("Position starts Back") == ("Position", "starts", "Back")
    assert filters.parse_where("Position ends Engineer") == ("Position", "ends", "Engineer")
    assert filters.parse_where("Stage in Applied,Interview") == ("Stage", "in", "Applied,Interview")


def test_parse_where_empty_operators_take_no_value():
    assert filters.parse_where("Site empty") == ("Site", "empty", "")
    assert filters.parse_where("Site !empty") == ("Site", "!empty", "")
    with pytest.raises(ValueError) as e:
        filters.parse_where("Site empty x")
    assert "값을 받지 않습니다" in str(e.value)


def test_parse_where_property_name_containing_a_word_operator_is_not_split():
    """'Contains Notes' 같은 이름이 있어도 공백 구분 토큰만 연산자로 본다."""
    assert filters.parse_where("Contains Notes contains x") == ("Contains Notes", "contains", "x")


def test_parse_where_without_operator_is_rejected():
    with pytest.raises(ValueError) as e:
        filters.parse_where("Stage")
    assert "연산자" in str(e.value)


def test_parse_sort_directions_and_default():
    assert filters.parse_sort("Applied On desc") == {
        "property": "Applied On", "direction": "descending"}
    assert filters.parse_sort("Applied On asc") == {
        "property": "Applied On", "direction": "ascending"}
    assert filters.parse_sort("Applied On") == {
        "property": "Applied On", "direction": "ascending"}
    with pytest.raises(ValueError):
        filters.parse_sort("Applied On sideways")


# --- 타입별 조건 번역 ---

def test_equality_uses_the_property_type_key():
    assert where("Stage=Offer") == {"property": "Stage", "select": {"equals": "Offer"}}
    assert where("Salary!=100") == {"property": "Salary", "number": {"does_not_equal": 100.0}}
    assert where("Remote=true") == {"property": "Remote", "checkbox": {"equals": True}}
    assert where("Notes=x") == {"property": "Notes", "rich_text": {"equals": "x"}}


def test_number_comparisons():
    assert where("Salary>=9000") == {
        "property": "Salary", "number": {"greater_than_or_equal_to": 9000.0}}
    assert where("Salary<9000") == {"property": "Salary", "number": {"less_than": 9000.0}}


def test_date_comparisons_use_before_after_vocabulary():
    assert where("Applied On>=2026-07-01") == {
        "property": "Applied On", "date": {"on_or_after": "2026-07-01"}}
    assert where("Applied On<2026-08-01") == {
        "property": "Applied On", "date": {"before": "2026-08-01"}}


def test_formula_comparison_is_allowed_even_though_it_is_read_only():
    """이것이 filterable 을 writable 과 분리한 이유다(스펙 §3)."""
    assert where("Days Open>30") == {
        "property": "Days Open", "formula": {"number": {"greater_than": 30.0}}}


def test_contains_family():
    assert where("Notes contains 쿠버") == {
        "property": "Notes", "rich_text": {"contains": "쿠버"}}
    assert where("Notes !contains 광고") == {
        "property": "Notes", "rich_text": {"does_not_contain": "광고"}}
    assert where("Tags contains remote") == {
        "property": "Tags", "multi_select": {"contains": "remote"}}


def test_starts_and_ends_are_text_only():
    assert where("Position starts Back") == {
        "property": "Position", "title": {"starts_with": "Back"}}
    with pytest.raises(ValueError) as e:
        where("Salary starts 9")
    assert "starts" in str(e.value)


def test_empty_operators_produce_is_empty():
    assert where("Site empty") == {"property": "Site", "url": {"is_empty": True}}
    assert where("Site !empty") == {"property": "Site", "url": {"is_not_empty": True}}


def test_in_expands_to_an_or_compound():
    assert where("Stage in Applied,Interview") == {"or": [
        {"property": "Stage", "select": {"equals": "Applied"}},
        {"property": "Stage", "select": {"equals": "Interview"}}]}


def test_in_is_the_only_or_surface_and_rejects_free_types():
    with pytest.raises(ValueError) as e:
        where("Salary in 1,2")
    assert "in" in str(e.value)


def test_relation_filter_reuses_the_write_path_resolver():
    """사용자는 쓸 때든 찾을 때든 회사 이름을 치지 page id 를 치지 않는다."""
    assert where("Company contains Acme") == {
        "property": "Company", "relation": {"contains": "pg_acme"}}


def test_relation_filter_miss_propagates_resolver_error():
    with pytest.raises(ValueError) as e:
        where("Company contains NoSuchCo")
    assert "NoSuchCo" in str(e.value)


def test_unfilterable_property_is_rejected():
    with pytest.raises(ValueError) as e:
        where("Approve=x")
    assert "Approve" in str(e.value)


def test_operator_not_available_for_type_lists_what_is():
    with pytest.raises(ValueError) as e:
        where("Remote>1")
    msg = str(e.value)
    assert "Remote" in msg and "=" in msg


def test_multiple_clauses_are_anded():
    out = filters.build_where(
        _db(), [filters.parse_where("Stage=Offer"), filters.parse_where("Salary>1")],
        resolve_relation=_resolver)
    assert out == {"and": [{"property": "Stage", "select": {"equals": "Offer"}},
                           {"property": "Salary", "number": {"greater_than": 1.0}}]}


def test_no_clauses_means_no_filter():
    assert filters.build_where(_db(), [], resolve_relation=_resolver) is None


# --- 검색 ---

def test_search_is_token_and_times_text_property_or():
    out = filters.build_search(_db(), "kube 마이그레이션")
    assert list(out) == ["and"]
    assert len(out["and"]) == 2
    first = out["and"][0]["or"]
    assert {"property": "Position", "title": {"contains": "kube"}} in first
    assert {"property": "Notes", "rich_text": {"contains": "kube"}} in first
    assert {"property": "Site", "url": {"contains": "kube"}} in first
    # 텍스트 계열이 아닌 속성은 대상이 아니다
    assert all(c["property"] != "Salary" for c in first)


def test_search_nesting_stays_within_notions_two_levels():
    out = filters.build_search(_db(), "a b")
    for group in out["and"]:
        assert list(group) == ["or"]
        for leaf in group["or"]:
            assert "and" not in leaf and "or" not in leaf


def test_single_token_search_still_wraps_in_and_for_shape_stability():
    out = filters.build_search(_db(), "kube")
    assert list(out) == ["and"] and len(out["and"]) == 1


def test_search_can_be_narrowed_with_fields():
    out = filters.build_search(_db(), "kube", fields=["Notes"])
    assert out["and"][0]["or"] == [{"property": "Notes", "rich_text": {"contains": "kube"}}]


def test_search_with_no_text_properties_raises():
    db = {"key": "k", "properties": [{"name": "N", "type": "number", "filterable": True}]}
    with pytest.raises(ValueError) as e:
        filters.build_search(db, "kube")
    assert "텍스트" in str(e.value)


def test_empty_search_is_none():
    assert filters.build_search(_db(), "   ") is None


# --- 결합 ---

def test_compile_query_ands_where_and_search_and_includes_sorts():
    out = filters.compile_query(
        _db(), wheres=[filters.parse_where("Stage=Offer")], search="kube",
        sorts=[filters.parse_sort("Applied On desc")], resolve_relation=_resolver)
    assert list(out["filter"]) == ["and"]
    assert out["sorts"] == [{"property": "Applied On", "direction": "descending"}]


def test_compile_query_omits_empty_keys_entirely():
    out = filters.compile_query(_db(), wheres=[], search="", sorts=[],
                                resolve_relation=_resolver)
    assert out == {}


def test_compile_query_rejects_sort_on_unfilterable_property():
    with pytest.raises(ValueError):
        filters.compile_query(_db(), wheres=[], search="",
                              sorts=[filters.parse_sort("Approve asc")],
                              resolve_relation=_resolver)


def _compound_depth(node, level: int = 0) -> int:
    """`node` 안 and/or 컴파운드의 최대 중첩 깊이. 리프(순수 조건 dict)는 자신을 감싸는
    and/or 가 없으면 0."""
    if not isinstance(node, dict):
        return level
    for key in ("and", "or"):
        if key in node:
            return max((_compound_depth(child, level + 1) for child in node[key]),
                       default=level + 1)
    return level


def test_compile_query_flattens_where_and_search_to_stay_within_two_levels():
    """리뷰 #1 — where 와 search 가 둘 다 있으면 `build_search` 가 이미 낸 `and[or[...]]`
    를 다시 `and` 로 감싸 `and→and→or` 3단계가 되던 버그. Notion 은 2단계까지만
    허용하므로 이런 쿼리는 전부 400 이었다. 조합 5가지(단일 where, 다중 where, in 전개,
    다중 토큰 search, where+search)를 전부 검증한다."""
    cases = [
        dict(wheres=[filters.parse_where("Stage=Offer")], search="", sorts=[]),
        dict(wheres=[filters.parse_where("Stage=Offer"),
                     filters.parse_where("Salary>1")], search="", sorts=[]),
        dict(wheres=[filters.parse_where("Stage in Applied,Interview")],
             search="", sorts=[]),
        dict(wheres=[], search="kube 마이그레이션 배포", sorts=[]),
        dict(wheres=[filters.parse_where("Stage=Offer")], search="kube 마이그레이션",
             sorts=[]),
        dict(wheres=[filters.parse_where("Stage in Applied,Interview"),
                     filters.parse_where("Salary>1")], search="kube 마이그레이션",
             sorts=[]),
    ]
    for kwargs in cases:
        out = filters.compile_query(_db(), resolve_relation=_resolver, **kwargs)
        depth = _compound_depth(out.get("filter", {}))
        assert depth <= 2, f"{kwargs} -> depth {depth}: {out}"


# --- 리뷰 #2: 연산자×타입 매트릭스 (Notion 문서 근거는 각 테스트에 명시) ---

def test_multi_select_has_no_equals_only_contains_and_empty():
    """Notion 문서: multi_select 는 contains/does_not_contain/is_empty/is_not_empty 뿐,
    equals 가 없다. `Stage=Ofer` 식 오타처럼 `Tags=remote` 도 예전엔 유효한 필터로
    컴파일돼 0건을 조용히 반환했다."""
    with pytest.raises(ValueError) as e:
        where("Tags=remote")
    msg = str(e.value)
    allowed = msg.split("사용 가능한 연산자: ")[1]
    assert "Tags" in msg and "contains" in allowed and "=" not in allowed.split(", ")


def test_people_ops_are_contains_and_empty_only():
    """Notion 문서: people(및 그 파생 created_by/last_edited_by) 은 contains/
    does_not_contain/is_empty/is_not_empty 뿐, equals 가 없다."""
    db = _db()
    db["properties"].append(
        {"name": "Owner", "type": "people", "writable": True, "filterable": True})
    with pytest.raises(ValueError):
        filters.build_where(db, [filters.parse_where("Owner=u1")],
                            resolve_relation=_resolver)
    out = filters.build_where(db, [filters.parse_where("Owner contains u1")],
                              resolve_relation=_resolver)
    assert out == {"property": "Owner", "people": {"contains": "u1"}}


def test_created_by_and_last_edited_by_support_contains():
    """리뷰 지적: people-계열인데 CONTAINS_TYPES 에 빠져 유효한 필터가 거부되고 있었다."""
    db = _db()
    db["properties"].append(
        {"name": "Creator", "type": "created_by", "writable": False, "filterable": True})
    out = filters.build_where(db, [filters.parse_where("Creator contains u1")],
                              resolve_relation=_resolver)
    assert out == {"property": "Creator", "created_by": {"contains": "u1"}}


def test_files_only_support_empty_checks():
    """Notion 문서: files 는 is_empty/is_not_empty 뿐 — equals/contains 등 전부 없다."""
    db = _db()
    db["properties"].append(
        {"name": "Attach", "type": "files", "writable": True, "filterable": True})
    out = filters.build_where(db, [filters.parse_where("Attach empty")],
                              resolve_relation=_resolver)
    assert out == {"property": "Attach", "files": {"is_empty": True}}
    with pytest.raises(ValueError):
        filters.build_where(db, [filters.parse_where("Attach=x")],
                            resolve_relation=_resolver)


def test_checkbox_has_no_empty_ops_it_is_non_nullable():
    """Notion 문서: checkbox 는 equals/does_not_equal 뿐이다 — non-nullable 이라 "비어
    있다"는 상태 자체가 없다. `coerce.py` 가 이미 같은 이유로 checkbox 를 nullable 로
    취급하지 않는다."""
    with pytest.raises(ValueError) as e:
        where("Remote empty")
    assert "Remote" in str(e.value)


def test_date_has_no_does_not_equal():
    """Notion 문서: date(및 created_time/last_edited_time)는 equals 는 있지만
    does_not_equal 이 없다 — 다른 비교 연산자와 비대칭이다."""
    assert where("Applied On=2026-07-01") == {
        "property": "Applied On", "date": {"equals": "2026-07-01"}}
    with pytest.raises(ValueError) as e:
        where("Applied On != 2026-07-01")
    assert "Applied On" in str(e.value)


def test_rollup_has_no_string_key_only_number_wrapped_comparisons():
    """Notion 문서: rollup 의 내부 키는 any/every/none/date/number 뿐이고 `string` 은
    존재하지 않는다. 이전 코드는 formula 와 같은 폴백을 rollup 에도 적용해
    `{"rollup": {"string": {...}}}` 를 만들었는데 이건 애초에 유효하지 않은 페이로드다.
    이 스킬은 rollup 집계 타입을 프로필에서 알 수 없으므로 number 로 구성 가능한
    비교(>,<,>=,<=,=,!=)만 지원하고 문자열이 필요한 연산은 거부한다."""
    db = _db()
    db["properties"].append(
        {"name": "Total", "type": "rollup", "writable": False, "filterable": True})
    out = filters.build_where(db, [filters.parse_where("Total>10")],
                              resolve_relation=_resolver)
    assert out == {"property": "Total", "rollup": {"number": {"greater_than": 10.0}}}
    out2 = filters.build_where(db, [filters.parse_where("Total!=5")],
                               resolve_relation=_resolver)
    assert out2 == {"property": "Total", "rollup": {"number": {"does_not_equal": 5.0}}}
    with pytest.raises(ValueError):
        filters.build_where(db, [filters.parse_where("Total contains x")],
                            resolve_relation=_resolver)


# --- 리뷰 #3: select/status/multi_select 값은 choices 대조 (coerce._choice 재사용) ---

def test_equals_rejects_a_value_outside_choices():
    """`--where "Stage=Ofer"` 는 예전엔 유효한 필터로 컴파일돼 0건을 조용히 반환했다.
    coerce.py 의 쓰기 경로가 이미 푼 문제(`_choice`)를 재사용한다."""
    with pytest.raises(ValueError) as e:
        where("Stage=Ofer")
    msg = str(e.value)
    assert "Applied" in msg and "Interview" in msg and "Offer" in msg


def test_in_rejects_a_value_outside_choices():
    with pytest.raises(ValueError) as e:
        where("Stage in Applied,Ofer")
    assert "Offer" in str(e.value)


def test_equals_rejects_outside_choices_with_a_read_side_hint_not_a_write_only_flag():
    """재리뷰 #1 — `--allow-new-option` 은 `--set` 전용 플래그라 `--where` 에는 존재하지
    않는다. 예전엔 coerce._choice 의 쓰기 경로 힌트를 그대로 재사용해 `Stage=Ofer` 같은
    가장 흔한 오타에 존재하지도 않는 플래그를 권했다 — 재시도해도 100% 같은 실패였다.
    허용 목록(actionable half)은 그대로 유지하고 tail 만 조회에서 실제로 되는 것
    (오타 수정 / templates refresh)으로 바뀌어야 한다."""
    with pytest.raises(ValueError) as e:
        where("Stage=Ofer")
    msg = str(e.value)
    assert "Applied" in msg and "Interview" in msg and "Offer" in msg  # 허용 목록은 유지
    assert "--allow-new-option" not in msg
    assert "templates refresh" in msg


def test_multi_select_contains_rejects_a_value_outside_choices():
    with pytest.raises(ValueError) as e:
        where("Tags contains remte")
    assert "remote" in str(e.value)


# --- 리뷰 #4: checkbox 값은 read/write 공유 파서로 검증(조용한 False 강제 금지) ---

def test_checkbox_rejects_unrecognized_word_instead_of_silently_becoming_false():
    """`Remote=maybe` 가 예전엔 `{"checkbox": {"equals": False}}` 로 조용히 컴파일됐다 —
    `Remote=nope` 와 구분이 안 되는, 확신에 찬 오답. coerce.py 와 같은 메시지를 낸다."""
    with pytest.raises(ValueError) as e:
        where("Remote=maybe")
    assert "maybe" in str(e.value)
    with pytest.raises(ValueError) as e2:
        where("Remote=nope")
    assert "nope" in str(e2.value)


# --- 리뷰 #5: 날짜 비교값은 coerce.parse_date 로 검증·정규화 ---

def test_date_comparison_rejects_unparsable_value_locally():
    """`coerce.parse_date` 를 거치지 않으면 이 값이 Notion 원격 400 으로 터진다 — 이
    패키지의 다른 모든 검증처럼 로컬에서, 에이전트가 자가 수정할 수 있는 메시지로
    잡아야 한다."""
    with pytest.raises(ValueError) as e:
        where("Applied On>7/1/2026")
    assert "7/1/2026" in str(e.value)


def test_date_comparison_normalizes_like_the_write_path():
    """`coerce.parse_date` 를 거치면 unpadded 월/일도 zero-padded 로 정규화된다 — 쓰기
    경로(`--set`)와 같은 포맷으로 나가야 조회→수정→기록 흐름이 자기 출력에 막히지
    않는다."""
    assert where("Applied On>=2026-7-1") == {
        "property": "Applied On", "date": {"on_or_after": "2026-07-01"}}


def test_date_comparison_rejects_range_operand():
    """`..` 범위는 존재/부재를 묻는 게 아니라 "둘 사이"를 묻는 것이라 비교 연산자
    하나의 피연산자가 될 수 없다 — Notion 비교 조건은 스칼라 하나만 받는다."""
    with pytest.raises(ValueError) as e:
        where("Applied On>2026-07-01..2026-07-31")
    assert ".." in str(e.value) or "범위" in str(e.value)
    assert "--where" in str(e.value) or "두 개" in str(e.value)


# --- 리뷰 #6: build_search 는 filterable=False 속성을 대상에서 뺀다 ---

def test_build_search_respects_the_filterable_flag():
    db = _db()
    notes = next(p for p in db["properties"] if p["name"] == "Notes")
    notes["filterable"] = False
    out = filters.build_search(db, "kube")
    assert all(c["property"] != "Notes" for c in out["and"][0]["or"])
    assert any(c["property"] == "Position" for c in out["and"][0]["or"])


# --- 리뷰 #7: build_search(fields=...) 는 find_prop 을 거쳐 오타/비텍스트를 구분한다 ---

def test_build_search_fields_typo_suggests_a_close_name():
    with pytest.raises(ValueError) as e:
        filters.build_search(_db(), "kube", fields=["Positon"])
    assert "Position" in str(e.value)


def test_build_search_fields_non_text_property_gets_a_distinct_message():
    """`Salary` 는 실재하는 속성이지만 텍스트가 아니다 — "텍스트 속성이 하나도 없다"는
    메시지(전체 스캔용)를 재사용하면 거짓이 된다. DB 에는 텍스트 속성이 많다."""
    with pytest.raises(ValueError) as e:
        filters.build_search(_db(), "kube", fields=["Salary"])
    msg = str(e.value)
    assert "Salary" in msg
    assert "텍스트 속성이 없습니다" not in msg


def test_build_search_fields_filterable_false_text_property_gets_its_own_message():
    """재리뷰 #2 — `Notes` 는 rich_text(텍스트 타입)지만 `filterable: False` 다. 예전엔
    "텍스트 속성이 아니라..." 분기로 합쳐져 `` `Notes`(rich_text)은 텍스트 속성이 아니라
    ... rich_text 중에서 고르세요 ``라는 자기모순 메시지가 났다 — 재시도해도 byte-identical
    로 실패한다. filterable 배제는 "타입이 틀렸다"와 다른 문제이므로 별도 메시지가
    필요하다."""
    db = _db()
    notes = next(p for p in db["properties"] if p["name"] == "Notes")
    notes["filterable"] = False
    with pytest.raises(ValueError) as e:
        filters.build_search(db, "kube", fields=["Notes"])
    msg = str(e.value)
    assert "Notes" in msg
    # 예전 메시지(타입 불일치 분기)와 겹치면 안 된다 — rich_text 를 도로 권하는 자기모순.
    assert "텍스트 속성이 아니" not in msg
    assert "rich_text 중에서 고르세요" not in msg


# --- 리뷰 #8: parse_sort 의 3단어+ 거부 메시지가 원인을 설명한다 ---

def test_parse_sort_three_word_name_error_explains_the_fix():
    with pytest.raises(ValueError) as e:
        filters.parse_sort("Date of Application")
    msg = str(e.value)
    assert "세 단어" in msg
    assert "asc" in msg and "desc" in msg


# --- 리뷰 #9: 값을 받는 연산자는 빈 값을 거부한다 ---

def test_value_taking_operators_reject_empty_value():
    with pytest.raises(ValueError) as e:
        where("Notes contains")
    assert "값이 없습니다" in str(e.value)
    with pytest.raises(ValueError):
        where("Notes !contains")
    with pytest.raises(ValueError):
        where("Position starts")
    with pytest.raises(ValueError):
        where("Position ends")
    with pytest.raises(ValueError):
        where("Salary>")
    with pytest.raises(ValueError):
        where("Stage=")


def test_operator_type_mismatch_is_reported_before_the_empty_value_guard():
    """재리뷰 #4 — `Salary starts` 는 값도 없고 연산자도 number 에 못 쓴다(starts 는
    텍스트 전용). 예전엔 빈 값 가드가 타입×연산자 디스패치보다 먼저 돌아 "값이
    없습니다"만 던졌다 — 에이전트가 값을 채워 재시도해야 그제서야 진짜 원인(연산자
    불일치)을 들었다. 두 라운드트립이 필요했던 것이 이제 하나로 끝나야 한다: 연산자
    오류가 먼저, 그리고 빈 값 문구는 아예 나오지 않는다."""
    with pytest.raises(ValueError) as e:
        where("Salary starts")
    msg = str(e.value)
    assert "Salary" in msg and "starts" in msg
    assert "값이 없습니다" not in msg


# --- 리뷰 #10: unique_id 비교는 정수로 나간다 ---

def test_unique_id_comparisons_send_integers_not_strings_or_floats():
    db = _db()
    db["properties"].append(
        {"name": "Ref", "type": "unique_id", "writable": False, "filterable": True})
    out = filters.build_where(db, [filters.parse_where("Ref>10")],
                              resolve_relation=_resolver)
    assert out == {"property": "Ref", "unique_id": {"greater_than": 10}}
    assert isinstance(out["unique_id"]["greater_than"], int)
    out2 = filters.build_where(db, [filters.parse_where("Ref=7")],
                               resolve_relation=_resolver)
    assert out2 == {"property": "Ref", "unique_id": {"equals": 7}}
    assert isinstance(out2["unique_id"]["equals"], int)


# --- 리뷰 #11: _valid_ops 를 _clause 디스패치에 고정 ---

_MATRIX_TYPES = ("title", "rich_text", "url", "email", "phone_number", "number",
                 "checkbox", "date", "created_time", "last_edited_time", "select",
                 "status", "multi_select", "people", "created_by", "last_edited_by",
                 "files", "relation", "formula", "rollup", "unique_id")

_MATRIX_SAMPLE = {
    "title": "x", "rich_text": "x", "url": "https://x.dev", "email": "a@b.c",
    "phone_number": "010-0000-0000", "number": "1", "checkbox": "true",
    "date": "2026-07-01", "created_time": "2026-07-01", "last_edited_time": "2026-07-01",
    "select": "sample", "status": "sample", "multi_select": "sample",
    "people": "u1", "created_by": "u1", "last_edited_by": "u1", "files": "x",
    "relation": "Acme", "formula": "1", "rollup": "1", "unique_id": "1",
}


def _matrix_db():
    props = []
    for t in _MATRIX_TYPES:
        prop = {"name": t, "type": t, "writable": True, "filterable": True}
        if t in ("select", "status", "multi_select"):
            prop["choices"] = ["sample"]
        if t == "relation":
            prop["relates_to"] = "companies"
        props.append(prop)
    return {"key": "matrix", "properties": props}


@pytest.mark.parametrize("ptype", _MATRIX_TYPES)
def test_valid_ops_matches_clause_dispatch_for_every_type(ptype):
    """`_valid_ops(ptype)` 가 말하는 '이 타입에 쓸 수 있는 연산자'와 `_clause` 가 실제로
    받아들이는 연산자가 항상 같아야 한다 — 손으로 든 두 목록이 로직이 바뀔 때 하나만
    바뀌고 거부 메시지가 낡은 정보를 내보내는 걸 전수로 막는다."""
    db = _matrix_db()
    allowed = set(filters._valid_ops(ptype))
    value = _MATRIX_SAMPLE[ptype]
    for op in filters.OPERATORS:
        v = "" if op in filters.NO_VALUE_OPS else value
        try:
            filters._clause(db, ptype, op, v, resolve_relation=_resolver)
        except ValueError as e:
            assert op not in allowed, (
                f"{ptype} {op}: _valid_ops 는 허용한다는데 _clause 가 거부: {e}")
        else:
            assert op in allowed, (
                f"{ptype} {op}: _clause 는 받아들였는데 _valid_ops 는 없다고 한다")
