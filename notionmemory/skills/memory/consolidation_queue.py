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


MAX_SESSIONS = 10


def enqueue(project: str, cwd: str, ts: str, session: dict | None = None) -> None:
    """프로젝트당 잡 1개 dedup(기존) + `sessions` 병합-upsert.

    같은 session_id 는 최신 항목으로 갱신(세션당 1항목 — Stop 은 매 턴 발화한다),
    ts 오름차순 최대 MAX_SESSIONS 개만 보존해 consolidate 를 오래 못 돌려도 큐가
    무한히 자라지 않는다. 구버전 잡 파일(sessions 없음)은 빈 목록으로 읽힌다."""
    root = queue_root()
    root.mkdir(parents=True, exist_ok=True)
    job_id = _job_filename(project)
    existing = _parse_job(root / job_id) or {}
    sessions = [s for s in existing.get("sessions") or [] if isinstance(s, dict)]
    if session and session.get("session_id") and session.get("transcript_path"):
        sessions = [s for s in sessions if s.get("session_id") != session["session_id"]]
        sessions.append(dict(session))
        sessions.sort(key=lambda s: str(s.get("ts", "")))
        sessions = sessions[-MAX_SESSIONS:]
    payload = {"id": job_id, "project": project, "cwd": cwd, "ts": ts,
               "sessions": sessions}
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


def ack_sessions(job_id: str, mined_session_ids, seen_ts: str) -> None:
    """compare-and-delete ack(M1) — `ack()`처럼 무조건 파일을 지우지 않는다.

    consolidate 가 이 잡의 세션 목록을 스냅샷해 LLM 패스(최대 600초)를 도는 동안,
    같은 프로젝트에서 새 Stop 이 발화해 `enqueue()`가 이 파일을 다시 쓸 수 있다
    (`ts`가 갱신되고 새 세션이 `sessions`에 추가된다). 그 시점에 `ack()`로 파일을
    통째로 unlink 하면 그 사이 끼어든 새 세션 엔트리까지 함께 사라진다 — 그래서
    여기서 ack 시점에 파일을 다시 읽어 `ts`를 스냅샷 때 값(`seen_ts`)과 비교한다:

    - 안 바뀌었으면(아무도 안 건드림) 기존과 동일하게 통째로 지운다.
    - 바뀌었으면 이번에 실제로 처리한 `mined_session_ids`만 `sessions`에서 제거하고
      나머지(레이스로 새로 들어온 것)는 남긴 채 다시 쓴다 — 남는 게 없으면 그때는
      지운다.
    """
    root = queue_root()
    path = root / job_id
    current = _parse_job(path)
    if current is None:
        return
    if current.get("ts") == seen_ts:
        try:
            path.unlink()
        except OSError:
            pass
        return
    mined = set(mined_session_ids)
    remaining = [s for s in (current.get("sessions") or [])
                if isinstance(s, dict) and s.get("session_id") not in mined]
    if not remaining:
        try:
            path.unlink()
        except OSError:
            pass
        return
    payload = dict(current)
    payload["sessions"] = remaining
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
