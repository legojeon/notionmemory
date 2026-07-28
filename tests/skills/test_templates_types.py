"""속성 타입 표 — 이 스킬이 성립하는 유일한 근거(스펙 §5 '타입은 닫힌 집합')."""
from notionmemory.skills.templates import types


def test_exactly_twenty_three_types():
    assert len(types.PROP_TYPES) == 23


def test_fourteen_writable_types():
    assert types.WRITABLE == frozenset({
        "title", "rich_text", "number", "checkbox", "url", "email", "phone_number",
        "date", "select", "multi_select", "status", "people", "files", "relation"})


def test_nine_read_only_types_are_not_writable():
    read_only = {"formula", "rollup", "created_time", "created_by", "last_edited_time",
                 "last_edited_by", "unique_id", "button", "verification"}
    for name in read_only:
        assert types.flags(name).writable is False, name


def test_read_only_does_not_mean_unfilterable():
    """formula/rollup 은 쓰기 불가지만 필터 가능 — 한 축으로 접으면
    '30일 넘게 열린 지원 보여줘'가 통째로 막힌다(스펙 §3)."""
    for name in ("formula", "rollup", "created_time", "unique_id", "last_edited_time"):
        assert types.flags(name).writable is False, name
        assert types.flags(name).filterable is True, name


def test_button_and_verification_are_neither():
    for name in ("button", "verification"):
        assert types.flags(name).writable is False
        assert types.flags(name).filterable is False


def test_unknown_type_is_demoted_to_both_false():
    """Notion 이 새 타입을 추가해도 쓰거나 필터하다 깨지지 않는다."""
    f = types.flags("quantum_flux")
    assert f.writable is False and f.filterable is False and f.capability == ""


def test_capability_mapping():
    assert types.flags("date").capability == "date"
    assert types.flags("created_time").capability == "date"
    assert types.flags("title").capability == "text"
    assert types.flags("rich_text").capability == "text"
    assert types.flags("people").capability == "people"
    assert types.flags("last_edited_by").capability == "people"
    assert types.flags("url").capability == "link"
    assert types.flags("files").capability == "link"
    assert types.flags("number").capability == ""


def test_derive_capabilities_is_a_sorted_union_over_databases():
    dbs = [{"properties": [{"name": "Name", "type": "title"},
                           {"name": "Due", "type": "date"}]},
           {"properties": [{"name": "Site", "type": "url"},
                           {"name": "N", "type": "number"}]}]
    assert types.derive_capabilities(dbs) == ["date", "link", "text"]


def test_derive_capabilities_empty_when_nothing_matches():
    assert types.derive_capabilities([{"properties": [{"name": "N", "type": "number"}]}]) == []
    assert types.derive_capabilities([]) == []
