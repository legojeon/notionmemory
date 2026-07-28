"""스킬 표면 구분 — 에이전트가 부르는 스킬 vs 훅으로 도는 백그라운드 서비스."""
from notionmemory.app import build_registry
from notionmemory.core.skill_base import VALID_SURFACES


def _cards(tmp_path):
    return build_registry(str(tmp_path / "none.yaml")).cards()


def test_every_skill_declares_a_valid_surface(tmp_path):
    for card in _cards(tmp_path):
        assert card.surface in VALID_SURFACES, f"{card.id}: {card.surface!r}"


def test_git_is_a_background_service(tmp_path):
    git = next(c for c in _cards(tmp_path) if c.id == "git")
    assert git.surface == "service"


def test_agent_skills_are_the_ones_with_skill_md(tmp_path):
    """SKILL.md 보유 여부와 surface 가 어긋나면 둘 중 하나가 틀린 것이다."""
    from notionmemory.core import skill_assets
    with_md = set(skill_assets.skill_names())
    for card in _cards(tmp_path):
        if card.surface == "agent":
            assert card.id in with_md, f"{card.id}: agent 인데 SKILL.md 가 없다"
        else:
            assert card.id not in with_md, f"{card.id}: service 인데 SKILL.md 가 있다"
