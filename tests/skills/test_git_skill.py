from notionmemory.app import build_registry
from notionmemory.core.config import Config
from notionmemory.skills.git.skill import GitCaptureSkill


def test_card_shape():
    s = GitCaptureSkill(Config({"skills": {}}))
    assert s.id == "git" and s.kinds == ("capture",)
    schema = s.options_schema()
    assert schema["install_policy"]["choices"] == ["auto", "ask", "off"]
    assert schema["install_policy"]["default"] == "auto"
    assert "repos" not in schema and "exclude" not in schema


def test_run_points_to_cli():
    s = GitCaptureSkill(Config({"skills": {}}))
    result = s.run({}, print)
    assert result.ok is False
    assert result.message == ("git은 CLI로 사용합니다: "
                              "notionmemory git install|status|list|ack|flush")


def test_registered_in_registry(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills: {}\n", encoding="utf-8")
    registry = build_registry(str(cfg))
    assert any(c.id == "git" for c in registry.cards())
