from notionmemory.core.config import Config
from notionmemory.core.skill_base import VALID_KINDS
from notionmemory.skills.memory.skill import MemorySkill


def _skill():
    return MemorySkill(Config({}, ""))


def test_identity_and_requires():
    s = _skill()
    assert (s.id, s.kinds, s.requires) == ("memory", ("capture", "recall"), ["notion"])
    assert set(s.kinds) <= VALID_KINDS


def test_schema_contract():
    schema = _skill().options_schema()
    assert schema["capture_mode"]["type"] == "select"
    assert schema["capture_mode"]["default"] == "auto"
    assert schema["capture_mode"]["choices"] == ["auto", "manual"]
    assert "--auto" in schema["capture_mode"]["help"]
    assert schema["top_n"]["type"] == "number" and schema["top_n"]["default"] == 5
    assert schema["default_project"]["type"] == "str"
    assert schema["default_project"]["default"] == ""
    # 토큰 방벽: 시크릿 키가 스키마에 없어야 한다
    assert not any(k for k in schema if "token" in k or "secret" in k)
    # 전부 persistent (runtime 옵션 없음 — 실행은 CLI verb)
    assert not any(f.get("runtime") for f in schema.values())


def test_run_points_to_cli_verbs():
    result = _skill().run({}, lambda *_: None)
    assert result.ok is False
    assert result.message == "memory is used as a CLI verb: notionmemory remember/recall/forget"


def test_options_schema_exposes_parent_page_id():
    schema = MemorySkill(Config({})).options_schema()
    field = schema["parent_page_id"]
    assert field["type"] == "str"
    assert not field.get("runtime")   # 대시보드에서 저장 가능해야 함
    assert field["default"] == ""
