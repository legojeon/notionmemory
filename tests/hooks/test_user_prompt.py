"""UserPromptSubmit 훅 — 로컬 memory 색인만 검색(네트워크 0), 관련성 게이트를
넘을 때만 힌트, 아니면 완전 침묵. Second Brain v2 Phase 2b Task 3.
"""
from __future__ import annotations

import ast
import io
import json
from pathlib import Path

import pytest

from notionmemory.hooks import user_prompt


_FIXED_INDEX = {
    "mem_1": {
        "title": "쿠버네티스 삭제 순서",
        "concepts": ["kubernetes", "삭제"],
        "excerpt": "네임스페이스보다 리소스를 먼저 지워야 finalizer 가 걸리지 않는다.",
        "strength": 8,
        "type": "decision",
        "project": "",
        "status": "Active",
    },
}


def _payload(prompt: str, cwd: str = ".") -> str:
    return json.dumps({"prompt": prompt, "cwd": cwd})


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    # resolve_project 이 git 리포를 실제로 훑지 않도록 결정적으로 만든다 — 관련성
    # 판정 자체와는 무관하다(색인 항목의 project="" 라 어떤 project 와도 매칭).
    monkeypatch.setattr(
        "notionmemory.hooks.session_start.subprocess.run",
        lambda *a, **k: type("R", (), {"returncode": 1, "stdout": ""})())


def test_relevant_prompt_yields_hint_with_matching_title(monkeypatch, capsys):
    monkeypatch.setattr(user_prompt.mem_index, "load", lambda: _FIXED_INDEX)
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload("쿠버네티스 리소스 삭제 순서가 뭐였지")))
    assert user_prompt.main() == 0
    out = capsys.readouterr().out
    assert "쿠버네티스 삭제 순서" in out
    assert out and out[0] not in "[{"


def test_irrelevant_prompt_is_silent(monkeypatch, capsys):
    monkeypatch.setattr(user_prompt.mem_index, "load", lambda: _FIXED_INDEX)
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload("오늘 날씨 어때")))
    assert user_prompt.main() == 0
    assert capsys.readouterr().out == ""


def test_empty_index_is_silent(monkeypatch, capsys):
    monkeypatch.setattr(user_prompt.mem_index, "load", lambda: {})
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload("아무 메시지")))
    assert user_prompt.main() == 0
    assert capsys.readouterr().out == ""


def test_raising_search_is_swallowed_and_returns_zero(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(user_prompt.mem_index, "load", lambda: _FIXED_INDEX)
    monkeypatch.setattr(user_prompt.mem_index, "search", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload("아무거나")))
    assert user_prompt.main() == 0
    assert capsys.readouterr().out == ""


def test_bad_stdin_is_swallowed_and_returns_zero(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert user_prompt.main() == 0
    assert capsys.readouterr().out == ""


def test_accepts_harness_kwarg(monkeypatch, capsys):
    monkeypatch.setattr(user_prompt.mem_index, "load", lambda: {})
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload("아무거나")))
    assert user_prompt.main(harness="codex") == 0


def test_hook_never_imports_network_modules():
    """`import`/`from ... import` 문에 notion_client/requests/agent_runtime 이 없어야
    한다 — 이 훅은 로컬 색인만 보는 것이 계약이다(session_stop 의 AST 가드와 같은
    패턴). session_start 를 임포트하는 건 허용된다 — session_start 모듈 자체의
    최상위 import 문에는 네트워크 모듈이 없다(함수 본문 안에서만 지연 임포트한다)."""
    forbidden = ("notion_client", "requests", "agent_runtime")
    src = Path(user_prompt.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(any(f in n.name for f in forbidden) for n in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module and any(f in node.module for f in forbidden))
