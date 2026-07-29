from notionmemory.core.config import Config
from notionmemory.core.integrations import Integration, build_integrations
from notionmemory.core.registry import Registry, SkillCard
from notionmemory.core.skill_base import Skill, RunResult


class NeedsNotionAgent(Skill):
    id, name, kinds, requires = "demo", "Demo", ("capture",), ["notion", "agent"]
    def options_schema(self): return {}
    def run(self, options, log): return RunResult(True)


class NeedsBoom(Skill):
    id, name, kinds, requires = "demo", "Demo", ("capture",), ["boom"]
    def options_schema(self): return {}
    def run(self, options, log): return RunResult(True)


class RaisingIntegration(Integration):
    id, name = "boom", "Boom"
    def status(self, config):
        raise RuntimeError("integration blew up")


def _reg(cfg_dict):
    cfg = Config(cfg_dict)
    return Registry([NeedsNotionAgent()], build_integrations(cfg), cfg)


def test_blocked_lists_missing_integrations():
    card = _reg({"integrations": {"notion": {"token": "x"}}}).cards()[0]
    assert card.status == "blocked"
    assert card.missing == ["agent"]


def test_available_when_all_requires_connected():
    card = _reg({"integrations": {
        "notion": {"token": "x"}, "agent": {"backend": "claude"}}}).cards()[0]
    assert card.status == "available"
    assert card.missing == []


def test_get_returns_skill_instance():
    reg = _reg({})
    assert reg.get("demo").id == "demo"
    assert reg.get("nope") is None


def test_status_is_error_when_integration_status_raises():
    cfg = Config({})
    reg = Registry([NeedsBoom()], {"boom": RaisingIntegration()}, cfg)
    card = reg.cards()[0]
    assert card.status == "error"
    assert card.missing == ["boom"]


def test_registry_public_accessors():
    cfg = Config({})
    ints = build_integrations(cfg)
    reg = Registry([], ints, cfg)
    assert reg.config is cfg
    assert set(reg.integrations().keys()) == {"notion", "agent", "git"}
    reg.integrations().clear()  # 복사본이어야 함
    assert set(reg.integrations().keys()) == {"notion", "agent", "git"}


# ── ko 오버레이 (cards(lang)) ──────────────────────────────

def test_card_run_label_is_korean_when_lang_ko():
    from notionmemory.skills.library.skill import LibrarySkill
    cfg = Config({})
    reg = Registry([LibrarySkill(cfg)], build_integrations(cfg), cfg)
    card = reg.cards("ko")[0]
    assert card.run_label == "재색인 실행"


def test_card_run_label_is_english_by_default():
    from notionmemory.skills.library.skill import LibrarySkill
    cfg = Config({})
    reg = Registry([LibrarySkill(cfg)], build_integrations(cfg), cfg)
    card = reg.cards()[0]
    assert card.run_label == "Reindex"
