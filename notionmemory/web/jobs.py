from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    logs: list = field(default_factory=list)
    done: bool = False
    ok: bool | None = None
    message: str = ""


class JobRegistry:
    def __init__(self):
        self._jobs: dict[str, Job] = {}

    def start(self, target) -> Job:
        """target(log: Callable[[str], None]) -> RunResult 를 데몬 스레드로 실행."""
        job = Job(id=uuid.uuid4().hex[:12])
        self._jobs[job.id] = job

        def _worker():
            try:
                result = target(job.logs.append)
                job.ok, job.message = result.ok, result.message
            except Exception as exc:  # noqa: BLE001 — job 격리: 실패를 상태로 기록
                job.ok, job.message = False, f"오류: {exc}"
            finally:
                job.done = True

        t = threading.Thread(target=_worker, daemon=True)
        job.thread = t  # 테스트 동기화용
        t.start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)
