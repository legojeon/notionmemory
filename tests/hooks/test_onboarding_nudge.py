"""SessionStart 온보딩 넛지 — PAT 미연결/calendar·memory 미바인딩이면 안내,
전부 설정되면 침묵(task-5, status.probe(verify=False) 기반, 네트워크 0)."""
import io
import json

import pytest

from notionmemory.hooks import session_start


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(session_start, "resolve_toplevel", lambda cwd: "")
    monkeypatch.setattr(session_start, "maybe_install_git_hook", lambda top: "")
    monkeypatch.setattr(session_start.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 1, "stdout": ""})())
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    return tmp_path


def _probe(connected, cal_bound, mem_bound):
    return {
        "notion": {"connected": connected, "detail": ""},
        "calendar": {"bound": cal_bound, "url": ""},
        "memory": {"bound": mem_bound, "url": ""},
        "library": {"indexed": False, "detail": ""},
    }


def _patch_probe(monkeypatch, connected, cal_bound, mem_bound):
    from notionmemory.core import status
    monkeypatch.setattr(
        status, "probe",
        lambda config, verify=True: _probe(connected, cal_bound, mem_bound))


def test_pat_not_connected_leads_with_settings_nudge(monkeypatch, capsys):
    _patch_probe(monkeypatch, False, False, False)
    assert session_start.main() == 0
    out = capsys.readouterr().out.lower()
    assert "settings dashboard" in out
    assert "notion" in out


def test_pat_connected_but_dbs_unbound_nudges_setup(monkeypatch, capsys):
    _patch_probe(monkeypatch, True, False, False)
    assert session_start.main() == 0
    out = capsys.readouterr().out.lower()
    assert "guided setup" in out
    assert "calendar" in out and "memory" in out
    # PAT 리드인 문구(미연결)는 없어야 한다 — 이미 연결됐으므로.
    assert "isn't connected" not in out


def test_pat_connected_one_db_bound_still_nudges_missing_only(monkeypatch, capsys):
    _patch_probe(monkeypatch, True, True, False)
    assert session_start.main() == 0
    out = capsys.readouterr().out.lower()
    assert "guided setup" in out
    assert "memory" in out


def test_everything_bound_is_silent(monkeypatch, capsys):
    _patch_probe(monkeypatch, True, True, True)
    assert session_start.main() == 0
    out = capsys.readouterr().out.lower()
    assert "guided setup" not in out


def test_onboarding_injection_language_switch(monkeypatch, tmp_path):
    from notionmemory.core import config as cfg, paths
    _patch_probe(monkeypatch, False, False, False)
    cfg.save_language(str(paths.config_path()), "en")
    assert "settings dashboard" in session_start.onboarding_injection()
    cfg.save_language(str(paths.config_path()), "ko")
    assert "settings" in session_start.onboarding_injection()
    assert "연결" in session_start.onboarding_injection()
