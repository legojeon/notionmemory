"""memory consolidation 큐 — git 큐(`notionmemory/skills/git/queue.py`)와 같은 모양,
파일 기반 enqueue/list/ack. env override 로 테스트를 실 상태 디렉터리에서 격리한다."""
from __future__ import annotations


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
