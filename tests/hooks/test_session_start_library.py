"""SessionStart library 주입 — 색인 나이만(네트워크 0), 빈 색인은 refresh 신호."""
import io
import json

import pytest

from notionmemory.hooks import session_start
from notionmemory.skills.library import index as I


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(session_start, "resolve_toplevel", lambda cwd: "")
    monkeypatch.setattr(session_start, "maybe_install_git_hook", lambda top: "")
    monkeypatch.setattr(session_start.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 1, "stdout": ""})())
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    return tmp_path


def test_empty_index_injects_refresh_signal(capsys):
    assert session_start.main() == 0
    out = capsys.readouterr().out
    assert "library index" in out and ("none" in out or "refresh" in out)


def test_populated_index_injects_age(capsys):
    idx = I.load()
    I.upsert(idx, "pg1", title="x", headings=[], url="u", last_edited_time="t")
    idx["last_refreshed"] = "2026-07-24T10:00:00.000Z"
    I.save(idx)
    session_start.main()
    out = capsys.readouterr().out
    assert "library index" in out and "1" in out


def test_refreshed_but_empty_workspace_is_silent(capsys):
    """refresh 는 돌았는데 공유 페이지가 0개면 넛지하지 않는다(빈 워크스페이스를 매 세션
    닦달하지 않기 위한 침묵 — '미갱신'만 넛지한다)."""
    idx = I.load()
    idx["last_run"] = "2026-07-25T00:00:00+00:00"
    I.save(idx)
    session_start.main()
    out = capsys.readouterr().out
    assert "library index" not in out


def test_injection_prefix_is_not_json_sniffable(capsys):
    session_start.main()
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "library" in ln]
    assert lines and lines[0][0] not in "[{"


def test_injection_makes_no_network_call(monkeypatch, capsys):
    import requests
    def explode(*a, **k):
        raise AssertionError("세션 훅이 네트워크를 호출했다")
    monkeypatch.setattr(requests, "request", explode)
    monkeypatch.setattr(requests, "get", explode)
    assert session_start.main() == 0
