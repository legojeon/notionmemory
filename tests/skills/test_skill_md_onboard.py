"""onboard SKILL.md — 온보딩 오케스트레이션 계약을 프로즈로 규정하는지 단언.
코드가 강제 못 하는 에이전트 행동이라 문구 존재를 검사한다(배포 패키지 데이터)."""
from notionmemory.core import skill_assets

CANONICAL = skill_assets.skills_root()


def _text():
    return (CANONICAL / "onboard" / "SKILL.md").read_text(encoding="utf-8")


def test_onboard_in_skill_set():
    assert "onboard" in skill_assets.skill_names()


def test_frontmatter_has_name_and_trigger_description():
    head = _text().split("---", 2)[1]
    assert "name: onboard" in head
    low = head.lower()
    assert "description:" in head
    assert "set up" in low or "onboard" in low


def test_probes_state_first():
    assert "notionmemory status" in _text()


def test_states_the_full_sequence():
    text = _text().lower()
    for step in ("language", "pat", "memory", "calendar", "library", "templates"):
        assert step in text, step


def test_language_step_sets_config_via_cli():
    """언어를 온보딩 첫 스텝으로 물어 `notionmemory language` 로 기록한다."""
    text = _text()
    assert "notionmemory language" in text
    low = text.lower()
    assert "한국어" in text or "korean" in low
    assert "english" in low


def test_pat_url_is_current_not_legacy():
    """토큰 생성 URL 은 현행 app.notion.com/developers/tokens — 에이전트가 자기
    기억의 옛 notion.so/my-integrations 를 쓰지 않도록 명시한다."""
    text = _text()
    assert "app.notion.com/developers/tokens" in text
    assert "my-integrations" not in text


def test_uses_structured_choices_with_fallback():
    text = _text()
    assert "AskUserQuestion" in text
    low = text.lower()
    assert "numbered" in low or "번호" in low or "fallback" in low
    assert "codex" in low  # Codex 폴백 근거


def test_offers_create_connect_skip_for_dbs():
    text = _text()
    assert "connect --new" in text and "connect --url" in text
    assert "skip" in text.lower()


def test_pat_via_dashboard_never_raw_in_chat():
    low = _text().lower()
    assert "settings" in low and "dashboard" in low
    assert "raw" in low and ("pat" in low or "token" in low)


def test_skips_already_done_steps():
    low = _text().lower()
    assert "skip" in low and ("already" in low or "done" in low or "bound" in low)
