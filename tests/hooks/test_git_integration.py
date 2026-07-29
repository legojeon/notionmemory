"""git 훅 통합: session_start 자동 설치 + save_reminder 큐 리마인더."""
import io
import json
import subprocess
import sys
from pathlib import Path

from notionmemory.core import paths
from notionmemory.hooks import save_reminder as sr_mod, session_start as ss_mod
from notionmemory.skills.git import hooks, queue

# tests/conftest.py's autouse `no_real_cli` fixture monkeypatches the shared
# subprocess.run (detection.subprocess is the same module object) to always
# return a stub CompletedProcess for every test. save_reminder tests below
# need a real `git` call, so capture the genuine subprocess.run here at
# import time — before any per-test fixture has a chance to patch it (same
# pattern as tests/skills/test_git_hooks.py).
_real_run = subprocess.run


def _write_cfg(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def _bare_repo(tmp_path, name="myrepo") -> Path:
    """git 리포처럼 보이는 디렉터리(.git/hooks 존재) — hooks.install/is_installed는
    서브프로세스를 쓰지 않으므로 실제 git init 없이 파일 구조만 갖추면 충분하다."""
    repo = tmp_path / name
    (repo / ".git" / "hooks").mkdir(parents=True)
    return repo


# ── session_start.maybe_install_git_hook ────────────────────────────

def test_maybe_install_auto_installs_and_announces(monkeypatch, tmp_path):
    ss = ss_mod
    repo = _bare_repo(tmp_path)
    cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(paths, "config_path", lambda p=cfg: p)
    _write_cfg(cfg, "skills: {}\n")

    note = ss.maybe_install_git_hook(str(repo))

    assert hooks.is_installed(repo) is True
    assert "installed a post-commit hook" in note
    # 전체 안내 문구까지 확인 — CLI 는 바뀌었지만(절대경로 → bare
    # "notionmemory"), 사용자가 그대로 따라 칠 수 있는 실행 커맨드가
    # 안내에 들어있는지는 여전히 검증한다.
    assert "notionmemory git uninstall" in note


def test_maybe_install_respects_exclude(monkeypatch, tmp_path):
    ss = ss_mod
    repo = _bare_repo(tmp_path)
    cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(paths, "config_path", lambda p=cfg: p)
    _write_cfg(cfg, f"skills:\n  git:\n    exclude:\n      - {repo}\n")

    note = ss.maybe_install_git_hook(str(repo))

    assert note == ""
    assert hooks.is_installed(repo) is False


def test_maybe_install_ask_policy_suggests_without_installing(monkeypatch, tmp_path):
    ss = ss_mod
    repo = _bare_repo(tmp_path)
    cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(paths, "config_path", lambda p=cfg: p)
    _write_cfg(cfg, "skills:\n  git:\n    install_policy: ask\n")

    note = ss.maybe_install_git_hook(str(repo))

    assert hooks.is_installed(repo) is False
    assert "Ask the user" in note
    assert "notionmemory git install" in note


def test_maybe_install_off_policy_returns_empty(monkeypatch, tmp_path):
    ss = ss_mod
    repo = _bare_repo(tmp_path)
    cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(paths, "config_path", lambda p=cfg: p)
    _write_cfg(cfg, "skills:\n  git:\n    install_policy: off\n")

    note = ss.maybe_install_git_hook(str(repo))

    assert note == ""
    assert hooks.is_installed(repo) is False


def test_maybe_install_already_installed_is_silent(monkeypatch, tmp_path):
    ss = ss_mod
    repo = _bare_repo(tmp_path)
    cfg = tmp_path / "config.yaml"
    _write_cfg(cfg, "skills: {}\n")
    hooks.install(repo, str(cfg))
    before = hooks.hook_path(repo).read_text(encoding="utf-8")
    monkeypatch.setattr(paths, "config_path", lambda p=cfg: p)

    note = ss.maybe_install_git_hook(str(repo))

    assert note == ""
    assert hooks.hook_path(repo).read_text(encoding="utf-8") == before


def test_maybe_install_non_git_toplevel_returns_empty(monkeypatch, tmp_path):
    ss = ss_mod
    cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(paths, "config_path", lambda p=cfg: p)

    assert ss.maybe_install_git_hook("") == ""


# ── session_start.git_queue_reminder ────────────────────────────────────

def _real_toplevel(repo: Path) -> str:
    return _real_run(
        ["git", "rev-parse", "--show-toplevel"], cwd=repo,
        capture_output=True, text=True, timeout=2).stdout.strip()


def _queue_entry(qdir: Path, chash: str, repo_top: str) -> None:
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / chash).write_text(
        f"repo {repo_top}\nbranch main\nts 2026-01-01T00:00:00Z\n"
        "subject test commit\nfiles a.py\nbody\n본문\n", encoding="utf-8")


def test_git_queue_reminder_counts_and_includes_procedure(monkeypatch, tmp_path):
    ss = ss_mod
    # config 격리 — 실 config 의 language 가 새면(사용자가 ko 로 두면) 리마인더가
    # 한국어로 나와 영어 단언이 깨진다. 빈 tmp config → 기본 en.
    monkeypatch.setattr(paths, "config_path", lambda: tmp_path / "config.yaml")
    monkeypatch.setattr(subprocess, "run", _real_run)
    repo = tmp_path / "myrepo"
    repo.mkdir()
    _real_run(["git", "init", "-q"], cwd=repo, check=True)
    top = _real_toplevel(repo)
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path / "gq"))
    qdir = queue.repo_queue_dir(top)
    _queue_entry(qdir, "aaa111", top)
    _queue_entry(qdir, "bbb222", top)

    note = ss.git_queue_reminder(top)

    assert "2 commit" in note
    # 전체 안내 커맨드까지 확인 — bare "notionmemory" 라는 이름만으로는
    # 거의 모든 문구에 걸리므로(near-vacuous), 실제 실행 가능한 전체
    # 커맨드 문구를 검증한다.
    assert "notionmemory git list" in note
    assert "notionmemory git ack" in note
    # 저장 여부와 무관하게 무가치 커밋도 ack로 큐를 비우라는 지시가 있어야 한다 —
    # 그렇지 않으면 사소한 커밋만 쌓인 큐가 매 세션 시작마다 영원히 재알림된다.
    assert "not worth remembering" in note


def test_git_queue_reminder_empty_queue_returns_empty(monkeypatch, tmp_path):
    ss = ss_mod
    monkeypatch.setattr(subprocess, "run", _real_run)
    repo = tmp_path / "myrepo"
    repo.mkdir()
    _real_run(["git", "init", "-q"], cwd=repo, check=True)
    top = _real_toplevel(repo)
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path / "gq"))

    assert ss.git_queue_reminder(top) == ""


def test_git_queue_reminder_needs_a_toplevel():
    """git 리포가 아니면 알릴 큐 자체가 없다 — 빈 문자열을 그대로 받는다."""
    assert ss_mod.git_queue_reminder("") == ""


def test_manual_capture_mode_suppresses_queue_reminder(monkeypatch, tmp_path):
    """manual 이면 `remember --auto` 가 거부된다 — 실행할 수 없는 일을 시키지 않는다."""
    ss = ss_mod
    cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(paths, "config_path", lambda p=cfg: p)
    _write_cfg(cfg, "skills:\n  memory:\n    capture_mode: manual\n")
    monkeypatch.setattr(subprocess, "run", _real_run)
    repo = tmp_path / "myrepo"
    repo.mkdir()
    _real_run(["git", "init", "-q"], cwd=repo, check=True)
    top = _real_toplevel(repo)
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path / "gq"))
    _queue_entry(queue.repo_queue_dir(top), "aaa111", top)

    assert ss.git_queue_reminder(top) == ""
    _write_cfg(cfg, "skills:\n  memory:\n    capture_mode: auto\n")
    assert "1 commit" in ss.git_queue_reminder(top)      # 전제: auto 면 나온다


def test_session_start_main_actually_emits_the_queue_reminder(monkeypatch, tmp_path, capsys):
    """배선 확인 — git_queue_reminder() 단위 테스트만으로는 main() 이 그것을
    호출하는지 알 수 없다(호출을 지워도 초록이었다)."""
    ss = ss_mod
    cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(paths, "config_path", lambda p=cfg: p)
    _write_cfg(cfg, "skills:\n  memory:\n    capture_mode: auto\n"
                    "  git:\n    install_policy: off\n")
    monkeypatch.setattr(subprocess, "run", _real_run)
    repo = tmp_path / "myrepo"
    repo.mkdir()
    _real_run(["git", "init", "-q"], cwd=repo, check=True)
    top = _real_toplevel(repo)
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path / "gq"))
    _queue_entry(queue.repo_queue_dir(top), "aaa111", top)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(repo)})))

    assert ss.main() == 0
    out = capsys.readouterr().out
    assert "this repo's queue has 1 commit" in out
    assert not out.lstrip().startswith(("[", "{"))   # JSON 스니핑 회피는 그대로
