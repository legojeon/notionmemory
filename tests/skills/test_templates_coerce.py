"""값 강제 레이어 — 테스트 무게중심(스펙 §11).

Notion 이 안 막아주는 것을 여기서 막는다: select 는 목록 밖 값에 200 + 새 옵션 생성으로
답한다. 아무도 에러를 못 보고 사용자 보드 뷰만 쪼개진다.
"""
import pytest

from notionmemory.skills.templates import coerce


def _db():
    return {"key": "applications", "title_property": "Position", "properties": [
        {"name": "Position", "type": "title", "writable": True, "filterable": True},
        {"name": "Notes", "type": "rich_text", "writable": True, "filterable": True},
        {"name": "Salary", "type": "number", "writable": True, "filterable": True},
        {"name": "Remote", "type": "checkbox", "writable": True, "filterable": True},
        {"name": "Site", "type": "url", "writable": True, "filterable": True},
        {"name": "Mail", "type": "email", "writable": True, "filterable": True},
        {"name": "Tel", "type": "phone_number", "writable": True, "filterable": True},
        {"name": "Applied On", "type": "date", "writable": True, "filterable": True},
        {"name": "Stage", "type": "select", "writable": True, "filterable": True,
         "choices": ["Applied", "Interview", "Offer"]},
        {"name": "Status", "type": "status", "writable": True, "filterable": True,
         "choices": ["Todo", "Doing", "Done"]},
        {"name": "Tags", "type": "multi_select", "writable": True, "filterable": True,
         "choices": ["remote", "senior"]},
        {"name": "Owner", "type": "people", "writable": True, "filterable": True},
        {"name": "Attach", "type": "files", "writable": True, "filterable": True},
        {"name": "Company", "type": "relation", "writable": True, "filterable": True,
         "relates_to": "companies"},
        {"name": "Orphan", "type": "relation", "writable": True, "filterable": True,
         "relates_to": None},
        {"name": "Days Open", "type": "formula", "writable": False, "filterable": True},
        {"name": "Approve", "type": "button", "writable": False, "filterable": False},
        {"name": "Weird", "type": "quantum_flux", "writable": False, "filterable": False},
    ]}


def _resolver(mapping=None):
    table = mapping if mapping is not None else {("companies", "Acme"): "pg_acme"}

    def resolve(key, title):
        try:
            return table[(key, title)]
        except KeyError:
            raise ValueError(f"'{key}'에서 '{title}'를 찾지 못했습니다")
    return resolve


def build(*pairs, allow_new_option=False, resolver=None):
    return coerce.build_properties(_db(), list(pairs),
                                   resolve_relation=resolver or _resolver(),
                                   allow_new_option=allow_new_option)


# --- 파싱 ---

def test_parse_set_splits_on_first_equals_only():
    assert coerce.parse_set("Notes=a=b=c") == ("Notes", "a=b=c")


def test_parse_set_strips_property_name_but_not_value():
    assert coerce.parse_set(" Stage = Applied") == ("Stage", " Applied")


def test_parse_set_without_equals_is_rejected():
    with pytest.raises(ValueError) as e:
        coerce.parse_set("Stage")
    assert "P=V" in str(e.value)


# --- 정상 변환 ---

def test_title_and_rich_text():
    out = build(("Position", "Backend Engineer"), ("Notes", "좋은 자리"))
    assert out["Position"] == {"title": [{"text": {"content": "Backend Engineer"}}]}
    assert out["Notes"] == {"rich_text": [{"text": {"content": "좋은 자리"}}]}


def test_rich_text_is_truncated_at_notion_limit():
    out = build(("Notes", "가" * 2500))
    assert len(out["Notes"]["rich_text"][0]["text"]["content"]) == 2000


def test_number_accepts_int_and_float():
    assert build(("Salary", "9000"))["Salary"] == {"number": 9000.0}
    assert build(("Salary", "1.5"))["Salary"] == {"number": 1.5}


def test_checkbox_truthy_words():
    for word in ("1", "true", "TRUE", "on", "yes"):
        assert build(("Remote", word))["Remote"] == {"checkbox": True}
    for word in ("0", "false", "no", "off"):
        assert build(("Remote", word))["Remote"] == {"checkbox": False}


def test_checkbox_empty_value_clears_to_false_not_none():
    """checkbox 는 Notion 에서 nullable 이 아니다 — 다른 타입들처럼 빈 값이 None 으로
    지워지는 게 아니라 False 자체가 "지워진" 상태다. 다음 사람이 이걸 일관성을 이유로
    None 으로 "고치면" Notion 이 400 을 낸다."""
    assert build(("Remote", ""))["Remote"] == {"checkbox": False}


def test_scalar_text_types_pass_through():
    out = build(("Site", "https://x.dev"), ("Mail", "a@b.c"), ("Tel", "010-0000-0000"))
    assert out["Site"] == {"url": "https://x.dev"}
    assert out["Mail"] == {"email": "a@b.c"}
    assert out["Tel"] == {"phone_number": "010-0000-0000"}


def test_empty_value_clears_a_scalar_property():
    """`--set "Site="` 는 링크 제거다 — calendar update 의 `--link ""` 와 같은 규약."""
    assert build(("Site", ""))["Site"] == {"url": None}


def test_date_accepts_day_and_minute_and_range():
    assert build(("Applied On", "2026-07-22"))["Applied On"] == {"date": {"start": "2026-07-22"}}
    assert build(("Applied On", "2026-07-22 14:30"))["Applied On"] == {
        "date": {"start": "2026-07-22T14:30:00"}}
    assert build(("Applied On", "2026-07-22..2026-07-25"))["Applied On"] == {
        "date": {"start": "2026-07-22", "end": "2026-07-25"}}


def test_select_and_status_and_multi_select_within_choices():
    assert build(("Stage", "Interview"))["Stage"] == {"select": {"name": "Interview"}}
    assert build(("Status", "Doing"))["Status"] == {"status": {"name": "Doing"}}
    assert build(("Tags", "remote, senior"))["Tags"] == {
        "multi_select": [{"name": "remote"}, {"name": "senior"}]}


def test_select_and_status_strip_surrounding_whitespace():
    """multi_select/people/files/relation 은 이미 쉼표 분리 값을 strip 한다 — select/status
    도 같은 대우를 받아야 `--set "Stage = Applied"` 가 목록 안 값으로 인식된다."""
    assert build(("Stage", " Applied "))["Stage"] == {"select": {"name": "Applied"}}
    assert build(("Status", " Todo "))["Status"] == {"status": {"name": "Todo"}}


def test_empty_value_clears_number():
    """number 도 url/email/phone_number/date 와 같은 "빈 값 = 지우기" 규약을 따른다 —
    이전에는 float('') 이 실패해 '숫자여야 합니다' 라는, 지우려는 의도와 무관한 오류를 냈다."""
    assert build(("Salary", ""))["Salary"] == {"number": None}


def test_empty_value_clears_select():
    assert build(("Stage", ""))["Stage"] == {"select": None}


def test_empty_value_clears_status():
    assert build(("Status", ""))["Status"] == {"status": None}


def test_whitespace_only_value_clears_like_empty_for_the_clearable_types():
    """select/status 는 이미 strip 후 비교해 공백만 있는 값도 지우기로 처리한다.
    number/url/email/phone_number/date 는 예전에 정확히 `""` 만 비교해서
    `--set "Salary =  "` 가 "숫자여야 합니다" 같은, 지우려는 의도와 무관한 오류를
    냈다 — 지워지는 쪽으로 통일한다."""
    assert build(("Salary", "  "))["Salary"] == {"number": None}
    assert build(("Site", "  "))["Site"] == {"url": None}
    assert build(("Mail", "  "))["Mail"] == {"email": None}
    assert build(("Tel", "  "))["Tel"] == {"phone_number": None}
    assert build(("Applied On", "  "))["Applied On"] == {"date": None}
    assert build(("Stage", "  "))["Stage"] == {"select": None}
    assert build(("Status", "  "))["Status"] == {"status": None}


def test_whitespace_only_value_does_not_clear_title_or_rich_text():
    """title/rich_text 는 자유 텍스트라 공백도 값으로 보존한다 — 지우기 규약이
    적용되는 스칼라/select/number/date 집합과는 다르다."""
    out = build(("Position", "  "), ("Notes", "  "))
    assert out["Position"] == {"title": [{"text": {"content": "  "}}]}
    assert out["Notes"] == {"rich_text": [{"text": {"content": "  "}}]}


def test_number_rejects_non_finite_values():
    """float() 은 nan/inf 를 받아주지만 json.dumps 가 그걸 유효하지 않은 bare NaN/Infinity
    로 뱉어 Notion 에서 불투명한 400 이 된다 — 로컬에서 의미 있는 메시지로 막는다."""
    for word in ("nan", "inf", "-inf", "Infinity"):
        with pytest.raises(ValueError) as e:
            build(("Salary", word))
        assert word in str(e.value)


def test_checkbox_rejects_invalid_word():
    with pytest.raises(ValueError) as e:
        build(("Remote", "maybe"))
    assert "maybe" in str(e.value)


def test_parse_bool_rejects_none_instead_of_silently_becoming_false():
    """재리뷰 #3 — 추출 전 인라인 버전은 `value.strip()` 을 직접 호출했으니 `None` 은
    AttributeError 로 즉시 드러났다. 추출하며 `(value or "")` 로 바꾸는 바람에 `None`
    이 "" 를 거쳐 `_FALSE` 에 걸려 조용히 `False` 가 됐다 — 이 함수 자체가 "모호한
    참/거짓을 조용히 False 로 삼키지 않는다"는 목적으로 존재하는데, 추출이 정확히 그
    실패 모드를 새로 만든 것. 잘못된 단어와 같은 ValueError 로 걸려야 한다."""
    with pytest.raises(ValueError) as e:
        coerce.parse_bool("Remote", None)
    assert "참/거짓" in str(e.value)


def test_people_accepts_comma_separated_ids():
    ids = ["6c8a1f2e-0000-4000-8000-000000000000", "6c8a1f2e-0000-4000-8000-000000000001"]
    out = build(("Owner", ", ".join(ids)))
    assert out["Owner"] == {"people": [{"id": ids[0]}, {"id": ids[1]}]}


def test_files_accepts_comma_separated_urls():
    out = build(("Attach", "https://x.dev/a.pdf, https://x.dev/b.pdf"))
    assert out["Attach"] == {"files": [
        {"name": "a.pdf", "external": {"url": "https://x.dev/a.pdf"}},
        {"name": "b.pdf", "external": {"url": "https://x.dev/b.pdf"}}]}


def test_relation_accepts_comma_separated_titles():
    resolver = _resolver({("companies", "Acme"): "pg_acme", ("companies", "Beta"): "pg_beta"})
    out = build(("Company", "Acme, Beta"), resolver=resolver)
    assert out["Company"] == {"relation": [{"id": "pg_acme"}, {"id": "pg_beta"}]}


def test_people_rejects_partially_hyphenated_ids():
    """`6c8a1f2e00004000-8000-000000000000` 처럼 하이픈이 일부만 있으면 로컬 정규식은
    통과시키고 Notion 에서만 400 이 났던 구멍 — 하이픈은 전부 있거나 전부 없거나여야 한다."""
    with pytest.raises(ValueError) as e:
        build(("Owner", "6c8a1f2e00004000-8000-000000000000"))
    assert "사용자 ID" in str(e.value)


def test_people_accepts_ids_without_any_hyphens():
    uuid = "6c8a1f2e-0000-4000-8000-000000000000"
    bare = uuid.replace("-", "")
    assert build(("Owner", bare))["Owner"] == {"people": [{"id": bare}]}


def test_date_reparses_its_own_emitted_format():
    """읽고-고치고-쓰는 흐름: parse_date 가 내보내는 형식을 다시 입력으로 넣어도 막히면
    안 된다."""
    assert build(("Applied On", "2026-07-22T14:30:00"))["Applied On"] == {
        "date": {"start": "2026-07-22T14:30:00"}}


def test_date_accepts_notion_timezone_suffixes():
    """Notion 조회 응답은 `+09:00` 오프셋이나 `Z` 를 붙여 값을 돌려준다 — 그걸 그대로
    다시 --set 에 넣어도 받아들이되, 출력 형식(타임존 없음)은 그대로 유지한다."""
    assert build(("Applied On", "2026-07-22T14:30:00+09:00"))["Applied On"] == {
        "date": {"start": "2026-07-22T14:30:00"}}
    assert build(("Applied On", "2026-07-22T14:30:00Z"))["Applied On"] == {
        "date": {"start": "2026-07-22T14:30:00"}}


def test_date_normalizes_unpadded_month_and_day():
    """strptime 은 zero-padding 을 강제하지 않아 `2026-7-2` 도 `%Y-%m-%d` 로 파싱된다 —
    예전엔 그 원본 문자열을 그대로 돌려줘서 로컬 검증은 통과하고 Notion(ISO 8601 요구)
    이 나중에 400 을 냈다. 지금은 파싱한 뒤 항상 zero-padded 형태로 재emit 해야 한다."""
    assert build(("Applied On", "2026-7-2"))["Applied On"] == {"date": {"start": "2026-07-02"}}
    assert build(("Applied On", "2026-07-2"))["Applied On"] == {"date": {"start": "2026-07-02"}}
    assert build(("Applied On", "2026-7-2..2026-7-9"))["Applied On"] == {
        "date": {"start": "2026-07-02", "end": "2026-07-09"}}


def test_empty_choices_list_or_missing_key_passes_value_through_unvalidated():
    """choices 를 못 읽은(또는 빈 목록인) 속성은 막을 근거가 없어 무검증 통과한다 —
    이건 의도된 동작이라 문서화해두지 않으면 다음 사람이 회귀로 오인하기 쉽다."""
    db = _db()
    prop = next(p for p in db["properties"] if p["name"] == "Stage")
    prop["choices"] = []
    out = coerce.build_properties(db, [("Stage", "Anything")], resolve_relation=_resolver())
    assert out["Stage"] == {"select": {"name": "Anything"}}

    del prop["choices"]
    out2 = coerce.build_properties(db, [("Stage", "Anything")], resolve_relation=_resolver())
    assert out2["Stage"] == {"select": {"name": "Anything"}}


def test_choice_validation_rejects_an_unnormalized_profile_with_options_but_no_choices():
    """이 레이어는 `choices` 만 읽는다. Notion 자신은 이 목록을 `select.options` 라고
    부른다 — 스키마 페처(아직 없는 후속 태스크)가 그 원래 이름 그대로 `options` 만
    채우고 `choices` 로 정규화하지 않으면, 과거에는 여기가 조용히 무검증 통과로
    빠졌다(회귀). 지금은 이 mis-shaped 프로필 자체를 즉시 거부해야 한다 — 통과하면
    안 되는 값을 걸러내는 게 아니라, 애초에 검증 불가능한 상태라고 에이전트에게
    알려야 한다."""
    db = _db()
    prop = next(p for p in db["properties"] if p["name"] == "Stage")
    del prop["choices"]
    prop["options"] = ["Applied", "Interview", "Offer"]   # Notion 이 실제로 부르는 이름
    with pytest.raises(ValueError) as e:
        coerce.build_properties(db, [("Stage", "Interview")], resolve_relation=_resolver())
    msg = str(e.value)
    assert "정규화" in msg
    assert "choices" in msg and "options" in msg


def test_choice_validation_accepts_notion_shaped_option_dicts_in_choices():
    """프로듀서가 `choices` 로는 정규화했지만 Notion 원본 옵션 배열의 항목 형태
    (`{"name": "Interview"}`)를 그대로 복사해오는 경우 — 문자열이 아니라 dict 가
    섞여 들어오면 예전에는 `', '.join(choices)` 에서 TypeError 가 나 조용한 실패
    금지 원칙(bare traceback 금지)을 어겼다. 지금은 정상적으로 검증하고, 목록 밖
    값이면 ValueError 로 거부한다."""
    db = _db()
    prop = next(p for p in db["properties"] if p["name"] == "Stage")
    prop["choices"] = [{"name": "Applied"}, {"name": "Interview"}, {"name": "Offer"}]
    out = coerce.build_properties(db, [("Stage", "Interview")], resolve_relation=_resolver())
    assert out["Stage"] == {"select": {"name": "Interview"}}

    with pytest.raises(ValueError) as e:
        coerce.build_properties(db, [("Stage", "NotInList")], resolve_relation=_resolver())
    msg = str(e.value)
    assert "Applied" in msg and "Interview" in msg and "Offer" in msg


def test_files_become_external_urls():
    assert build(("Attach", "https://x.dev/a.pdf"))["Attach"] == {
        "files": [{"name": "a.pdf", "external": {"url": "https://x.dev/a.pdf"}}]}


def test_relation_resolves_title_to_page_id():
    assert build(("Company", "Acme"))["Company"] == {"relation": [{"id": "pg_acme"}]}


# --- 거부: 이것이 이 레이어의 존재 이유다 ---

def test_unknown_property_suggests_a_close_name():
    with pytest.raises(ValueError) as e:
        build(("Staus", "Doing"))
    assert "Status" in str(e.value)


def test_read_only_property_is_rejected_with_its_type():
    with pytest.raises(ValueError) as e:
        build(("Days Open", "30"))
    msg = str(e.value)
    assert "Days Open" in msg and "formula" in msg


def test_unknown_type_is_rejected_by_the_writable_gate():
    """`_value_json` 마지막의 `raise` 는 사실 도달 불가능하다 — 쓰기 가능한 타입은 전부
    분기가 있고, `quantum_flux` 처럼 쓰기 불가 타입은 `build_properties` 의 writable
    게이트에서 먼저 걸린다. 이 테스트가 실제로 exercise 하는 건 그 게이트다."""
    with pytest.raises(ValueError) as e:
        build(("Weird", "x"))
    assert "Weird" in str(e.value)


def test_select_value_outside_choices_lists_the_whole_allowlist():
    with pytest.raises(ValueError) as e:
        build(("Stage", "Interviewing"))
    msg = str(e.value)
    assert "Applied" in msg and "Interview" in msg and "Offer" in msg


def test_allow_new_option_lets_select_and_multi_select_through():
    assert build(("Stage", "Screening"), allow_new_option=True)["Stage"] == {
        "select": {"name": "Screening"}}
    assert build(("Tags", "urgent"), allow_new_option=True)["Tags"] == {
        "multi_select": [{"name": "urgent"}]}


def test_allow_new_option_does_not_apply_to_status():
    """status 는 API 가 옵션 생성을 허용하지 않아 어차피 400 이다 — 로컬에서 막는 편이
    메시지가 명확하다(스펙 §5 비대칭). 메시지 자체도 select/multi_select 처럼
    `--allow-new-option` 을 광고하면 안 된다 — 그 플래그는 status 에 안 먹히므로,
    권하면 에이전트가 똑같이 실패할 재시도에 라운드트립을 태운다."""
    with pytest.raises(ValueError) as e:
        build(("Status", "Blocked"), allow_new_option=True)
    msg = str(e.value)
    assert "Todo" in msg
    assert "--allow-new-option" not in msg
    assert "Notion" in msg and "옵션" in msg


def test_allow_new_option_hint_is_present_for_select_and_multi_select():
    """select/multi_select 는 status 와 반대로 `--allow-new-option` 힌트를 그대로
    유지해야 한다 — 실제로 그 플래그가 먹히기 때문이다."""
    with pytest.raises(ValueError) as e:
        build(("Stage", "Interviewing"))
    assert "--allow-new-option" in str(e.value)
    with pytest.raises(ValueError) as e:
        build(("Tags", "urgent"))
    assert "--allow-new-option" in str(e.value)


def test_number_rejects_non_numeric_showing_the_value():
    with pytest.raises(ValueError) as e:
        build(("Salary", "많이"))
    assert "많이" in str(e.value)


def test_date_rejects_unparsable_value():
    with pytest.raises(ValueError) as e:
        build(("Applied On", "다음 주 화요일"))
    assert "다음 주 화요일" in str(e.value)


def test_relation_miss_propagates_resolver_message():
    with pytest.raises(ValueError) as e:
        build(("Company", "NoSuchCo"))
    assert "NoSuchCo" in str(e.value)


def test_relation_without_relates_to_is_rejected_by_the_relates_to_guard():
    """`Orphan` 픽스처는 `"writable": True` 다 — writable 게이트는 통과한다. 거부는
    `_value_json` 의 relation 분기 안, `relates_to` 가 없다는 별도 가드에서 일어난다
    (템플릿 밖 DB 를 가리키는 relation 은 resolve 할 대상이 없다, 스펙 §3)."""
    with pytest.raises(ValueError) as e:
        build(("Orphan", "Acme"))
    assert "Orphan" in str(e.value)


def test_people_requires_user_ids_not_names():
    ok = build(("Owner", "6c8a1f2e-0000-4000-8000-000000000000"))
    assert ok["Owner"] == {"people": [{"id": "6c8a1f2e-0000-4000-8000-000000000000"}]}
    with pytest.raises(ValueError) as e:
        build(("Owner", "김철수"))
    assert "사용자 ID" in str(e.value)


def test_duplicate_property_in_one_call_is_rejected():
    with pytest.raises(ValueError) as e:
        build(("Stage", "Applied"), ("Stage", "Offer"))
    assert "Stage" in str(e.value)
