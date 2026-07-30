"""Second Brain v2 Phase 2b Task 4 — memory SKILL.md 는 per-message 로컬 memory
힌트(UserPromptSubmit)와 `memory reindex` 규약을 프로즈로 규정해야 한다(코드가
강제 못 하니 문구 존재만 단언한다).

플러그인 사본의 byte-identity는 `tests/test_plugin_manifests.py`가 이미 강제하므로
여기서는 agent_skills(정본) 쪽 substring만 확인한다."""
from notionmemory.core import skill_assets

CANONICAL = skill_assets.skills_root()


def _memory_skill_md() -> str:
    return (CANONICAL / "memory" / "SKILL.md").read_text(encoding="utf-8")


def test_memory_skill_md_documents_reindex_command():
    text = _memory_skill_md()
    assert "memory reindex" in text


def test_memory_skill_md_documents_per_message_hint_concept():
    text = _memory_skill_md()
    low = text.lower()
    assert "relevant memory" in low or "hint" in low


def test_memory_skill_md_hint_is_advisory_not_authoritative():
    """힌트가 뜨면 관련 있을 때만 recall 하고, 무관하면 무시하라는 규약이 있어야
    한다 — 힌트를 맹목적으로 그대로 출력하는 것과는 다른 행동이다."""
    text = _memory_skill_md()
    assert "recall" in text.lower()
