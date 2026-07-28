from pathlib import Path

import pytest

from notionmemory.skills.git import queue


ENTRY = """repo {repo}
branch main
ts 2026-07-20T01:00:00Z
subject fix: 큐 파싱
files a.py,b/c.py
body
본문 첫 줄

본문 둘째 줄"""


@pytest.fixture
def qroot(tmp_path, monkeypatch):
    monkeypatch.setenv(queue.QUEUE_ROOT_ENV, str(tmp_path / "gq"))
    return tmp_path / "gq"


def _write(qroot: Path, repo: str, chash: str) -> Path:
    d = queue.repo_queue_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    f = d / chash
    f.write_text(ENTRY.format(repo=repo), encoding="utf-8")
    return f


def test_queue_root_env_override(qroot):
    assert queue.queue_root() == qroot


def test_repo_slug_disambiguates_same_basename():
    a, b = queue.repo_slug("/x/proj"), queue.repo_slug("/y/proj")
    assert a != b and a.startswith("proj-") and b.startswith("proj-")


def test_parse_and_list(qroot):
    _write(qroot, "/x/proj", "abc123")
    entries = queue.list_entries("/x/proj")
    assert len(entries) == 1
    e = entries[0]
    assert e["hash"] == "abc123" and e["repo"] == "/x/proj"
    assert e["files"] == ["a.py", "b/c.py"]
    assert e["subject"] == "fix: 큐 파싱"
    assert "본문 둘째 줄" in e["body"]


def test_list_all_repos_and_corrupt_skipped(qroot):
    _write(qroot, "/x/proj", "abc123")
    _write(qroot, "/y/other", "def456")
    bad = queue.repo_queue_dir("/y/other") / "bad999"
    bad.write_text("깨진 내용", encoding="utf-8")
    entries = queue.list_entries()
    assert {e["hash"] for e in entries} == {"abc123", "def456"}


def test_ack_removes_and_prunes_empty_dir(qroot):
    _write(qroot, "/x/proj", "abc123")
    assert queue.ack(["abc123", "nope"]) == 1
    assert queue.list_entries() == []
    assert not queue.repo_queue_dir("/x/proj").exists()


def test_list_entries_empty_when_root_missing(qroot):
    assert queue.list_entries() == []
