"""SessionEnd 훅 — 세션 종료 시 consolidate 를 detached 로 스폰(비블로킹).

Codex 는 SessionEnd 타임아웃이 기본 1초/최대 3초(공식 문서)라 이 훅은 stdin 소비 →
게이트 확인 → 스폰 → 종료 외에는 아무것도 하지 않는다. 게이트/락은 autorun 이 쥔다.
"""
from __future__ import annotations

import io

import pytest

from notionmemory.hooks import session_end


def test_session_end_spawns_via_autorun(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    monkeypatch.setattr(session_end.autorun, "maybe_spawn", lambda cli: calls.append(cli) or True)
    assert session_end.main(harness="claude") == 0
    assert calls  # sys.argv[0] 이 cli 경로로 전달됨


def test_session_end_swallows_everything(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("not-json"))
    monkeypatch.setattr(session_end.autorun, "maybe_spawn",
                        lambda cli: (_ for _ in ()).throw(RuntimeError("boom")))
    assert session_end.main() == 0


def test_session_end_noop_under_recursion_guard(monkeypatch):
    monkeypatch.setenv("NOTIONMEMORY_CONSOLIDATE", "1")
    monkeypatch.setattr(session_end.autorun, "maybe_spawn",
                        lambda cli: pytest.fail("guarded"))
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert session_end.main() == 0
