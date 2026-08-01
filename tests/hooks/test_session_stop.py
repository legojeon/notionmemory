"""Stop 훅 — 세션 종료 시 이 프로젝트의 Draft memory consolidation 큐잉만 한다.

LLM pass(consolidate)는 여기서 절대 돌지 않는다 — agent_runtime 을 임포트도 호출도
하지 않는 것이 계약이다(비블로킹 큐잉 전용, task-3 브리프).
"""
from __future__ import annotations

import io
import json
import subprocess
import sys

from notionmemory.hooks import session_stop
from notionmemory.skills.memory import consolidation_queue as cq


def test_stop_hook_enqueues_one_job(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIONMEMORY_MEMQUEUE_DIR", str(tmp_path / "q"))
    monkeypatch.setattr(
        "notionmemory.hooks.session_stop.os.getcwd", lambda: str(tmp_path))
    # resolve_project(cwd) 는 session_start.resolve_toplevel 을 거친다 — git 리포
    # 밖(tmp_path)이라 자연히 실패해 cwd basename 폴백을 타지만, 결정적으로 만들기
    # 위해 명시적으로도 실패시킨다.
    monkeypatch.setattr(
        "notionmemory.hooks.session_start.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], 1, "", ""))
    # payload 없는 호출(빈 stdin)도 project-only enqueue 로 동작해야 한다 — cwd 는
    # payload 에 없으니 os.getcwd() 폴백을 탄다.
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    from notionmemory.hooks import session_stop
    assert session_stop.main() == 0
    from notionmemory.skills.memory import consolidation_queue as q
    jobs = q.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["project"] == tmp_path.name
    assert jobs[0]["cwd"] == str(tmp_path)


def test_stop_hook_never_imports_agent_runtime():
    """`import`/`from ... import` 문에 agent_runtime 이 없어야 한다 — LLM pass 는
    별도 명령(Task 4)에서만 돈다. 소스를 정적으로 검사한다(문서 문자열 언급은 무관 —
    실제 import 문만 본다). `sys.modules` 를 지우고 재임포트하는 방식은 쓰지 않는다
    — agent_runtime 이 이미 다른 테스트에 의해 로드돼 있으면 클래스 identity 가
    갈라져(`except AgentRuntimeError`가 재로딩된 다른 클래스 객체를 못 잡음) 무관한
    테스트를 오염시킨다(실측: `test_run_still_registers_when_the_agent_runtime_is_missing`
    가 전체 스위트에서만 깨졌다)."""
    import ast
    from pathlib import Path

    from notionmemory.hooks import session_stop
    src = Path(session_stop.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any("agent_runtime" in n.name for n in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module and "agent_runtime" in node.module)
    assert not hasattr(session_stop, "build_runtime")
    assert not hasattr(session_stop, "AgentRuntimeError")


def test_stop_hook_swallows_exceptions_and_returns_zero(monkeypatch):
    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr("notionmemory.hooks.session_stop.os.getcwd", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    from notionmemory.hooks import session_stop
    assert session_stop.main() == 0


def test_stop_hook_swallows_enqueue_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "notionmemory.hooks.session_stop.os.getcwd", lambda: str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    def boom(*a, **k):
        raise OSError("disk full")

    from notionmemory.hooks import session_stop
    monkeypatch.setattr(session_stop.consolidation_queue, "enqueue", boom)
    assert session_stop.main() == 0


def test_stop_hook_accepts_harness_kwarg(tmp_path, monkeypatch):
    """CLI dispatch 는 `--harness` 를 넘긴다(다른 훅과 동일 시그니처) — enqueue-only
    이므로 harness 는 사용하지 않아도 되지만 kwarg 는 받아야 한다."""
    monkeypatch.setenv("NOTIONMEMORY_MEMQUEUE_DIR", str(tmp_path / "q"))
    monkeypatch.setattr(
        "notionmemory.hooks.session_stop.os.getcwd", lambda: str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    from notionmemory.hooks import session_stop
    assert session_stop.main(harness="codex") == 0


def test_stop_hook_enqueues_transcript_session(tmp_path, monkeypatch):
    monkeypatch.setenv(cq.QUEUE_ROOT_ENV, str(tmp_path))
    monkeypatch.setattr(session_stop, "resolve_project", lambda cwd: "proj")
    payload = json.dumps({"session_id": "sid1", "transcript_path": "/tr.jsonl",
                          "cwd": "/proj"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert session_stop.main(harness="claude") == 0
    job = cq.list_jobs()[0]
    assert job["sessions"][0] == {"session_id": "sid1", "transcript_path": "/tr.jsonl",
                                  "harness": "claude", "ts": job["sessions"][0]["ts"]}


def test_stop_hook_noop_when_capture_mode_off(tmp_path, monkeypatch):
    monkeypatch.setenv(cq.QUEUE_ROOT_ENV, str(tmp_path))
    monkeypatch.setattr(session_stop, "capture_mode", lambda: "off")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert session_stop.main() == 0
    assert cq.list_jobs() == []


def test_stop_hook_codex_glob_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv(cq.QUEUE_ROOT_ENV, str(tmp_path))
    monkeypatch.setattr(session_stop, "resolve_project", lambda cwd: "proj")
    monkeypatch.setattr(session_stop.transcripts, "find_codex_rollout",
                        lambda sid: "/roll.jsonl" if sid == "sid2" else "")
    payload = json.dumps({"session_id": "sid2", "cwd": "/proj"})  # transcript_path 없음
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert session_stop.main(harness="codex") == 0
    assert cq.list_jobs()[0]["sessions"][0]["transcript_path"] == "/roll.jsonl"


def test_hook_noop_under_consolidate_guard(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv(cq.QUEUE_ROOT_ENV, str(tmp_path))
    monkeypatch.setenv("NOTIONMEMORY_CONSOLIDATE", "1")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert session_stop.main() == 0
    assert capsys.readouterr().out == ""
    assert cq.list_jobs() == []  # 재귀 가드 아래서는 큐잉조차 하지 않는다


def test_hook_reads_stdin_before_consolidate_guard_noop(monkeypatch, tmp_path):
    """M6 — 재귀 가드로 no-op 하더라도 stdin 은 이미 소비돼 있어야 한다(모든 훅이
    stdin 을 먼저 비운다는 단일 규율). 커스텀 스트림으로 `.read()` 호출 여부를
    직접 관측한다."""
    monkeypatch.setenv(cq.QUEUE_ROOT_ENV, str(tmp_path))
    monkeypatch.setenv("NOTIONMEMORY_CONSOLIDATE", "1")

    class _TrackedStdin(io.StringIO):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.read_called = False

        def read(self, *a, **k):
            self.read_called = True
            return super().read(*a, **k)

    stdin = _TrackedStdin("{}")
    monkeypatch.setattr("sys.stdin", stdin)
    assert session_stop.main() == 0
    assert stdin.read_called is True
