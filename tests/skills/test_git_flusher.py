import json
from pathlib import Path

import pytest
import requests

from notionmemory.core.config import Config
from notionmemory.skills.git import flusher, queue


@pytest.fixture
def qroot(tmp_path, monkeypatch):
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path / "gq"))
    return tmp_path / "gq"


def _seed(repo: str, chash: str, subject: str = "feat: x"):
    d = queue.repo_queue_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    (d / chash).write_text(
        f"repo {repo}\nbranch main\nts 2026-07-20T01:00:00Z\n"
        f"subject {subject}\nfiles a.py\nbody\n", encoding="utf-8")


CFG = Config({"skills": {}})


def test_flush_empty_queue_ok(qroot):
    assert flusher.flush(CFG, print) == 0


def test_flush_summarizes_remembers_acks(qroot, monkeypatch):
    _seed("/x/proj", "aaa111")
    _seed("/x/proj", "bbb222", "fix: y")
    units = [{"content": "proj 작업 요약\n\n상세", "type": "fact",
              "concepts": ["git"], "hashes": ["aaa111", "bbb222"]}]

    class FakeRuntime:
        def generate(self, system, user):
            assert "aaa111" in user and "fix: y" in user
            return json.dumps(units)

    saved = []

    class FakeStore:
        def __init__(self, *a, **k): ...
        def remember(self, content, **kw):
            saved.append((content, kw))
            return {"mem_id": "mem_1", "concepts": kw.get("concepts", [])}

    monkeypatch.setattr(flusher, "build_runtime", lambda cfg: FakeRuntime())
    monkeypatch.setattr(flusher, "MemoryStore", FakeStore)
    monkeypatch.setattr(flusher, "NotionSession", lambda: object())
    monkeypatch.setattr(flusher, "repo_web_url", lambda r: "https://github.com/u/proj")
    assert flusher.flush(CFG, print) == 0
    assert queue.list_entries() == []                      # ack 됨
    content, kw = saved[0]
    assert kw["source"] == "git" and kw["project"] == "proj"
    assert kw["url"] == "https://github.com/u/proj/commit/aaa111"
    assert kw["files"] == ["a.py"]


def test_flush_empty_units_acks_and_logs_distinctly(qroot, monkeypatch):
    _seed("/x/proj", "aaa111")

    class FakeRuntime:
        def generate(self, system, user):
            return "[]"

    class FakeStore:
        def __init__(self, *a, **k): ...
        def remember(self, *a, **k):
            raise AssertionError("빈 유닛일 때는 remember가 호출되면 안 됨")

    logs = []

    monkeypatch.setattr(flusher, "build_runtime", lambda cfg: FakeRuntime())
    monkeypatch.setattr(flusher, "MemoryStore", FakeStore)
    monkeypatch.setattr(flusher, "NotionSession", lambda: object())
    monkeypatch.setattr(flusher, "repo_web_url", lambda r: "https://github.com/u/proj")
    assert flusher.flush(CFG, logs.append) == 0
    assert queue.list_entries() == []                       # ack 됨(트리비얼 커밋 재요약 방지)
    assert any("기억할 항목 없음" in line for line in logs)
    assert not any("기억 0건 저장" in line for line in logs)


def test_flush_offline_keeps_queue_exit2(qroot, monkeypatch):
    _seed("/x/proj", "aaa111")

    class FakeRuntime:
        def generate(self, system, user):
            return json.dumps([{"content": "c", "type": "fact",
                                "concepts": [], "hashes": ["aaa111"]}])

    class FailingStore:
        def __init__(self, *a, **k): ...
        def remember(self, *a, **k):
            raise requests.ConnectionError("offline")

    monkeypatch.setattr(flusher, "build_runtime", lambda cfg: FakeRuntime())
    monkeypatch.setattr(flusher, "MemoryStore", FailingStore)
    monkeypatch.setattr(flusher, "NotionSession", lambda: object())
    monkeypatch.setattr(flusher, "repo_web_url", lambda r: "")
    assert flusher.flush(CFG, print) == 2
    assert len(queue.list_entries()) == 1                  # 큐 보존


def test_flush_bad_json_exit1_keeps_queue(qroot, monkeypatch):
    _seed("/x/proj", "aaa111")

    class FakeRuntime:
        def generate(self, system, user):
            return "JSON 아님"

    class FakeStore:
        def __init__(self, *a, **k): ...

    monkeypatch.setattr(flusher, "build_runtime", lambda cfg: FakeRuntime())
    monkeypatch.setattr(flusher, "MemoryStore", FakeStore)
    monkeypatch.setattr(flusher, "NotionSession", lambda: object())
    assert flusher.flush(CFG, print) == 1
    assert len(queue.list_entries()) == 1


def test_flush_invalid_type_falls_back_to_fact(qroot, monkeypatch):
    _seed("/x/proj", "aaa111")

    class FakeRuntime:
        def generate(self, system, user):
            return json.dumps([{"content": "c", "type": "이상한값",
                                "concepts": [], "hashes": ["aaa111"]}])

    saved = {}

    class FakeStore:
        def __init__(self, *a, **k): ...
        def remember(self, content, **kw):
            saved.update(kw)
            return {"mem_id": "m", "concepts": []}

    monkeypatch.setattr(flusher, "build_runtime", lambda cfg: FakeRuntime())
    monkeypatch.setattr(flusher, "MemoryStore", FakeStore)
    monkeypatch.setattr(flusher, "NotionSession", lambda: object())
    monkeypatch.setattr(flusher, "repo_web_url", lambda r: "")
    assert flusher.flush(CFG, print) == 0
    assert saved["mem_type"] == "fact"


def test_repo_web_url_parses_ssh_remote(monkeypatch):
    monkeypatch.setattr(flusher, "_gh_url", lambda repo: "")
    monkeypatch.setattr(flusher, "_git", lambda repo, *a: "git@github.com:u/proj.git\n")
    assert flusher.repo_web_url("/x/proj") == "https://github.com/u/proj"
