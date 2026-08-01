"""memory consolidation 큐 — git 큐(`notionmemory/skills/git/queue.py`)와 같은 모양,
파일 기반 enqueue/list/ack. env override 로 테스트를 실 상태 디렉터리에서 격리한다."""
from __future__ import annotations

import json

from notionmemory.skills.memory import consolidation_queue as queue


def test_queue_root_honors_env_override(tmp_path, monkeypatch):
    override = tmp_path / "q"
    monkeypatch.setenv("NOTIONMEMORY_MEMQUEUE_DIR", str(override))
    from notionmemory.skills.memory import consolidation_queue as q
    assert q.queue_root() == override


def test_queue_root_defaults_under_state_dir(monkeypatch):
    monkeypatch.delenv("NOTIONMEMORY_MEMQUEUE_DIR", raising=False)
    from notionmemory.skills.memory import consolidation_queue as q
    assert q.queue_root().parts[-2:] == ("notionmemory", "memqueue")


def test_enqueue_and_list_and_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIONMEMORY_MEMQUEUE_DIR", str(tmp_path / "q"))
    from notionmemory.skills.memory import consolidation_queue as q
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    jobs = q.list_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job["project"] == "proj"
    assert job["cwd"] == "/cwd"
    assert job["ts"] == "2026-07-29T00:00:00Z"
    assert job["id"]
    assert q.ack([job["id"]]) == 1
    assert q.list_jobs() == []


def test_list_jobs_empty_when_queue_root_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIONMEMORY_MEMQUEUE_DIR", str(tmp_path / "does-not-exist"))
    from notionmemory.skills.memory import consolidation_queue as q
    assert q.list_jobs() == []


def test_ack_returns_zero_when_nothing_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIONMEMORY_MEMQUEUE_DIR", str(tmp_path / "q"))
    from notionmemory.skills.memory import consolidation_queue as q
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    assert q.ack(["nonexistent-id"]) == 0
    assert len(q.list_jobs()) == 1


def test_enqueue_multiple_jobs_lists_all(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIONMEMORY_MEMQUEUE_DIR", str(tmp_path / "q"))
    from notionmemory.skills.memory import consolidation_queue as q
    q.enqueue("proj-a", "/a", "2026-07-29T00:00:00Z")
    q.enqueue("proj-b", "/b", "2026-07-29T00:00:01Z")
    jobs = q.list_jobs()
    assert {j["project"] for j in jobs} == {"proj-a", "proj-b"}


def test_enqueue_same_project_twice_dedupes_to_one_job(tmp_path, monkeypatch):
    """fix round 2(final review) — Stop 훅은 세션 종료마다(읽기전용 세션 포함)
    enqueue 를 부른다. 같은 프로젝트로 반복 호출해도 잡은 늘지 않고 1개로 수렴하며,
    최신 cwd/ts 로 갱신돼야 한다(오래된 정보로 멈춰있으면 안 됨)."""
    monkeypatch.setenv("NOTIONMEMORY_MEMQUEUE_DIR", str(tmp_path / "q"))
    from notionmemory.skills.memory import consolidation_queue as q
    q.enqueue("proj", "/first", "2026-07-29T00:00:00Z")
    q.enqueue("proj", "/second", "2026-07-29T00:00:01Z")
    q.enqueue("proj", "/third", "2026-07-29T00:00:02Z")
    jobs = q.list_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job["project"] == "proj"
    assert job["cwd"] == "/third"
    assert job["ts"] == "2026-07-29T00:00:02Z"


def test_enqueue_same_project_id_is_deterministic_and_ack_removes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIONMEMORY_MEMQUEUE_DIR", str(tmp_path / "q"))
    from notionmemory.skills.memory import consolidation_queue as q
    q.enqueue("proj", "/a", "2026-07-29T00:00:00Z")
    first_id = q.list_jobs()[0]["id"]
    q.enqueue("proj", "/b", "2026-07-29T00:00:01Z")
    second_id = q.list_jobs()[0]["id"]
    assert first_id == second_id
    assert q.ack([second_id]) == 1
    assert q.list_jobs() == []


def test_queue_root_writable_creates_dir(tmp_path, monkeypatch):
    override = tmp_path / "nested" / "q"
    monkeypatch.setenv("NOTIONMEMORY_MEMQUEUE_DIR", str(override))
    from notionmemory.skills.memory import consolidation_queue as q
    assert q.queue_root_writable() is True
    assert override.is_dir()


def _sess(sid, ts="2026-08-01T00:00:00Z", path="/t.jsonl"):
    return {"session_id": sid, "transcript_path": path, "harness": "claude", "ts": ts}


def test_enqueue_merges_sessions_per_session_id(tmp_path, monkeypatch):
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path))
    queue.enqueue("p", "/p", "t1", session=_sess("s1", ts="t1"))
    queue.enqueue("p", "/p", "t2", session=_sess("s1", ts="t2"))  # 같은 세션 갱신
    queue.enqueue("p", "/p", "t3", session=_sess("s2", ts="t3"))
    jobs = queue.list_jobs()
    assert len(jobs) == 1
    sess = jobs[0]["sessions"]
    assert [s["session_id"] for s in sess] == ["s1", "s2"]
    assert next(s for s in sess if s["session_id"] == "s1")["ts"] == "t2"


def test_enqueue_caps_sessions_at_ten(tmp_path, monkeypatch):
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path))
    for i in range(12):
        queue.enqueue("p", "/p", f"t{i:02d}", session=_sess(f"s{i:02d}", ts=f"t{i:02d}"))
    sess = queue.list_jobs()[0]["sessions"]
    assert len(sess) == queue.MAX_SESSIONS
    assert sess[0]["session_id"] == "s02"  # 가장 오래된 s00·s01 탈락


def test_enqueue_without_session_keeps_legacy_shape(tmp_path, monkeypatch):
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path))
    queue.enqueue("p", "/p", "t1")
    job = queue.list_jobs()[0]
    assert job["sessions"] == [] and job["project"] == "p"


def test_legacy_job_file_without_sessions_still_parses(tmp_path, monkeypatch):
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path))
    root = queue.queue_root(); root.mkdir(parents=True, exist_ok=True)
    jid = queue._job_filename("p")
    (root / jid).write_text(json.dumps({"id": jid, "project": "p", "cwd": "/p", "ts": "t"}))
    queue.enqueue("p", "/p", "t2", session=_sess("s1"))
    assert [s["session_id"] for s in queue.list_jobs()[0]["sessions"]] == ["s1"]


# ── ack_sessions (M1) — compare-and-delete ack ────────────────────────────

def test_ack_sessions_unlinks_when_ts_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path))
    queue.enqueue("p", "/p", "t1", session=_sess("s1"))
    job_id = queue.list_jobs()[0]["id"]
    queue.ack_sessions(job_id, {"s1"}, "t1")
    assert queue.list_jobs() == []


def test_ack_sessions_keeps_new_session_when_ts_changed(tmp_path, monkeypatch):
    """스냅샷 이후(ack 시점 전) 같은 job 이 새 세션과 함께 다시 쓰여졌으면(ts 변경),
    이번에 처리한 세션만 지우고 새로 들어온 세션은 남긴다."""
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path))
    queue.enqueue("p", "/p", "t1", session=_sess("s1", ts="t1"))
    job_id = queue.list_jobs()[0]["id"]
    seen_ts = queue.list_jobs()[0]["ts"]
    queue.enqueue("p", "/p", "t2", session=_sess("s2", ts="t2"))  # race — 새 세션 도착

    queue.ack_sessions(job_id, {"s1"}, seen_ts)

    remaining = queue.list_jobs()
    assert len(remaining) == 1
    assert [s["session_id"] for s in remaining[0]["sessions"]] == ["s2"]


def test_ack_sessions_unlinks_when_ts_changed_but_nothing_remains(tmp_path, monkeypatch):
    """ts 는 바뀌었지만(예: cwd 만 갱신된 재-enqueue) 남는 세션이 없으면 그냥 지운다."""
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path))
    queue.enqueue("p", "/p", "t1", session=_sess("s1", ts="t1"))
    job_id = queue.list_jobs()[0]["id"]
    seen_ts = queue.list_jobs()[0]["ts"]
    queue.enqueue("p", "/p2", "t2")  # 같은 세션 s1 그대로, cwd/ts 만 갱신

    queue.ack_sessions(job_id, {"s1"}, seen_ts)

    assert queue.list_jobs() == []


def test_ack_sessions_noop_when_job_already_gone(tmp_path, monkeypatch):
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path))
    queue.ack_sessions("nonexistent-id", {"s1"}, "t1")  # 트레이스백 없이 조용히 무시
