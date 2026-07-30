"""SessionStart 온보딩 넛지 — 코어(PAT/memory/calendar) 미설정이고 아직 제안 안
했으면 onboard 스킬을 한 번 제안(one-shot 마커), 이미 제안했거나 코어가 다 되면 침묵."""
import io
import json

import pytest

from notionmemory.hooks import session_start


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setattr(session_start, "resolve_toplevel", lambda cwd: "")
    monkeypatch.setattr(session_start, "maybe_install_git_hook", lambda top: "")
    monkeypatch.setattr(session_start.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 1, "stdout": ""})())
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    return tmp_path


def _probe(connected, cal_bound, mem_bound, indexed=False):
    return {
        "notion": {"connected": connected, "detail": ""},
        "calendar": {"bound": cal_bound, "url": ""},
        "memory": {"bound": mem_bound, "url": ""},
        "library": {"indexed": indexed, "detail": ""},
    }


def _patch_probe(monkeypatch, connected, cal_bound, mem_bound, indexed=False):
    from notionmemory.core import status
    monkeypatch.setattr(
        status, "probe",
        lambda config, verify=True: _probe(connected, cal_bound, mem_bound, indexed))


def test_unoffered_pat_missing_offers_onboard(monkeypatch):
    _patch_probe(monkeypatch, False, False, False)
    out = session_start.onboarding_injection().lower()
    assert "onboard" in out
    assert "notion" in out
    # 온보딩을 settings 로 오도하지 않는다(디-온보딩)
    assert "settings dashboard" not in out


def test_unoffered_dbs_missing_lists_them(monkeypatch):
    _patch_probe(monkeypatch, True, False, False)
    out = session_start.onboarding_injection().lower()
    assert "onboard" in out
    assert "memory" in out and "calendar" in out
    assert "isn't connected" not in out  # PAT 이미 연결


def test_offer_sets_marker_and_is_one_shot(monkeypatch):
    from notionmemory.core import paths
    from notionmemory.core.config import Config
    _patch_probe(monkeypatch, False, False, False)
    first = session_start.onboarding_injection()
    assert first  # 제안함
    assert Config.load(str(paths.config_path())).onboarding_offered() is True
    # 두 번째 호출은 마커 때문에 침묵
    assert session_start.onboarding_injection() == ""


def test_marker_already_set_is_silent(monkeypatch):
    from notionmemory.core import config as cfg, paths
    cfg.save_onboarding_offered(str(paths.config_path()))
    _patch_probe(monkeypatch, False, False, False)
    assert session_start.onboarding_injection() == ""


def test_core_all_set_is_silent_and_no_marker(monkeypatch):
    from notionmemory.core import paths
    from notionmemory.core.config import Config
    # library 미색인이어도 코어(PAT/memory/calendar)가 되면 onboard 제안 안 함
    _patch_probe(monkeypatch, True, True, True, indexed=False)
    assert session_start.onboarding_injection() == ""
    assert Config.load(str(paths.config_path())).onboarding_offered() is False


def test_offer_language_switch(monkeypatch):
    from notionmemory.core import config as cfg, paths
    _patch_probe(monkeypatch, False, False, False)
    cfg.save_language(str(paths.config_path()), "en")
    assert "onboard" in session_start.onboarding_injection().lower()
    # 마커가 set 됐으니 ko 확인 전 리셋(마커 삭제 위해 새 probe 세션 = 다른 tmp 없음)
    cfg.save_language(str(paths.config_path()), "ko")
    # 마커 우회: 직접 문구만 확인
    from notionmemory.core import i18n, messages
    ko = i18n.t(messages.CATALOG, "hook.onboarding_offer", "ko",
                missing="memory", cli="notionmemory")
    assert "onboard" in ko and "온보딩" in ko


def test_main_offer_suppresses_library_empty_nudge(monkeypatch, capsys):
    # onboard 제안이 나가면 library 빈-색인 넛지는 그 세션에 억제(중복 방지)
    _patch_probe(monkeypatch, False, False, False)
    assert session_start.main() == 0
    out = capsys.readouterr().out.lower()
    assert "onboard" in out
    assert "not scanned" not in out  # library_empty 억제
