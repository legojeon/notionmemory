import pytest

from notionmemory.core.skill_base import Skill, RunResult, VALID_KINDS


class FakeCapture(Skill):
    id = "fake-capture"
    name = "Fake Capture"
    kinds = ("capture",)
    requires = ["notion"]

    def options_schema(self) -> dict:
        return {"dry_run": {"type": "bool", "default": True}}

    def run(self, options, log) -> RunResult:
        log(f"running with {options}")
        return RunResult(ok=True, message="done")


def test_skill_declares_manifest_fields():
    s = FakeCapture()
    assert s.id == "fake-capture"
    assert set(s.kinds) <= VALID_KINDS
    assert s.requires == ["notion"]
    assert s.options_schema()["dry_run"]["default"] is True


def test_valid_kinds_are_functions_not_skill_names():
    assert VALID_KINDS == {"capture", "recall", "action"}


def test_skill_declares_multiple_kinds():
    class Multi(Skill):
        id, name = "multi", "Multi"
        kinds = ("capture", "recall")
        requires = []
        def options_schema(self): return {}
        def run(self, options, log): return RunResult(True)
    assert set(Multi().kinds) <= VALID_KINDS


def test_skill_run_logs_and_returns_result():
    logs = []
    result = FakeCapture().run({"dry_run": False}, logs.append)
    assert result == RunResult(ok=True, message="done")
    assert logs == ["running with {'dry_run': False}"]


class CoerceSkill(Skill):
    id, name, kinds = "coerce", "Coerce", ("capture",)
    requires = []

    def options_schema(self):
        return {"limit": {"type": "number", "default": 0},
                "flag": {"type": "bool", "default": False},
                "note": {"type": "str", "default": ""},
                "mode": {"type": "select", "default": "auto", "choices": ["auto", "manual"]}}

    def run(self, options, log):
        return RunResult(True)


def test_clean_options_coerces_by_schema():
    s = CoerceSkill()
    out = s.clean_options({"limit": "5", "flag": "on", "note": "x", "unknown": "keep"})
    assert out == {"limit": 5, "flag": True, "note": "x", "unknown": "keep"}


def test_clean_options_drops_empty_strings():
    assert CoerceSkill().clean_options({"note": "", "limit": "3"}) == {"limit": 3}


def test_clean_options_bad_number_raises():
    with pytest.raises(ValueError, match="limit"):
        CoerceSkill().clean_options({"limit": "true"})  # 값 없는 --limit 이 CLI에서 "true"로 들어오는 케이스


def test_clean_options_select_value_in_choices_passes():
    assert CoerceSkill().clean_options({"mode": "manual"}) == {"mode": "manual"}


def test_clean_options_select_rejects_value_outside_choices():
    with pytest.raises(ValueError, match="mode"):
        CoerceSkill().clean_options({"mode": "Manual"})  # 대소문자 오타 등 choices 밖 값


def test_usage_and_setup_steps_default_empty():
    """스킬은 사용법·설정 절차를 선언할 수 있다(대시보드/문서가 소비) — 기본은 비어 있음."""
    s = FakeCapture()
    assert s.usage == "" and s.setup_steps == ()
