"""SKILL.md 규약 — 패키지 데이터로 배포되므로 기계 독립적이어야 한다."""
from pathlib import Path

from notionmemory.core import skill_assets

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = skill_assets.skills_root()


def test_skills_root_is_inside_package():
    assert CANONICAL.is_dir()
    assert CANONICAL.name == "agent_skills"
    assert CANONICAL.parent.name == "notionmemory"


def test_skill_names_are_the_final_set():
    assert skill_assets.skill_names() == [
        "calendar", "library", "memory", "settings", "templates"]   # notes 제거


def test_skill_names_include_library():
    assert "library" in skill_assets.skill_names()


def test_library_skill_documents_the_three_modes_and_refresh():
    text = (CANONICAL / "library" / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---", 2)[1]
    assert "name: library" in head and "description:" in head
    for cmd in ("library search", "library read", "library refresh"):
        assert cmd in text, cmd
    # 빈 색인 → refresh 규약
    assert "refresh" in text and ("none" in text or "empty" in text or "stale" in text)
    # 포인터 우선 / 라이브 확인 / 위임
    assert "read" in text and ("subagent" in text or "delegate" in text)


def test_no_skill_md_contains_machine_specific_paths():
    """배포물이므로 절대경로·venv 경로가 하나도 없어야 한다."""
    for name in skill_assets.skill_names():
        text = (CANONICAL / name / "SKILL.md").read_text(encoding="utf-8")
        assert "/Users/" not in text, f"{name}: 절대경로 잔존"
        assert "venv/bin" not in text, f"{name}: venv 경로 잔존"


def test_repo_scope_mirrors_are_gone():
    """레포 미러는 폐지 — 남아 있으면 레포 세션에서 스킬이 두 번 노출된다."""
    for rel in (".claude/skills", ".agents/skills"):
        assert not (ROOT / rel).exists(), f"레포 미러 잔존: {rel}"


def test_memory_skill_conventions():
    text = (CANONICAL / "memory" / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---", 2)[1]
    assert "name: memory" in head
    assert "description:" in head
    assert "remember this" in head and "note that" in head and "did we ever" in head
    assert "notionmemory remember" in text
    assert "--auto" in text
    assert "jwt-refresh-rotation" in text
    assert "--supersedes" in text and "--link" in text
    assert "recall --get" in text and "forget" in text


def test_calendar_frontmatter_and_body():
    text = (CANONICAL / "calendar" / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---", 2)[1]
    assert "name: calendar" in head and "description:" in head
    assert "notionmemory calendar" in text
    assert "--auto" not in text


def test_settings_skill_wraps_serve():
    text = (CANONICAL / "settings" / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---", 2)[1]
    assert "name: settings" in head
    assert "notionmemory serve" in text
    assert "8765" in text
    assert "pkill" in text


def test_templates_frontmatter_and_three_step_protocol():
    text = (CANONICAL / "templates" / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---", 2)[1]
    assert "name: templates" in head and "description:" in head
    # 3단계 규약이 순서대로 있어야 한다 — 2번을 건너뛰고 속성명을 추측하면 왕복이 늘어난다
    for cmd in ("templates list", "templates show", "templates query", "templates add"):
        assert cmd in text, cmd
    assert text.index("templates list") < text.index("templates show")
    assert "guess" in text


def test_templates_skill_documents_the_hard_limits():
    text = (CANONICAL / "templates" / "SKILL.md").read_text(encoding="utf-8")
    assert "body" in text and "searchable" in text    # 본문 검색 불가
    assert "--allow-new-option" in text
    assert "row id" in text or "id" in text


def test_templates_skill_states_the_subagent_gate_as_three_conditions():
    text = (CANONICAL / "templates" / "SKILL.md").read_text(encoding="utf-8")
    section = text.split("subagent", 1)[1]
    assert "3 or more" in section and "synthesis" in section and "Read-only" in section


CROSSREF_HEADING = "## Find content with library"


def _crossref_section(name: str) -> str:
    text = (CANONICAL / name / "SKILL.md").read_text(encoding="utf-8")
    assert CROSSREF_HEADING in text, f"{name}: 상호 참조 절 없음"
    return text.split(CROSSREF_HEADING, 1)[1]


def test_built_in_skills_point_content_recall_at_library():
    for name in ("calendar", "memory"):        # notes 은퇴 — 2개
        section = _crossref_section(name)
        assert "library" in section, f"{name}: library 안내 없음"


def test_cross_reference_sections_are_byte_identical():
    """두 파일이 갈라지면 한쪽만 낡는다 — 문구 동일성을 코드로 못 박는다.

    상호 참조는 두 SKILL.md 에 같은 규칙을 복사한 것이라, 한 파일만 리워드되면
    나머지 하나는 조용히 뒤처진다. 존재 여부만 보는 테스트로는 그 드리프트를 못 잡는다.
    """
    sections = {name: _crossref_section(name) for name in ("calendar", "memory")}
    assert len(set(sections.values())) == 1, (
        "상호 참조 절이 파일마다 다릅니다: "
        + ", ".join(sorted(n for n, s in sections.items() if s != sections["calendar"])))


def test_old_templates_crossref_section_is_gone():
    for name in ("calendar", "memory"):
        text = (CANONICAL / name / "SKILL.md").read_text(encoding="utf-8")
        assert "## 등록된 Notion 템플릿도 함께 본다" not in text


def test_calendar_skill_documents_write_routing():
    text = (CANONICAL / "calendar" / "SKILL.md").read_text(encoding="utf-8")
    section = text.split("Where to write", 1)[1]
    assert "--here" in section              # 이번만
    assert "calendar target" in section     # 앞으로 계속
    assert "templates add" in section       # 템플릿을 골랐을 때 갈 곳
    # calendar 가 남의 DB 에 쓴다는 오해를 주면 안 된다
    low = section.lower()
    assert "just this time" in low and "going forward" in low


def test_calendar_skill_tells_the_agent_to_ask_not_to_guess():
    text = (CANONICAL / "calendar" / "SKILL.md").read_text(encoding="utf-8")
    assert "guess" in text or "arbitrarily" in text


def test_templates_skill_mentions_the_calendar_write_handoff():
    text = (CANONICAL / "templates" / "SKILL.md").read_text(encoding="utf-8")
    assert "calendar target" in text


def test_templates_skill_documents_document_editing():
    text = (CANONICAL / "templates" / "SKILL.md").read_text(encoding="utf-8")
    # 명명한 명령이 실재해야 한다(Task 4 가 만든 것과 일치)
    for cmd in ("templates read", "templates block add", "templates block set",
                "templates block remove", "templates page add"):
        assert cmd in text, cmd


def test_templates_skill_states_the_three_document_rules():
    text = (CANONICAL / "templates" / "SKILL.md").read_text(encoding="utf-8")
    section = text.split("Document editing", 1)[1]
    assert "read" in section and "guess" in section         # read 없이 block-id 추측 금지
    assert "--yes" in section                               # --yes 는 지름길이 아니다
    assert "sibling" in section or "existing" in section    # 새 항목은 형제 모방


def test_templates_skill_notes_row_body_is_a_page():
    text = (CANONICAL / "templates" / "SKILL.md").read_text(encoding="utf-8")
    # 행 본문 = 페이지: add 로 행 id 얻어 block add
    assert "row" in text and "block add" in text


def test_templates_skill_documents_prompt_and_authoring():
    text = (CANONICAL / "templates" / "SKILL.md").read_text(encoding="utf-8")
    assert "templates prompt" in text          # 프롬프트 첨부
    assert "templates image" in text           # 이미지 저작
    assert "templates create-page" in text     # 페이지 저작
    assert "lecture" in text or "paper" in text  # 씨앗 예시(옛 notes 지식)


def test_templates_skill_documents_prompt_only_templates():
    text = (CANONICAL / "templates" / "SKILL.md").read_text(encoding="utf-8")
    assert "templates new-prompt" in text          # 생성 명령
    assert "prompt-only" in text
    # 빈 page_id = 매번 새 페이지 규약 + 전환 안내
    assert "new page" in text and ("Promot" in text or "register" in text)
    # 강의노트 시드 안내
    assert "lecture" in text


def test_no_skill_md_invokes_the_retired_notes_skill():
    """notes 은퇴 후 어떤 SKILL.md 도 `notionmemory run notes` 를 지시하면 안 된다 —
    그 명령은 이제 exit 2 로 실패한다(최종 리뷰 Important, settings SKILL.md 잔존 방지)."""
    for name in skill_assets.skill_names():
        text = (CANONICAL / name / "SKILL.md").read_text(encoding="utf-8")
        assert "run notes" not in text, f"{name}: 은퇴한 notes 스킬 실행 안내 잔존"
