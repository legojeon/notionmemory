from notionmemory.core.skill_base import RunResult
from notionmemory.web.jobs import JobRegistry


def test_job_runs_and_captures_logs():
    reg = JobRegistry()

    def work(log):
        log("하나")
        log("둘")
        return RunResult(True, "완료")

    job = reg.start(work)
    job.thread.join(timeout=5)
    assert job.done and job.ok is True
    assert job.logs == ["하나", "둘"] and job.message == "완료"


def test_job_failure_recorded_not_raised():
    reg = JobRegistry()

    def boom(log):
        raise RuntimeError("파이프라인 죽음")

    job = reg.start(boom)
    job.thread.join(timeout=5)
    assert job.done and job.ok is False and "파이프라인 죽음" in job.message


def test_get_unknown_job_returns_none():
    assert JobRegistry().get("nope") is None
