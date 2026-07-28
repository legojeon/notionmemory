"""git 로컬 큐 — 커밋당 파일 1개(파일명=해시), `key value` 헤더 + body 블록.

훅 셸 블록(hooks.py)이 쓰고 Python이 읽는다. 포맷/slug 를 바꾸면 양쪽을 함께 바꿀 것.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

QUEUE_ROOT_ENV = "NOTIONMEMORY_GITQUEUE_DIR"


def queue_root() -> Path:
    override = os.environ.get(QUEUE_ROOT_ENV)
    if override:
        return Path(override)
    return Path.home() / ".local" / "state" / "notionmemory" / "gitqueue"


def repo_slug(repo: str | Path) -> str:
    p = str(Path(repo))
    return f"{Path(p).name}-{hashlib.sha256(p.encode()).hexdigest()[:8]}"


def repo_queue_dir(repo: str | Path) -> Path:
    return queue_root() / repo_slug(repo)


def parse_entry(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    entry: dict = {"hash": path.name, "path": path, "repo": "", "branch": "",
                   "ts": "", "subject": "", "files": [], "body": ""}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line == "body":
            entry["body"] = "\n".join(lines[i + 1:]).strip()
            break
        key, _, val = line.partition(" ")
        if key == "files":
            entry["files"] = [f for f in val.split(",") if f]
        elif key in ("repo", "branch", "ts", "subject"):
            entry[key] = val
    if not entry["repo"] or not entry["subject"]:
        return None
    return entry


def list_entries(repo: str | Path | None = None) -> list[dict]:
    root = queue_root()
    if not root.is_dir():
        return []
    dirs = [repo_queue_dir(repo)] if repo else sorted(
        p for p in root.iterdir() if p.is_dir())
    out: list[dict] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(p for p in d.iterdir() if p.is_file()):
            e = parse_entry(f)
            if e:
                out.append(e)
    return out


def ack(hashes: list[str]) -> int:
    root = queue_root()
    if not root.is_dir():
        return 0
    targets, removed = set(hashes), 0
    for d in (p for p in root.iterdir() if p.is_dir()):
        for f in list(d.iterdir()):
            if f.name in targets:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        try:
            next(d.iterdir())
        except StopIteration:
            d.rmdir()
        except OSError:
            pass
    return removed


def queue_root_writable() -> bool:
    """큐 루트 생성 가능 여부 — 훅은 무조건 exit 0 이라 권한 문제를 조용히 삼키므로
    install/status 가 이 검사로 미리 경고한다 (e2e 발견: root 소유 ~/.local/state)."""
    try:
        queue_root().mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False
