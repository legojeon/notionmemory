"""레지스트리 카드 — agent 미연결이 CRUD 를 잠그면 안 된다."""
import pytest

from notionmemory.app import build_registry
from notionmemory.core.config import Config
from notionmemory.skills.templates.skill import TemplatesSkill


def _skill(tmp_path):
    return TemplatesSkill(Config.load(str(tmp_path / "none.yaml")))


def test_identity_follows_the_naming_rule(tmp_path):
    s = _skill(tmp_path)
    assert s.id == "templates" and s.name == "Templates"
    assert s.kinds == ("recall", "action")
    assert s.surface == "agent"


def test_requires_notion_only(tmp_path):
    """agent 는 본문 생성에만 쓰이고 실패해도 프로필이 저장된다(스펙 §1)."""
    assert _skill(tmp_path).requires == ["notion"]


def test_options_schema_is_target_and_slug_only(tmp_path):
    assert set(_skill(tmp_path).options_schema()) == {"target", "slug"}


def test_usage_points_at_the_cli_verbs(tmp_path):
    assert "notionmemory templates" in _skill(tmp_path).usage


def test_run_without_target_fails_with_a_useful_message(tmp_path):
    result = _skill(tmp_path).run({}, lambda *_: None)
    assert result.ok is False and "target" in result.message


def test_registry_includes_templates(tmp_path):
    ids = [c.id for c in build_registry(str(tmp_path / "none.yaml")).cards()]
    assert "templates" in ids


def test_run_registers_through_introspect(tmp_path, monkeypatch):
    from notionmemory.skills.templates import skill as mod

    seen = {}

    class FakeProfile:
        slug, databases = "job-tracker", [{"key": "a"}]

    def fake_register(session, target, *, slug="", runtime=None, log=print):
        seen.update(target=target, slug=slug)
        return FakeProfile()

    monkeypatch.setattr(mod, "NotionSession", lambda **kw: object())
    monkeypatch.setattr(mod.introspect, "register", fake_register)
    monkeypatch.setattr(mod, "build_runtime", lambda config: object())
    result = _skill(tmp_path).run({"target": "https://n/x"}, lambda *_: None)
    assert result.ok is True and "job-tracker" in result.message
    assert seen["target"] == "https://n/x"


def test_run_still_registers_when_the_agent_runtime_is_missing(tmp_path, monkeypatch):
    from notionmemory.core.agent_runtime import AgentRuntimeError
    from notionmemory.skills.templates import skill as mod

    got = {}

    class FakeProfile:
        slug, databases = "job-tracker", []

    def fake_register(session, target, *, slug="", runtime=None, log=print):
        got["runtime"] = runtime
        return FakeProfile()

    def boom(config):
        raise AgentRuntimeError("미감지")

    monkeypatch.setattr(mod, "NotionSession", lambda **kw: object())
    monkeypatch.setattr(mod, "build_runtime", boom)
    monkeypatch.setattr(mod.introspect, "register", fake_register)
    assert _skill(tmp_path).run({"target": "x"}, lambda *_: None).ok is True
    assert got["runtime"] is None


def test_run_does_not_leak_unexpected_exceptions_from_introspect(tmp_path, monkeypatch):
    """introspect.register() 는 실제 Notion HTTP 호출이라 KeyError 등 RuntimeError/
    ValueError 가 아닌 예외도 낼 수 있다 — run() 은 CLI 의 _cmd_run 에서 try/except 없이
    호출되므로 여기서 삼키지 않으면 생 traceback 이 그대로 노출된다."""
    from notionmemory.skills.templates import skill as mod

    def fake_register(session, target, *, slug="", runtime=None, log=print):
        raise KeyError("data_source_id")

    monkeypatch.setattr(mod, "NotionSession", lambda **kw: object())
    monkeypatch.setattr(mod, "build_runtime", lambda config: object())
    monkeypatch.setattr(mod.introspect, "register", fake_register)
    result = _skill(tmp_path).run({"target": "x"}, lambda *_: None)
    assert result.ok is False
    assert "data_source_id" in result.message or "오류" in result.message
