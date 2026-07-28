"""출력 경제 — 원본 JSON 금지, row id 필수, 절단은 반드시 눈에 보이게."""
import json

from notionmemory.skills.templates import render


def _page():
    return {"id": "pg_1", "url": "https://notion.so/pg_1", "properties": {
        "Position": {"type": "title", "title": [{"plain_text": "Backend"}]},
        "Notes": {"type": "rich_text", "rich_text": [{"plain_text": "좋은 "},
                                                     {"plain_text": "자리"}]},
        "Salary": {"type": "number", "number": 9000},
        "Remote": {"type": "checkbox", "checkbox": True},
        "Site": {"type": "url", "url": "https://x.dev"},
        "Mail": {"type": "email", "email": "a@b.c"},
        "Tel": {"type": "phone_number", "phone_number": "010"},
        "Applied On": {"type": "date", "date": {"start": "2026-07-22", "end": None}},
        "Window": {"type": "date", "date": {"start": "2026-07-22", "end": "2026-07-25"}},
        "Stage": {"type": "select", "select": {"name": "Offer"}},
        "Status": {"type": "status", "status": {"name": "Doing"}},
        "Tags": {"type": "multi_select", "multi_select": [{"name": "remote"},
                                                          {"name": "senior"}]},
        "Owner": {"type": "people", "people": [{"name": "김철수"}]},
        "Attach": {"type": "files", "files": [{"name": "a.pdf"}]},
        "Company": {"type": "relation", "relation": [{"id": "pg_acme"}]},
        "Days Open": {"type": "formula", "formula": {"type": "number", "number": 31}},
        "Total": {"type": "rollup", "rollup": {"type": "number", "number": 3}},
        "Created": {"type": "created_time", "created_time": "2026-07-01T00:00:00.000Z"},
        "By": {"type": "created_by", "created_by": {"name": "김철수"}},
        "Edited": {"type": "last_edited_time", "last_edited_time": "2026-07-02T00:00:00.000Z"},
        "EditedBy": {"type": "last_edited_by", "last_edited_by": {"name": "이영희"}},
        "Num": {"type": "unique_id", "unique_id": {"prefix": "JOB", "number": 7}},
        "Approve": {"type": "button", "button": {}},
        "Verify": {"type": "verification", "verification": {"state": "verified"}},
    }}


def test_plain_covers_every_type_without_crashing():
    props = _page()["properties"]
    for name, value in props.items():
        assert isinstance(render.plain(value), str), name


def test_plain_values():
    p = _page()["properties"]
    assert render.plain(p["Position"]) == "Backend"
    assert render.plain(p["Notes"]) == "좋은 자리"
    assert render.plain(p["Salary"]) == "9000"
    assert render.plain(p["Remote"]) == "true"
    assert render.plain(p["Applied On"]) == "2026-07-22"
    assert render.plain(p["Window"]) == "2026-07-22..2026-07-25"
    assert render.plain(p["Stage"]) == "Offer"
    assert render.plain(p["Tags"]) == "remote, senior"
    assert render.plain(p["Owner"]) == "김철수"
    assert render.plain(p["Company"]) == "pg_acme"
    assert render.plain(p["Days Open"]) == "31"
    assert render.plain(p["Total"]) == "3"
    assert render.plain(p["Num"]) == "JOB-7"


def test_plain_values_for_previously_indirectly_covered_types():
    # 이 11종은 이전에 "문자열을 내고 안 죽는다"는 블랭킷 테스트로만 커버됐다 —
    # total 이라는 주장을 실제 값으로 뒷받침한다.
    p = _page()["properties"]
    assert render.plain(p["Site"]) == "https://x.dev"
    assert render.plain(p["Mail"]) == "a@b.c"
    assert render.plain(p["Tel"]) == "010"
    assert render.plain(p["Status"]) == "Doing"
    assert render.plain(p["Attach"]) == "a.pdf"
    assert render.plain(p["Created"]) == "2026-07-01T00:00:00.000Z"
    assert render.plain(p["By"]) == "김철수"
    assert render.plain(p["Edited"]) == "2026-07-02T00:00:00.000Z"
    assert render.plain(p["EditedBy"]) == "이영희"
    # button 은 값이라 부를 게 없다 — 표시할 것이 없으므로 빈 문자열이 옳다.
    assert render.plain(p["Approve"]) == ""
    assert render.plain(p["Verify"]) == "verified"


def test_plain_of_an_empty_property_is_empty_string():
    assert render.plain({"type": "select", "select": None}) == ""
    assert render.plain({"type": "number", "number": None}) == ""
    assert render.plain({"type": "rich_text", "rich_text": []}) == ""


def test_plain_of_an_unknown_type_does_not_dump_json():
    out = render.plain({"type": "quantum_flux", "quantum_flux": {"a": [1, 2, 3]}})
    assert "[" not in out and "{" not in out


def test_plain_formula_boolean_result():
    # formula 는 결과 종류가 string/number/boolean/date 넷이다 — boolean 을 못 다루면
    # true/false 결과가 조용히 빈 칸이 된다(Days Open 케이스는 number 만 커버한다).
    prop = {"type": "formula", "formula": {"type": "boolean", "boolean": True}}
    assert render.plain(prop) == "true"
    prop = {"type": "formula", "formula": {"type": "boolean", "boolean": False}}
    assert render.plain(prop) == "false"


def test_plain_formula_string_result():
    prop = {"type": "formula", "formula": {"type": "string", "string": "hi"}}
    assert render.plain(prop) == "hi"


def test_plain_rollup_array_result():
    # rollup type="array" 는 원소가 각각 속성 값 객체다(예: number 목록) — 재귀로
    # 펼쳐야 하고, 안 그러면 집계 목록 전체가 빈 칸이 된다.
    prop = {"type": "rollup", "rollup": {"type": "array", "array": [
        {"type": "number", "number": 5}, {"type": "number", "number": 3}]}}
    assert render.plain(prop) == "5, 3"


def test_plain_unique_id_without_number_does_not_leak_none():
    prop = {"type": "unique_id", "unique_id": {"prefix": "JOB", "number": None}}
    assert "None" not in render.plain(prop)


def test_plain_degrades_instead_of_crashing_on_non_dict_list_items():
    # Notion 실제 응답이 이 모양을 보내지는 않지만, plain() 은 23종 전부에 대해
    # total 이어야 한다 — 방어가 없으면 리스트 원소가 dict 가 아닐 때 AttributeError.
    cases = [
        {"type": "title", "title": ["not-a-dict"]},
        {"type": "rich_text", "rich_text": ["not-a-dict"]},
        {"type": "multi_select", "multi_select": ["not-a-dict"]},
        {"type": "people", "people": ["not-a-dict"]},
        {"type": "files", "files": ["not-a-dict"]},
        {"type": "relation", "relation": ["not-a-dict"]},
    ]
    for prop in cases:
        assert render.plain(prop) == "", prop["type"]


def test_plain_mixed_dict_and_non_dict_list_items_keeps_the_good_ones():
    prop = {"type": "people", "people": [{"name": "김철수"}, "not-a-dict"]}
    assert render.plain(prop) == "김철수"


def test_flatten_always_includes_id():
    row = render.flatten(_page(), ["Position"])
    assert row["id"] == "pg_1"
    assert row["Position"] == "Backend"


def test_flatten_projects_only_requested_names():
    row = render.flatten(_page(), ["Position", "Stage"])
    assert set(row) == {"id", "url", "Position", "Stage"}


def test_flatten_missing_property_becomes_empty_not_keyerror():
    assert render.flatten(_page(), ["NoSuch"])["NoSuch"] == ""


def _page_with_colliding_id_property():
    return {"id": "pg_real_123", "url": "https://real", "properties": {
        "id": {"type": "rich_text", "rich_text": [{"plain_text": "user-typed"}]},
    }}


def _page_with_colliding_url_property():
    return {"id": "pg_real_123", "url": "https://real", "properties": {
        "url": {"type": "rich_text", "rich_text": [{"plain_text": "user-typed-url"}]},
    }}


def test_flatten_user_property_named_id_does_not_clobber_real_page_id():
    row = render.flatten(_page_with_colliding_id_property(), ["id"])
    assert row["id"] == "pg_real_123"
    assert row["url"] == "https://real"
    # 사용자의 동명 속성 값은 버리지 않고 충돌 없는 키로 옮겨 보존한다.
    assert row["id (property)"] == "user-typed"


def test_flatten_user_property_named_url_does_not_clobber_real_page_url():
    row = render.flatten(_page_with_colliding_url_property(), ["url"])
    assert row["id"] == "pg_real_123"
    assert row["url"] == "https://real"
    assert row["url (property)"] == "user-typed-url"


def test_flatten_colliding_name_requested_alongside_other_fields():
    page = _page_with_colliding_id_property()
    page["properties"]["Position"] = {"type": "title", "title": [{"plain_text": "Backend"}]}
    row = render.flatten(page, ["id", "Position"])
    assert row["id"] == "pg_real_123"
    assert row["id (property)"] == "user-typed"
    assert row["Position"] == "Backend"


def test_render_rows_puts_id_first_even_if_not_requested():
    out = render.render_rows([render.flatten(_page(), ["Position"])], ["Position"])
    header = out.splitlines()[0]
    assert header.split()[0] == "id"


def test_render_rows_pads_korean_by_display_width_not_codepoints():
    # "김철수" 는 코드포인트 3개지만 터미널에서 폭 6(East Asian Wide)을 차지한다.
    # ljust 는 코드포인트로 세므로 "Owner"(폭5)보다 좁게 잡혀 정렬이 깨진다.
    rows = [{"id": "p1", "Owner": "김철수"}, {"id": "p2", "Owner": "Bob"}]
    out = render.render_rows(rows, ["Owner"])
    header, row1, row2 = out.splitlines()
    assert header == "id  Owner "
    assert row1 == "p1  김철수"
    assert row2 == "p2  Bob   "


def test_render_rows_empty_says_so():
    assert "결과 없음" in render.render_rows([], ["Position"])


def test_render_json_is_flat_and_parses():
    rows = [render.flatten(_page(), ["Position", "Salary"])]
    parsed = json.loads(render.render_json(rows))
    assert parsed[0]["id"] == "pg_1"
    assert parsed[0]["Salary"] == "9000"
    assert all(isinstance(v, str) for k, v in parsed[0].items())


def test_truncation_note_is_empty_when_nothing_was_cut():
    assert render.truncation_note(capped=False, cap=1000, sorted_=True) == ""


def test_truncation_note_names_the_cap():
    note = render.truncation_note(capped=True, cap=1000, sorted_=True)
    assert "1000" in note and "좁히" in note


def test_arbitrary_order_warning_when_cut_without_sort():
    note = render.truncation_note(capped=True, cap=25, sorted_=False)
    assert "임의 순서" in note


def test_truncation_note_stalled_does_not_blame_the_users_filter():
    """서버 정체는 조건 문제가 아니다 — "조건을 좁히세요"라고 하면 사용자가 존재하지도
    않는 원인을 탓하게 된다."""
    note = render.truncation_note(capped=True, cap=1000, sorted_=True, stalled=True)
    assert "좁히" not in note
    assert "불완전" in note


def test_truncation_note_stalled_wins_over_capped():
    """`_fetch` 가 cap 근처에도 못 갔는데 `capped=True` 를 잘못 넘기더라도, `stalled`
    가 실제 원인이면 그 말을 한다 — cap 메시지가 정체 상황을 덮어써서는 안 된다."""
    note = render.truncation_note(capped=False, cap=1000, sorted_=True, stalled=True)
    assert "1000" not in note
    assert "불완전" in note
