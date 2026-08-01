"""cwd → git 프로젝트 식별 (toplevel/이름).

원래 `hooks/session_start.py` 안에 있던 로직이다 — SessionStart/Stop/UserPromptSubmit
훅들이 세션 컨텍스트를 "이 리포 프로젝트"로 스코프하기 위해 썼다. `transcripts.
collect_excerpts`(I2 — codex 세션의 project-level cwd 가드)도 같은 판정이 필요해졌는데,
skill 코드(`notionmemory/skills/memory`)가 `notionmemory/hooks`를 임포트하면 계층이
거꾸로 된다(훅은 skill 위에 얹히는 얇은 어댑터여야 한다) — 그래서 이 얇은 판정만
core로 옮겨 양쪽이 공유한다. `hooks/session_start.py`는 하위호환을 위해 이 모듈에서
그대로 재-임포트한다(기존 `session_start.resolve_toplevel`/`resolve_project` monkeypatch
가 계속 동작해야 한다)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def resolve_toplevel(cwd: str) -> str:
    """git toplevel 절대경로, git 리포가 아니거나 실패하면 ""."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=cwd or None,
            capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:
        return ""


def resolve_project(cwd: str) -> str:
    """git toplevel basename, 실패 시 cwd basename."""
    top = resolve_toplevel(cwd)
    if top:
        return Path(top).name
    return Path(cwd or ".").resolve().name
