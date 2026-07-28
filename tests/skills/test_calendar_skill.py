from notionmemory.core.config import Config
from notionmemory.core.skill_base import VALID_KINDS
from notionmemory.skills.calendar.skill import CalendarSkill


def _skill():
    return CalendarSkill(Config({}, ""))


def test_identity_and_requires():
    s = _skill()
    assert (s.id, s.kinds, s.requires) == ("calendar", ("recall", "action"), ["notion"])
    assert set(s.kinds) <= VALID_KINDS


def test_schema_contract():
    schema = _skill().options_schema()
    assert set(schema) == {"parent_page_id", "write_target"}
    field = schema["parent_page_id"]
    assert field["type"] == "str" and field["default"] == ""
    assert not field.get("runtime")  # 대시보드에서 저장 가능해야 함
    assert not any(k for k in schema if "token" in k or "secret" in k)
    wt = schema["write_target"]
    assert wt["type"] == "str" and wt["default"] == ""
    assert not wt.get("runtime")


def test_run_points_to_cli_verbs():
    result = _skill().run({}, lambda *_: None)
    assert result.ok is False
    assert result.message == ("calendar is used as a CLI verb: "
                              "notionmemory calendar list/add/update/cancel")


def test_registered_in_app_registry(tmp_path):
    from notionmemory.app import build_registry
    p = tmp_path / "config.yaml"
    p.write_text("skills: {}\n", encoding="utf-8")
    ids = {c.id for c in build_registry(str(p)).cards()}
    assert "calendar" in ids


def test_declares_usage_and_setup_steps_for_dashboard():
    """대시보드가 'notionmemory run calendar <folder>'라는 틀린 안내를 내지 않도록,
    스킬이 자기 사용법과 Notion Calendar 앱 설정 절차를 직접 선언한다."""
    from notionmemory.skills.calendar.notion_db import SETUP_STEPS
    s = _skill()
    assert s.usage == "notionmemory calendar list/add/update/cancel"
    assert s.setup_steps == SETUP_STEPS
    assert any("default calendar" in step.lower() for step in s.setup_steps)


def test_card_exposes_usage_and_setup_steps(tmp_path):
    from notionmemory.app import build_registry
    p = tmp_path / "config.yaml"
    p.write_text("skills: {}\n", encoding="utf-8")
    card = next(c for c in build_registry(str(p)).cards() if c.id == "calendar")
    assert card.usage.startswith("notionmemory calendar")
    assert card.setup_steps and isinstance(card.setup_steps, list)
