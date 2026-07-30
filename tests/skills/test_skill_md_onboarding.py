"""'Connection & onboarding' 절 — memory/calendar SKILL.md(패키지 경로)가 연결 확인·
PAT 안내·connect 메뉴를 프로즈로 규정하는지 최소 구조를 단언한다.

Task 6 브리프: 새 CLI 표면(calendar/memory connect --new|--url, connection,
notionmemory status)을 에이전트가 실제로 어떻게 쓰는지는 SKILL.md 프로즈만 규정한다
— 코드가 강제할 수 없으니 여기서 문구 존재만 단언한다."""
from notionmemory.core import skill_assets

CANONICAL = skill_assets.skills_root()

ONBOARDING_HEADING = "## Connection & onboarding"


def _text(name: str) -> str:
    return (CANONICAL / name / "SKILL.md").read_text(encoding="utf-8")


def _onboarding_section(name: str) -> str:
    text = _text(name)
    assert ONBOARDING_HEADING in text, f"{name}: onboarding 절 없음"
    return text.split(ONBOARDING_HEADING, 1)[1]


def test_memory_and_calendar_have_onboarding_section():
    for name in ("memory", "calendar"):
        _onboarding_section(name)  # raises if missing


def test_onboarding_section_checks_connection_first():
    for name in ("memory", "calendar"):
        section = _onboarding_section(name)
        assert "notionmemory status" in section
        assert "connection" in section


def test_onboarding_section_documents_connect_menu():
    for name in ("memory", "calendar"):
        section = _onboarding_section(name)
        assert f"{name} connect --new" in section
        assert f"{name} connect --url" in section


def test_onboarding_section_never_puts_raw_pat_in_chat():
    for name in ("memory", "calendar"):
        section = _onboarding_section(name)
        low = section.lower()
        assert "settings" in low
        assert "raw" in low and ("token" in low or "pat" in low)


def test_onboarding_section_points_to_onboard_not_duplicate_sequence():
    for name in ("memory", "calendar"):
        section = _onboarding_section(name)
        # 전체 시퀀스는 onboard 스킬이 소유 — per-skill 은 onboard 를 참조만 한다
        assert "onboard" in section
        # 중복 standalone "Setup sequence" 불릿은 사라진다(포인터 문단의 화살표 요약은 허용)
        assert "Setup sequence" not in section


def test_memory_connect_is_documented_as_strict():
    section = _onboarding_section("memory")
    assert "strict" in section.lower()


def test_calendar_connect_documents_column_and_conflict_behavior():
    section = _onboarding_section("calendar")
    low = section.lower()
    assert "column" in low
    assert "conflict" in low


def test_templates_onboarding_is_usage_only_no_forced_setup():
    text = _text("templates")
    assert ONBOARDING_HEADING in text
    section = text.split(ONBOARDING_HEADING, 1)[1]
    # 설정 강제 없음 — connect 메뉴/PAT 게이팅 문구가 들어오면 브리프 위반
    assert "connect --new" not in section
    assert "connect --url" not in section
