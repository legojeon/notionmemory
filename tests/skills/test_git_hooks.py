import subprocess
from pathlib import Path

import pytest

from notionmemory.skills.git import hooks, queue

# tests/conftest.py's autouse `no_real_cli` fixture monkeypatches the shared
# subprocess.run (detection.subprocess is the same module object) to always
# return a stub CompletedProcess for every test. This test needs real `git`
# calls, so capture the genuine subprocess.run here at import time — before
# any per-test fixture has a chance to patch it — and use that reference
# below (same pattern as tests/web/test_app_js.py).
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


def _hook(repo: Path) -> Path:
    return repo / ".git" / "hooks" / "post-commit"


def test_install_fresh_and_idempotent(repo, cfg):
    assert hooks.install(repo, cfg) is True
    text = _hook(repo).read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh")
    assert hooks.MARKER_BEGIN in text and hooks.MARKER_END in text
    assert _hook(repo).stat().st_mode & 0o111
    assert hooks.install(repo, cfg) is False          # 멱등
    assert text == _hook(repo).read_text(encoding="utf-8")


def test_install_chains_foreign_hook(repo, cfg):
    _hook(repo).parent.mkdir(parents=True, exist_ok=True)
    _hook(repo).write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    hooks.install(repo, cfg)
    text = _hook(repo).read_text(encoding="utf-8")
    assert "echo mine" in text and hooks.MARKER_BEGIN in text
    assert text.index("echo mine") < text.index(hooks.MARKER_BEGIN)


def test_install_replaces_stale_block(repo, cfg):
    hooks.install(repo, cfg)
    stale = _hook(repo).read_text(encoding="utf-8").replace("gitqueue", "oldqueue")
    _hook(repo).write_text(stale, encoding="utf-8")
    assert hooks.install(repo, cfg) is True
    text = _hook(repo).read_text(encoding="utf-8")
    assert "oldqueue" not in text and text.count(hooks.MARKER_BEGIN) == 1


def test_registry_and_status(repo, cfg):
    hooks.install(repo, cfg)
    rows = hooks.status(cfg)
    assert rows == [{"repo": str(repo.resolve()), "exists": True, "installed": True}]


def test_uninstall_keeps_foreign_and_excludes(repo, cfg):
    _hook(repo).parent.mkdir(parents=True, exist_ok=True)
    _hook(repo).write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    hooks.install(repo, cfg)
    hooks.uninstall(repo, cfg)
    text = _hook(repo).read_text(encoding="utf-8")
    assert "echo mine" in text and hooks.MARKER_BEGIN not in text
    from notionmemory.core.config import Config
    opts = Config.load(cfg).skill_options("git")
    assert str(repo.resolve()) in (opts.get("exclude") or [])
    assert str(repo.resolve()) not in (opts.get("repos") or [])


LEGACY_BEGIN = "# >>> notionmemory git-capture >>>"
LEGACY_END = "# <<< notionmemory git-capture <<<"


def _legacy_block() -> str:
    return LEGACY_BEGIN + "\n(echo legacy-capture-body)\n" + LEGACY_END


def test_is_installed_detects_legacy_marker(repo, cfg):
    _hook(repo).parent.mkdir(parents=True, exist_ok=True)
    _hook(repo).write_text("#!/bin/sh\n\n" + _legacy_block() + "\n", encoding="utf-8")
    assert hooks.is_installed(repo) is True


def test_uninstall_removes_legacy_marker_entirely(repo, cfg):
    _hook(repo).parent.mkdir(parents=True, exist_ok=True)
    _hook(repo).write_text("#!/bin/sh\n\n" + _legacy_block() + "\n", encoding="utf-8")
    hooks.uninstall(repo, cfg)
    assert not _hook(repo).exists() or "notionmemory" not in _hook(repo).read_text(encoding="utf-8")


def test_install_replaces_legacy_marker_with_single_new_block(repo, cfg):
    _hook(repo).parent.mkdir(parents=True, exist_ok=True)
    _hook(repo).write_text("#!/bin/sh\n\n" + _legacy_block() + "\n", encoding="utf-8")
    hooks.install(repo, cfg)
    text = _hook(repo).read_text(encoding="utf-8")
    assert LEGACY_BEGIN not in text and "legacy-capture-body" not in text
    assert text.count(hooks.MARKER_BEGIN) == 1


def test_uninstall_keeps_foreign_hook_with_legacy_marker(repo, cfg):
    _hook(repo).parent.mkdir(parents=True, exist_ok=True)
    _hook(repo).write_text(
        "#!/bin/sh\necho mine\n\n" + _legacy_block() + "\n", encoding="utf-8")
    hooks.uninstall(repo, cfg)
    text = _hook(repo).read_text(encoding="utf-8")
    assert "echo mine" in text
    assert LEGACY_BEGIN not in text and "notionmemory" not in text


def test_installed_hook_queues_commit(repo, cfg, tmp_path, monkeypatch):
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path / "gq"))
    hooks.install(repo, cfg)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "NOTIONMEMORY_GITQUEUE_DIR": str(tmp_path / "gq"), "PATH": "/usr/bin:/bin"}
    _real_run(["git", "add", "a.py"], cwd=repo, check=True)
    _real_run(["git", "commit", "-q", "-m", "feat: 첫 커밋\n\n상세 본문"],
              cwd=repo, check=True, env=env)
    entries = queue.list_entries(repo.resolve())
    assert len(entries) == 1
    e = entries[0]
    assert e["subject"] == "feat: 첫 커밋"
    assert e["files"] == ["a.py"] and "상세 본문" in e["body"]
