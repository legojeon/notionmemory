"""공백 붙은 속성 이름 도달성 — 실사용 버그(to-do-kanban-board 의 `마감일 `).

Notion 스키마엔 끝공백 붙은 속성 이름이 흔한데(공유 템플릿 복제 등) `parse_set`/
`--fields`/`--where` 파싱은 이름을 strip 하므로 정확 일치로는 절대 도달할 수 없었다.
계약: `find_prop` 은 정확 일치 우선 → 실패 시 양쪽 strip 비교로 **유일** 매칭이면 그
속성을 돌려주고, 페이로드를 만드는 호출부는 사용자가 친 이름이 아니라 **캐노니컬
이름(`prop["name"]`)** 을 키로 쓴다(안 그러면 로컬 검증은 통과하고 Notion 만 400)."""
import pytest

from notionmemory.skills.templates import coerce, filters
from notionmemory.skills.templates import profile as P


def _db():
    return {"key": "kanban", "title_property": "이름", "properties": [
        {"name": "이름", "type": "title", "writable": True, "filterable": True},
        {"name": "마감일 ", "type": "date", "writable": True, "filterable": True},
        {"name": "상태", "type": "select", "writable": True, "filterable": True,
         "choices": ["할 일", "진행 중", "완료"]},
    ]}


# --- find_prop 폴백 ---

def test_find_prop_reaches_trailing_space_name_via_stripped_match():
    prop = P.find_prop(_db(), "마감일")
    assert prop["name"] == "마감일 "        # 캐노니컬(공백 포함)을 그대로 돌려준다
    assert prop["type"] == "date"


def test_find_prop_exact_match_still_wins_over_stripped():
    db = _db()
    db["properties"].append(
        {"name": "마감일", "type": "rich_text", "writable": True, "filterable": True})
    assert P.find_prop(db, "마감일")["type"] == "rich_text"      # 정확 일치 우선
    assert P.find_prop(db, "마감일 ")["type"] == "date"          # 공백 포함도 정확 일치


def test_find_prop_ambiguous_stripped_match_is_rejected_not_guessed():
    db = _db()
    db["properties"].append(
        {"name": " 마감일", "type": "rich_text", "writable": True, "filterable": True})
    with pytest.raises(ValueError):
        P.find_prop(db, "마감일")           # "마감일 " vs " 마감일" — 추측하지 않는다


def test_find_prop_unknown_name_error_is_unchanged():
    with pytest.raises(ValueError) as e:
        P.find_prop(_db(), "업어짐")
    assert "refresh" in str(e.value)


# --- 페이로드 키 = 캐노니컬 이름 ---

def test_build_properties_payload_key_is_canonical_name():
    out = coerce.build_properties(_db(), [("마감일", "2026-08-01")],
                                  resolve_relation=lambda k, t: t)
    assert "마감일 " in out and "마감일" not in out
    assert out["마감일 "]["date"] == {"start": "2026-08-01"}


def test_build_properties_duplicate_check_sees_through_whitespace():
    with pytest.raises(ValueError):
        coerce.build_properties(_db(), [("마감일", "2026-08-01"), ("마감일 ", "2026-08-02")],
                                resolve_relation=lambda k, t: t)


def test_where_clause_property_is_canonical_name():
    out = filters.build_where(_db(), [filters.parse_where("마감일 > 2026-08-01")],
                              resolve_relation=lambda k, t: t)
    assert out["property"] == "마감일 "


def test_sort_property_is_canonical_name():
    payload = filters.compile_query(_db(), wheres=[], search="",
                                    sorts=[filters.parse_sort("마감일 asc")],
                                    resolve_relation=lambda k, t: t)
    assert payload["sorts"][0]["property"] == "마감일 "


# --- 옵션 값(choices) 의 공백 — 속성 이름과 같은 부류, 더 위험(불일치 시 select 는
# 400 이 아니라 조용히 새 옵션을 만들어 보드를 쪼갠다) ---

def _db_spacey_choices():
    return {"key": "kanban", "title_property": "이름", "properties": [
        {"name": "이름", "type": "title", "writable": True, "filterable": True},
        {"name": "상태", "type": "select", "writable": True, "filterable": True,
         "choices": ["할 일", "진행 중", "완료 "]},          # ← 끝공백 옵션
        {"name": "단계", "type": "status", "writable": True, "filterable": True,
         "choices": ["시작 ", "끝"]},
    ]}


def test_select_value_reaches_trailing_space_option_as_canonical():
    out = coerce.build_properties(_db_spacey_choices(), [("상태", "완료")],
                                  resolve_relation=lambda k, t: t)
    # 캐노니컬 옵션명("완료 ")으로 실어야 기존 옵션에 붙는다 — "완료" 로 보내면
    # select 는 조용히 새 옵션을 만든다(silent split).
    assert out["상태"]["select"]["name"] == "완료 "


def test_select_allow_new_still_prefers_existing_stripped_match():
    out = coerce.build_properties(_db_spacey_choices(), [("상태", "완료")],
                                  resolve_relation=lambda k, t: t,
                                  allow_new_option=True)
    assert out["상태"]["select"]["name"] == "완료 "   # 새 옵션 생성보다 기존 매칭 우선


def test_status_value_reaches_trailing_space_option():
    out = coerce.build_properties(_db_spacey_choices(), [("단계", "시작")],
                                  resolve_relation=lambda k, t: t)
    assert out["단계"]["status"]["name"] == "시작 "


def test_where_filter_value_is_canonicalized_too():
    # 필터 값이 raw 로 나가면 equals 가 아무것도 못 찾아 조용히 0건이 된다.
    out = filters.build_where(_db_spacey_choices(), [filters.parse_where("상태=완료")],
                              resolve_relation=lambda k, t: t)
    assert out["select"]["equals"] == "완료 "


def test_choice_exact_match_still_wins():
    db = _db_spacey_choices()
    db["properties"][1]["choices"] = ["완료", "완료 "]     # 정확 일치가 있으면 그걸
    out = coerce.build_properties(db, [("상태", "완료")],
                                  resolve_relation=lambda k, t: t)
    assert out["상태"]["select"]["name"] == "완료"


def test_choice_unknown_value_error_unchanged():
    with pytest.raises(ValueError) as e:
        coerce.build_properties(_db_spacey_choices(), [("상태", "없는값")],
                                resolve_relation=lambda k, t: t)
    assert "허용" in str(e.value)


# --- NFC/NFD — 공백과 같은 부류(화면엔 동일, 바이트는 불일치) ---

def test_find_prop_matches_nfd_input_against_nfc_schema():
    import unicodedata
    nfd = unicodedata.normalize("NFD", "마감일")
    assert P.find_prop(_db(), nfd)["name"] == "마감일 "


def test_choice_matches_nfd_value_against_nfc_option():
    import unicodedata
    nfd = unicodedata.normalize("NFD", "완료")
    out = coerce.build_properties(_db_spacey_choices(), [("상태", nfd)],
                                  resolve_relation=lambda k, t: t)
    assert out["상태"]["select"]["name"] == "완료 "
