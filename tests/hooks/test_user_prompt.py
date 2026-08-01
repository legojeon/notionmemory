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
from notionmemory.skills.memory import mem_index


# v2 색인(mem_index.build 산출물, BM25 척도) — mem_1 은 title/concepts 가 쿼리와
# 다중 토큰으로 겹쳐 게이트(기본 min_score=1.0)를 여유 있게 넘는다(score ≈8.2, 실측).
# mem_2~4 는 서로 다른 제목/무관한 내용이지만 "회의" 한 단어만 content 에 1회
# 등장한다 — df 가 3/4 문서로 높아 idf 가 작고, 그 단어 하나만 매칭되는 쿼리는
# 부스트 후에도 score ≈0.38 로 게이트(1.0) 아래 머문다(공용어 1회 매치가 침묵해야
# 한다는 계약, 실측 확인).
_MEMORIES = [
    {"id": "mem_1", "title": "쿠버네티스 삭제 순서", "concepts": ["kubernetes", "삭제"],
     "content": "네임스페이스보다 리소스를 먼저 지워야 finalizer가 걸리지 않는다.",
     "strength": 8, "type": "decision", "project": "", "status": "Active"},
    {"id": "mem_2", "title": "월간 정산 문서", "concepts": [],
     "content": "회의 관련 간단한 메모입니다.",
     "strength": 0, "type": "fact", "project": "", "status": "Active"},
    {"id": "mem_3", "title": "분기 실적 요약", "concepts": [],
     "content": "회의 관련 간단한 메모입니다.",
     "strength": 0, "type": "fact", "project": "", "status": "Active"},
    {"id": "mem_4", "title": "연간 예산 계획", "concepts": [],
     "content": "회의 관련 간단한 메모입니다.",
     "strength": 0, "type": "fact", "project": "", "status": "Active"},
]
_FIXED_INDEX = mem_index.build(_MEMORIES)


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
    """제목+concepts 에 다중 토큰이 겹치는 프롬프트 — BM25 게이트(1.0)를 넉넉히
    넘어 힌트 한 줄이 나온다."""
    monkeypatch.setattr(user_prompt.mem_index, "load", lambda: _FIXED_INDEX)
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload("쿠버네티스 삭제 순서 다시 알려줘")))
    assert user_prompt.main() == 0
    out = capsys.readouterr().out
    assert "쿠버네티스 삭제 순서" in out
    assert out and out[0] not in "[{"


def test_irrelevant_prompt_is_silent(monkeypatch, capsys):
    """어느 문서와도 토큰이 겹치지 않는 프롬프트 — 매치 0건, 완전 침묵."""
    monkeypatch.setattr(user_prompt.mem_index, "load", lambda: _FIXED_INDEX)
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload("오늘 날씨 예보 확인해줘")))
    assert user_prompt.main() == 0
    assert capsys.readouterr().out == ""


def test_weak_common_word_match_is_silent(monkeypatch, capsys):
    """content 에만 1회 등장하는 공용어("회의")가 여러 문서에 흩어져 있어 idf 가
    낮다 — BM25 score(≈0.38)가 게이트(1.0) 아래라 침묵해야 한다."""
    monkeypatch.setattr(user_prompt.mem_index, "load", lambda: _FIXED_INDEX)
    monkeypatch.setattr("sys.stdin", io.StringIO(_payload("회의 내용 뭐였지")))
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


def test_hook_noop_under_consolidate_guard(monkeypatch, capsys):
    monkeypatch.setenv("NOTIONMEMORY_CONSOLIDATE", "1")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert user_prompt.main() == 0
    assert capsys.readouterr().out == ""


def test_hook_reads_stdin_before_consolidate_guard_noop(monkeypatch):
    """M6 — 재귀 가드로 no-op 하더라도 stdin 은 이미 소비돼 있어야 한다."""
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
    assert user_prompt.main() == 0
    assert stdin.read_called is True


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
