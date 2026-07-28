import subprocess

import pytest

from notionmemory import cli
from notionmemory.skills.git import hooks, queue

# tests/conftest.py's autouse `no_real_cli` fixture monkeypatches the shared
# subprocess.run (detection.subprocess is the same module object) to always
# return a stub CompletedProcess for every test. This test needs real `git`
# calls, so capture the genuine subprocess.run here at import time — before
# any per-test fixture has a chance to patch it — and use that reference
# below (same pattern as tests/skills/test_git_hooks.py).
_real_run = subprocess.run


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "myrepo"
    r.mkdir()
    _real_run(["git", "init", "-q"], cwd=r, check=True)
    return r


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("skills: {}\n", encoding="utf-8")
    return str(p)


@pytest.fixture
def qroot(tmp_path, monkeypatch):
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path / "gq"))
    return tmp_path / "gq"


def test_cli_install_status_uninstall(repo, cfg, capsys):
    assert cli.main(["git", "install", str(repo), "--config", cfg]) == 0
    assert hooks.is_installed(repo)
    assert cli.main(["git", "status", "--config", cfg]) == 0
    assert str(repo.resolve()) in capsys.readouterr().out
    assert cli.main(["git", "uninstall", str(repo), "--config", cfg]) == 0
    assert not hooks.is_installed(repo)


def test_cli_install_non_repo_exit1(tmp_path, cfg, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert cli.main(["git", "install", str(plain), "--config", cfg]) == 1
    assert "git 리포" in capsys.readouterr().out


def test_cli_list_and_ack(qroot, capsys):
    d = queue.repo_queue_dir("/x/proj")
    d.mkdir(parents=True, exist_ok=True)
    (d / "abc123").write_text(
        "repo /x/proj\nbranch main\nts t\nsubject feat: z\nfiles a.py\nbody\n",
        encoding="utf-8")
    assert cli.main(["git", "list", "--all"]) == 0
    out = capsys.readouterr().out
    assert "abc123" in out and "feat: z" in out
    assert cli.main(["git", "ack", "abc123"]) == 0
    assert queue.list_entries() == []


def test_cli_list_from_subdir_uses_git_toplevel(repo, qroot, monkeypatch, capsys):
    # no_real_cli(autouse) 는 detection.subprocess.run(전역 subprocess 모듈)을
    # 스텁으로 바꿔둔다. `git rev-parse --show-toplevel` 이 실제로 실행되어야
    # 이 테스트의 취지(하위 디렉터리에서도 리포 toplevel 을 찾는지)를 검증할 수
    # 있으므로, 이 테스트 동안만 실제 subprocess.run 을 복원한다.
    monkeypatch.setattr(cli.subprocess, "run", _real_run)

    sub = repo / "sub"
    sub.mkdir()

    d = queue.repo_queue_dir(str(repo.resolve()))
    d.mkdir(parents=True, exist_ok=True)
    (d / "def456").write_text(
        f"repo {repo.resolve()}\nbranch main\nts t\nsubject feat: y\nfiles a.py\nbody\n",
        encoding="utf-8")

    monkeypatch.chdir(sub)
    assert cli.main(["git", "list"]) == 0
    out = capsys.readouterr().out
    assert "def456" in out


def test_cli_flush_delegates(monkeypatch, cfg, qroot):
    called = {}
    monkeypatch.setattr(cli, "gc_flush",
                        lambda config, log, repo="": called.setdefault("code", 2))
    assert cli.main(["git", "flush", "--config", cfg]) == 2
    assert called["code"] == 2


def test_cli_install_warns_when_queue_root_unwritable(repo, cfg, tmp_path,
                                                      monkeypatch, capsys):
    """e2e 발견(2026-07-20): 큐 루트 권한 불가 시 훅이 조용히 죽는다 — install이 경고해야 한다."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(blocked / "gitqueue"))
    try:
        assert cli.main(["git", "install", str(repo), "--config", cfg]) == 0
        out = capsys.readouterr().out
        assert "경고" in out and "gitqueue" in out
    finally:
        blocked.chmod(0o700)


def test_cli_install_no_warning_when_queue_root_writable(repo, cfg, qroot, capsys):
    assert cli.main(["git", "install", str(repo), "--config", cfg]) == 0
    assert "경고" not in capsys.readouterr().out


def test_cli_uninstall_all_strips_every_registered_repo(tmp_path, cfg, qroot, capsys):
    repos = []
    for name in ("r1", "r2"):
        r = tmp_path / name
        r.mkdir()
        _real_run(["git", "init", "-q"], cwd=r, check=True)
        assert cli.main(["git", "install", str(r), "--config", cfg]) == 0
        repos.append(r)
    capsys.readouterr()
    assert cli.main(["git", "uninstall", "--all", "--config", cfg]) == 0
    out = capsys.readouterr().out
    for r in repos:
        assert not hooks.is_installed(r)
        assert str(r.resolve()) in out
    from notionmemory.core.config import Config
    opts = Config.load(cfg).skill_options("git")
    assert opts.get("repos") == []
    assert {str(r.resolve()) for r in repos} <= set(opts.get("exclude") or [])
