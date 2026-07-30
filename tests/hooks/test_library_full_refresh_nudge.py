"""SessionStart `library refresh --full` 넛지 — read-repair 의 anti-entropy 스윕
트리거. 드리프트 관측(dirty) + floor 경과, 또는 관측 없이 backstop 경과일 때만.
네트워크 0, 벽시계는 `now` 주입으로 결정적 테스트."""
from datetime import datetime, timedelta, timezone

import pytest

from notionmemory.hooks import session_start
from notionmemory.skills.library import index

NOW = datetime(2026, 7, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / ".local" / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    return tmp_path


def _index(*, last_full_run="", dirty=False, pages=1):
    idx = index.load()
    for i in range(pages):
        index.upsert(idx, f"p{i}", title="t", headings=[], url="",
                     last_edited_time="2026-01-01T00:00:00Z")
    idx["last_full_run"] = last_full_run
    idx["dirty_since_full"] = dirty
    idx["last_run"] = NOW.isoformat()          # 갱신은 됐음(was_refreshed True)
    index.save(idx)


def _ago(days):
    return (NOW - timedelta(days=days)).isoformat()


def test_unscanned_index_is_silent():
    # 미갱신(빈) → library_injection 의 몫, 여기선 침묵
    assert session_start.library_full_refresh_injection(now=NOW) == ""


def test_empty_but_refreshed_is_silent():
    idx = index.load()
    idx["last_run"] = NOW.isoformat()          # 갱신은 됐지만 페이지 0
    index.save(idx)
    assert session_start.library_full_refresh_injection(now=NOW) == ""


def test_dirty_and_floor_passed_nudges():
    _index(last_full_run=_ago(10), dirty=True)    # floor(7) 경과 + 드리프트
    out = session_start.library_full_refresh_injection(now=NOW)
    assert "refresh --full" in out


def test_dirty_but_within_floor_is_silent():
    _index(last_full_run=_ago(2), dirty=True)     # floor 안 → 아직
    assert session_start.library_full_refresh_injection(now=NOW) == ""


def test_dirty_never_full_nudges():
    _index(last_full_run="", dirty=True)          # 한 번도 full 없음 + 드리프트
    assert "refresh --full" in session_start.library_full_refresh_injection(now=NOW)


def test_clean_never_full_is_silent():
    _index(last_full_run="", dirty=False)         # never-full·무드리프트 → 나그 안 함
    assert session_start.library_full_refresh_injection(now=NOW) == ""


def test_clean_but_backstop_passed_nudges():
    _index(last_full_run=_ago(40), dirty=False)   # 관측 없어도 backstop(30) 경과 → 한 번
    assert "refresh --full" in session_start.library_full_refresh_injection(now=NOW)


def test_clean_within_backstop_is_silent():
    _index(last_full_run=_ago(20), dirty=False)   # 20일 < backstop 30 → 침묵
    assert session_start.library_full_refresh_injection(now=NOW) == ""


def test_config_floor_override_respected():
    from notionmemory.core import config as cfg, paths
    cfg.save_skill_options(str(paths.config_path()), "library", {"full_refresh_days": 3})
    _index(last_full_run=_ago(5), dirty=True)     # 기본 7이면 침묵, 3이면 넛지
    assert "refresh --full" in session_start.library_full_refresh_injection(now=NOW)


def test_language_switch_en_ko():
    from notionmemory.core import config as cfg, paths
    _index(last_full_run=_ago(40), dirty=True)
    cfg.save_language(str(paths.config_path()), "en")
    assert "prune" in session_start.library_full_refresh_injection(now=NOW).lower()
    cfg.save_language(str(paths.config_path()), "ko")
    assert "정리" in session_start.library_full_refresh_injection(now=NOW)
