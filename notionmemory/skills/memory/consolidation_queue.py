"""memory consolidation 로컬 큐 — 프로젝트 1개당 job(파일명=project 의 결정적 해시).

`notionmemory/skills/git/queue.py` 와 같은 모양(env override → 파일 기반
enqueue/list/ack). Stop 훅(비블로킹, agent_runtime 미사용)이 쓰고, 나중에
(Task 4) `notionmemory memory consolidate` 가 드레인한다 — 이 모듈 자체는 LLM
pass 를 전혀 모른다.

**fix round 2(final review)**: `enqueue` 는 예전엔 매 호출마다 uuid4 파일을 새로
찍어 세션 종료마다(읽기전용 세션 포함) 잡이 하나씩 쌓였다 — SessionStart 넛지가
"미정리 Draft 개수"인 양 잡 개수를 세면서 실제 draft 수와 무관하게 부풀었다. 이제
파일명을 `project` 문자열의 결정적 해시로 고정해, 같은 프로젝트에서 반복되는 Stop
은 기존 잡을 최신 cwd/ts 로 덮어쓸 뿐 새 파일을 만들지 않는다 — 프로젝트당 잡 ≤1개."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def _job_filename(project: str) -> str:
    """project 문자열의 결정적 해시 → 같은 프로젝트는 항상 같은 파일(dedup)."""
    return hashlib.sha256(project.encode("utf-8")).hexdigest()

QUEUE_ROOT_ENV = "NOTIONMEMORY_MEMQUEUE_DIR"


def queue_root() -> Path:
    override = os.environ.get(QUEUE_ROOT_ENV)
    if override:
        return Path(override)
    return Path.home() / ".local" / "state" / "notionmemory" / "memqueue"


def queue_root_writable() -> bool:
    """큐 루트 생성 가능 여부 — git 큐와 동일한 이유(권한 문제를 조용히 삼키는
    훅 대신 install/status 가 미리 경고할 수 있도록)."""
    try:
        queue_root().mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def enqueue(project: str, cwd: str, ts: str) -> None:
    """프로젝트당 잡 1개로 dedup — 같은 project 로 반복 호출하면 기존 잡을 최신
    cwd/ts 로 덮어쓸 뿐, 파일이 늘지 않는다(파일명 = project 의 결정적 해시)."""
    root = queue_root()
    root.mkdir(parents=True, exist_ok=True)
    job_id = _job_filename(project)
    payload = {"id": job_id, "project": project, "cwd": cwd, "ts": ts}
    (root / job_id).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _parse_job(path: Path) -> dict | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    return raw


def list_jobs() -> list[dict]:
    root = queue_root()
    if not root.is_dir():
        return []
    out: list[dict] = []
    for f in sorted(p for p in root.iterdir() if p.is_file()):
        job = _parse_job(f)
        if job:
            out.append(job)
    return out


def ack(ids: list[str]) -> int:
    root = queue_root()
    if not root.is_dir():
        return 0
    targets, removed = set(ids), 0
    for f in list(root.iterdir()):
        if f.is_file() and f.name in targets:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed
