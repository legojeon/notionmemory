"""Stop 훅 — 세션 종료 시 이 프로젝트의 Draft memory consolidation 큐잉만 한다.

LLM pass(consolidate)는 여기서 절대 돌지 않는다 — agent_runtime 을 임포트도 호출도
하지 않는 것이 계약이다(비블로킹 큐잉 전용, task-3 브리프).
"""
from __future__ import annotations

import subprocess
import sys


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
    from notionmemory.hooks import session_stop
    assert session_stop.main() == 0


def test_stop_hook_swallows_enqueue_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "notionmemory.hooks.session_stop.os.getcwd", lambda: str(tmp_path))

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
    from notionmemory.hooks import session_stop
    assert session_stop.main(harness="codex") == 0
