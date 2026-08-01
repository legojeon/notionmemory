"""core/projects.py — cwd → git 프로젝트 식별. hooks/session_start.py 에서 옮겨온
로직(I2, review wave) — transcripts.collect_excerpts 도 같은 판정을 쓰게 하려고
core 로 이전했다. 기존 hooks 쪽 회귀 가드(tests/hooks/test_hook_cli.py)는 재-임포트
경로를 통해 그대로 유지된다 — 여기서는 core 모듈 자체를 직접 검증한다."""
from __future__ import annotations

import subprocess

from notionmemory.core import projects


def test_resolve_project_prefers_git_toplevel(monkeypatch):
    monkeypatch.setattr(
        projects.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 0, stdout="/Users/x/myrepo\n", stderr=""))
    assert projects.resolve_project("/Users/x/myrepo/sub") == "myrepo"


def test_resolve_project_falls_back_to_cwd_basename(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("no git")
    monkeypatch.setattr(projects.subprocess, "run", boom)
    assert projects.resolve_project(str(tmp_path)) == tmp_path.name


def test_resolve_toplevel_returns_empty_on_failure(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("no git")
    monkeypatch.setattr(projects.subprocess, "run", boom)
    assert projects.resolve_toplevel("/anywhere") == ""
