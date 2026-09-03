"""SessionStart memory 섹션 — 프로젝트 브리프 + 고Strength Active 메모리 주입 +
미정리 초안(consolidation) nudge (Second Brain v2 Phase 2a, Task 5).

이 섹션은 옛 `recall --project`(최근5, 서브프로세스) 를 대체한다: 브리프 우선 →
고Strength 보강 → pending nudge. 세션당 Notion 왕복 1회까지 허용하되(브리프/
top_memories 조회), 실패/오프라인이면 무조건 조용히 무시한다(세션 시작을 막지
않는다는 훅 전역 계약)."""
import io
import json
import sys

import pytest

from notionmemory.hooks import session_start


class _FakeStore:
    def __init__(self, brief="", top=None):
        self._brief = brief
        self._top = top or []

    def project_brief(self, project):
        return self._brief

    def top_memories(self, project, *, min_strength, limit):
        return self._top


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(session_start, "resolve_toplevel", lambda cwd: "")
    monkeypatch.setattr(session_start, "maybe_install_git_hook", lambda top: "")
    monkeypatch.setattr(session_start, "templates_injection", lambda: "")
    monkeypatch.setattr(session_start, "library_injection", lambda: "")
    monkeypatch.setattr(session_start, "onboarding_injection", lambda: "")
    monkeypatch.setattr(session_start, "harness_wiring_injection", lambda: "")
    monkeypatch.setattr(session_start, "memory_index_injection", lambda: "")
    monkeypatch.setattr(session_start.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 1, "stdout": ""})())
    monkeypatch.setattr(session_start, "_memory_store", lambda config: _FakeStore())
    monkeypatch.setattr(session_start.cq, "list_jobs", lambda: [])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    return tmp_path


def test_brief_present_is_injected(monkeypatch, capsys):
    monkeypatch.setattr(session_start, "_memory_store",
                        lambda config: _FakeStore(brief="핵심 결정: X 채택"))
    assert session_start.main() == 0
    out = capsys.readouterr().out
    assert "핵심 결정: X 채택" in out
    assert not out.lstrip().startswith(("[", "{"))


def test_brief_absent_but_high_strength_present_is_injected(monkeypatch, capsys):
    monkeypatch.setattr(
        session_start, "_memory_store",
        lambda config: _FakeStore(top=[{"title": "JWT 만료 정책", "strength": 9}]))
    assert session_start.main() == 0
    out = capsys.readouterr().out
    assert "JWT 만료 정책" in out and "9" in out


def test_neither_brief_nor_high_strength_is_silent(capsys):
    assert session_start.main() == 0
    assert capsys.readouterr().out == ""


def test_pending_drafts_append_consolidate_nudge(monkeypatch, capsys):
    monkeypatch.setattr(session_start.cq, "list_jobs", lambda: [
        {"id": "a", "project": "proj"}, {"id": "c", "project": "other"}])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": "/x/proj"})))
    assert session_start.main() == 0
    out = capsys.readouterr().out
    # 개수 주장 없음(count-free wording) — 실제 draft 수가 아니라 job 존재 여부만 반영.
    assert "unconsolidated memory activity" in out and "memory consolidate" in out


def test_pending_drafts_nudge_is_korean_when_configured(monkeypatch, capsys, tmp_path):
    from notionmemory.core import config as cfg, paths
    cfg.save_language(str(paths.config_path()), "ko")
    monkeypatch.setattr(session_start.cq, "list_jobs",
                        lambda: [{"id": "a", "project": "proj"}])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": "/x/proj"})))
    assert session_start.main() == 0
    out = capsys.readouterr().out
    assert "미정리 항목" in out and "memory consolidate" in out


def test_notion_error_is_silent_no_raise(monkeypatch, capsys):
    def boom(config):
        raise RuntimeError("Notion 토큰이 없습니다")
    monkeypatch.setattr(session_start, "_memory_store", boom)
    assert session_start.main() == 0
    assert capsys.readouterr().out == ""


def test_notion_error_and_pending_drafts_coexist_nudge_still_fires(monkeypatch, capsys):
    """fix round 1 — Notion 왕복(브리프/top_memories)이 죽어도 pending nudge 는
    로컬(consolidation_queue)만 보므로 독립적으로 살아남아야 한다. 두 try/except
    를 나눈 이유가 정확히 이거다."""
    def boom(config):
        raise RuntimeError("offline")
    monkeypatch.setattr(session_start, "_memory_store", boom)
    monkeypatch.setattr(session_start.cq, "list_jobs",
                        lambda: [{"id": "a", "project": "proj"}])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": "/x/proj"})))
    assert session_start.main() == 0
    out = capsys.readouterr().out
    assert "memory consolidate" in out
    assert "브리프" not in out and "brief" not in out.lower()


def test_brief_and_pending_nudge_can_coexist(monkeypatch, capsys):
    monkeypatch.setattr(session_start, "_memory_store",
                        lambda config: _FakeStore(brief="브리프 본문"))
    monkeypatch.setattr(session_start.cq, "list_jobs",
                        lambda: [{"id": "a", "project": "proj"}])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": "/x/proj"})))
    assert session_start.main() == 0
    out = capsys.readouterr().out
    assert "브리프 본문" in out
    assert "memory consolidate" in out


def test_catalog_has_memory_pending_consolidation_key_en_and_ko():
    from notionmemory.core import messages
    assert "hook.memory_pending_consolidation" in messages.CATALOG["en"]
    assert "hook.memory_pending_consolidation" in messages.CATALOG["ko"]


def test_hook_noop_under_consolidate_guard(monkeypatch, capsys):
    monkeypatch.setenv("NOTIONMEMORY_CONSOLIDATE", "1")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert session_start.main() == 0
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
    assert session_start.main() == 0
    assert stdin.read_called is True


# ── SessionStart 폴백 스폰 — autorun.maybe_spawn(sys.argv[0]), 모든 주입 뒤 별도 try ──

def test_fallback_spawn_calls_autorun_with_cli_path(monkeypatch):
    from notionmemory.skills.memory import autorun
    calls = []
    monkeypatch.setattr(autorun, "maybe_spawn", lambda cli: calls.append(cli) or True)
    assert session_start.main() == 0
    assert calls == [sys.argv[0]]


def test_fallback_spawn_skipped_under_consolidate_guard(monkeypatch):
    from notionmemory.skills.memory import autorun
    monkeypatch.setenv("NOTIONMEMORY_CONSOLIDATE", "1")
    monkeypatch.setattr(autorun, "maybe_spawn",
                        lambda cli: pytest.fail("guarded — must not spawn"))
    assert session_start.main() == 0


def test_fallback_spawn_failure_does_not_break_injection(monkeypatch, capsys):
    """스폰이 던져도 그 앞 섹션들의 주입은 이미 출력된 채로 살아남는다(격리된 try)."""
    from notionmemory.skills.memory import autorun

    def boom(cli):
        raise RuntimeError("spawn boom")

    monkeypatch.setattr(autorun, "maybe_spawn", boom)
    monkeypatch.setattr(session_start, "_memory_store",
                        lambda config: _FakeStore(brief="브리프 생존"))
    assert session_start.main() == 0
    assert "브리프 생존" in capsys.readouterr().out


def test_injection_failure_does_not_break_fallback_spawn(monkeypatch):
    """주입 섹션이 던져도(예: templates_injection 실패) 폴백 스폰은 별도 try 라
    영향받지 않고 여전히 호출된다."""
    from notionmemory.skills.memory import autorun
    calls = []
    monkeypatch.setattr(autorun, "maybe_spawn", lambda cli: calls.append(cli) or True)

    def boom():
        raise RuntimeError("injection boom")

    monkeypatch.setattr(session_start, "templates_injection", boom)
    assert session_start.main() == 0
    assert calls == [sys.argv[0]]
