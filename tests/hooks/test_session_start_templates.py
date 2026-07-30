"""SessionStart 템플릿 주입 — 조용하고, 빠르고, JSON 으로 오인되지 않는다."""
import io
import json

import pytest

from notionmemory.hooks import session_start
from notionmemory.skills.templates import profile as P


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(session_start, "resolve_toplevel", lambda cwd: "")
    monkeypatch.setattr(session_start, "maybe_install_git_hook", lambda top: "")
    # recall 서브프로세스·library 색인·온보딩 넛지 신호는 이 테스트의 관심사가 아니다(각각
    # test_hook_cli.py / test_session_start_library.py / test_onboarding_nudge.py 가 전담)
    # — 여기선 templates만 본다.
    monkeypatch.setattr(session_start.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 1, "stdout": ""})())
    monkeypatch.setattr(session_start, "library_injection", lambda: "")
    monkeypatch.setattr(session_start, "onboarding_injection", lambda: "")
    monkeypatch.setattr(session_start, "memory_index_injection", lambda: "")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    return tmp_path


def _save(slug, **kw):
    p = P.Profile(slug=slug, name=slug, page_id="pg", summary=kw.pop("summary", "요약"),
                  databases=[], **kw)
    P.save(p)
    return p


def test_nothing_registered_prints_nothing(capsys):
    assert session_start.main() == 0
    assert capsys.readouterr().out == ""


def test_registered_templates_are_listed_with_summaries(capsys):
    _save("job-tracker", summary="지원 현황 추적")
    _save("reading-list", summary="읽은 책 기록")
    assert session_start.main() == 0
    out = capsys.readouterr().out
    assert "job-tracker(지원 현황 추적)" in out and "reading-list(읽은 책 기록)" in out


def test_injection_prefix_is_not_json_sniffable(capsys):
    _save("job-tracker")
    session_start.main()
    line = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()][0]
    assert line.startswith("notionmemory templates:")
    assert line[0] not in "[{"


def test_disabled_and_trashed_are_hidden(capsys):
    _save("live")
    _save("off", enabled=False)
    _save("gone-ish", health="trashed")
    session_start.main()
    out = capsys.readouterr().out
    assert "live" in out and "off" not in out and "gone-ish" not in out


def test_injection_makes_no_network_calls(monkeypatch, capsys):
    """세션 시작을 느리게 하면 안 된다 — 파일만 읽는다."""
    import requests

    def explode(*a, **k):
        raise AssertionError("세션 훅이 네트워크를 호출했다")
    monkeypatch.setattr(requests, "request", explode)
    monkeypatch.setattr(requests, "get", explode)
    _save("job-tracker")
    assert session_start.main() == 0
    assert "job-tracker" in capsys.readouterr().out


def test_a_broken_profile_file_does_not_break_the_session(capsys):
    _save("good")
    P.store_dir().joinpath("broken.md").write_text("쓰레기", encoding="utf-8")
    assert session_start.main() == 0
    assert "good" in capsys.readouterr().out
