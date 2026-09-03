"""SessionStart memory 색인 넛지 — 로컬 색인 파일만 보고 판정(네트워크 0).
memory DB 가 바인딩돼 있고 색인이 비어 있으면(파일 없음/0건) reindex 안내, 색인이
있으면 침묵. memory 가 아예 바인딩돼 있지 않으면(Fix round 1) 색인 상태와 무관하게
항상 침묵한다 — 안 그러면 `onboarding_injection`의 "Notion 미연결/memory 미설정"
안내 바로 아래 즉시 실패하는(`reindex`는 바인딩된 DB가 없으면 죽는다) 죽은 명령을
또 얹게 된다. en/ko 파리티는
`test_onboarding_cli_i18n.py::test_catalog_en_ko_keysets_identical_and_nonempty`
가 강제한다."""
import io
import json

import pytest

from notionmemory.core import paths
from notionmemory.core.config import Config, SkillMeta
from notionmemory.hooks import session_start
from notionmemory.skills.memory import mem_index


def _bind_memory() -> None:
    """config 에 memory database_id 를 직접 심는다(네트워크 0) — `status.probe`가
    읽는 바로 그 값이라 실제 바인딩 판정 경로를 그대로 탄다."""
    config = Config.load(str(paths.config_path()))
    SkillMeta(config, "memory").set_meta("database_id", "1" * 32)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(session_start, "resolve_toplevel", lambda cwd: "")
    monkeypatch.setattr(session_start, "maybe_install_git_hook", lambda top: "")
    monkeypatch.setattr(session_start, "memory_injection", lambda project: "")
    monkeypatch.setattr(session_start, "templates_injection", lambda: "")
    monkeypatch.setattr(session_start, "library_injection", lambda: "")
    monkeypatch.setattr(session_start, "onboarding_injection", lambda: "")
    monkeypatch.setattr(session_start, "harness_wiring_injection", lambda: "")
    monkeypatch.setattr(session_start.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 1, "stdout": ""})())
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    # memory 는 기본 미바인딩(fresh HOME) — 바인딩이 필요한 테스트는 _bind_memory() 를
    # 명시적으로 부른다.
    return tmp_path


def test_unbound_memory_is_silent_even_with_missing_index(capsys):
    assert not mem_index.index_path().is_file()
    assert session_start.main() == 0
    out = capsys.readouterr().out
    assert "reindex" not in out


def test_unbound_memory_is_silent_even_with_empty_saved_index(capsys):
    mem_index.save({})
    assert session_start.main() == 0
    out = capsys.readouterr().out
    assert "reindex" not in out


def test_bound_missing_index_file_injects_reindex_nudge(capsys):
    _bind_memory()
    assert not mem_index.index_path().is_file()
    assert session_start.main() == 0
    out = capsys.readouterr().out
    assert "reindex" in out


def test_bound_populated_index_is_silent(capsys):
    _bind_memory()
    idx = mem_index.build([
        {"id": "mem_1", "title": "x", "content": "y", "type": "decision",
         "status": "Active"},
    ])
    mem_index.save(idx)
    session_start.main()
    out = capsys.readouterr().out
    assert "reindex" not in out


def test_bound_empty_but_present_index_file_still_nudges(capsys):
    _bind_memory()
    mem_index.save({})
    assert mem_index.index_path().is_file()
    session_start.main()
    out = capsys.readouterr().out
    assert "reindex" in out


def test_bound_v2_index_with_zero_docs_still_nudges(capsys):
    """v2 인덱스는 항상 최상위 dict(version/meta/docs)라 `not idx` 로는 "비어 있음"을
    못 잡는다(docs 가 0건이어도 dict 자체는 truthy) — `mem_index.count(idx) == 0` 으로
    판정해야 한다(회귀 가드, Task 3)."""
    _bind_memory()
    mem_index.save(mem_index.build([]))
    assert mem_index.index_path().is_file()
    assert mem_index.count(mem_index.load()) == 0
    session_start.main()
    out = capsys.readouterr().out
    assert "reindex" in out


def test_injection_makes_no_network_call(monkeypatch, capsys):
    import requests

    def explode(*a, **k):
        raise AssertionError("SessionStart memory 색인 넛지가 네트워크를 호출했다")

    monkeypatch.setattr(requests, "request", explode)
    monkeypatch.setattr(requests, "get", explode)
    _bind_memory()
    assert session_start.main() == 0


def test_memory_index_nudge_language(monkeypatch):
    from notionmemory.core import config as cfg
    _bind_memory()
    cfg.save_language(str(paths.config_path()), "en")
    assert "reindex" in session_start.memory_index_injection()
    cfg.save_language(str(paths.config_path()), "ko")
    assert "색인" in session_start.memory_index_injection()
