"""Second Brain v2 Phase 2a Task 6 — memory SKILL.md 는 Draft 캡처/consolidation
규약을 프로즈로 규정해야 한다(코드가 강제 못 하니 문구 존재만 단언한다).

플러그인 사본의 byte-identity는 `tests/test_plugin_manifests.py`가 이미 강제하므로
여기서는 agent_skills(정본) 쪽 substring만 확인한다."""
from notionmemory.core import skill_assets

CANONICAL = skill_assets.skills_root()


def _memory_skill_md() -> str:
    return (CANONICAL / "memory" / "SKILL.md").read_text(encoding="utf-8")


def test_memory_skill_md_documents_consolidate_command():
    text = _memory_skill_md()
    assert "memory consolidate" in text


def test_memory_skill_md_documents_draft_status():
    text = _memory_skill_md()
    low = text.lower()
    assert "draft" in low


def test_memory_skill_md_documents_auto_flag_capture_semantics():
    text = _memory_skill_md()
    assert "--auto" in text


def test_memory_skill_md_distinguishes_auto_draft_from_manual_active():
    """--auto 저장은 Draft(정제 대기), --auto 없는 수동 저장은 Active(즉시 중요)
    라는 구분이 프로즈에 명시돼야 한다 — 기존 '--auto를 붙인다' 규칙만으로는
    상태 전이가 드러나지 않는다."""
    text = _memory_skill_md()
    low = text.lower()
    assert "active" in low
    # Draft 라는 단어와 consolidate 라는 단어가 같은 문서 안에서 함께 상태 전이를
    # 설명해야 한다 — 둘 중 하나만 있으면 절반짜리 문서다.
    assert "draft" in low and "consolidate" in low
