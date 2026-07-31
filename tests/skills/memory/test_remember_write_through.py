"""remember() write-through (fix round C1) — remember() 저장 직후 로컬 색인도 바로
갱신해, reindex 를 기다리지 않고도 recall 의 로컬 랭킹 경로가 방금 저장한 메모리를
바로 보게 한다. 색인 쓰기가 실패해도 이미 성공한 Notion 저장(remember 의 반환값)은
절대 무르지 않는다(best-effort)."""
from __future__ import annotations

import json

import pytest

from notionmemory.core.config import Config
from notionmemory.skills.memory import mem_index
from notionmemory.skills.memory.store import ConfigMeta, MemoryStore


@pytest.fixture(autouse=True)
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / ".local" / "state"))
    return tmp_path


class FakeDB:
    """create_page(저장) + query(recall 의 검증/전량 왕복) 를 함께 지원하는 페이크.
    `live` 는 mem_id → 저장된 메모리 dict(title/content/type/concepts/project/status)."""

    def __init__(self, live=None):
        self.live = dict(live or {})
        self.created = []
        self.queries = []

    def ensure(self, parent, meta, *, create=True):
        return "ds_1"

    def create_page(self, ds, memory):
        self.created.append(memory)
        return f"pg_{memory['id']}"

    def query(self, ds, filt):
        self.queries.append(filt)
        ids = ([c["rich_text"]["equals"] for c in filt.get("and", [{}])[-1].get("or", [])
                if "rich_text" in c] if "and" in filt else [])
        pool = ids if ids else sorted(self.live)
        return [self._page(i) for i in pool if i in self.live]

    def _page(self, mem_id):
        p = self.live[mem_id]
        return {"id": f"pg-{mem_id}", "last_edited_time": "2026-07-31T00:00:00.000Z",
                "properties": {
                    "Mem ID": {"rich_text": [{"plain_text": mem_id}]},
                    "Title": {"title": [{"plain_text": p["title"]}]},
                    "Type": {"select": {"name": p.get("type", "fact")}},
                    "Concepts": {"multi_select": [{"name": c} for c in p.get("concepts", [])]},
                    "Excerpt": {"rich_text": [{"plain_text": p.get("content", "")}]},
                    "Project": {"select": ({"name": p["project"]} if p.get("project") else None)},
                    "Status": {"select": {"name": p.get("status", "Active")}},
                }}


def _store(db):
    s = MemoryStore.__new__(MemoryStore)
    s.db, s.config = db, Config({}, "")
    s.meta, s._ds_cache = ConfigMeta(s.config), "ds_1"
    return s


def _seed_old_memory():
    mem_index.save(mem_index.build([{
        "id": "old1", "title": "옛날 메모", "concepts": [], "content": "예전 내용",
        "strength": 5, "type": "fact", "project": "p", "status": "Active",
        "last_edited": "t"}]))


# (a) ────────────────────────────────────────────────────

def test_remember_adds_to_index_and_updates_meta():
    _seed_old_memory()
    db = FakeDB()

    out = _store(db).remember("jwt refresh rotation 정책 변경\n본문", mem_type="architecture",
                              concepts=["jwt-refresh"], project="p")

    idx = mem_index.load()
    docs = mem_index.docs(idx)
    assert out["mem_id"] in docs
    assert docs[out["mem_id"]]["title"] == "jwt refresh rotation 정책 변경"
    assert docs[out["mem_id"]]["concepts"] == ["jwt-refresh"]
    assert idx["meta"]["n"] == 2                          # old1 + 새 메모리
    assert idx["meta"]["df"].get("jwt", 0) >= 1


# (b) ────────────────────────────────────────────────────

def test_remember_survives_poisoned_index(monkeypatch):
    """색인 쓰기가 터져도(예: 디스크 오류) 이미 성공한 Notion 저장의 반환값은 그대로
    돌아와야 한다 — best-effort, 절대 remember 를 실패시키면 안 된다."""
    db = FakeDB()
    monkeypatch.setattr(mem_index, "save",
                        lambda idx: (_ for _ in ()).throw(RuntimeError("disk full")))

    out = _store(db).remember("새 메모리", mem_type="fact")

    assert len(db.created) == 1
    assert out["mem_id"] == db.created[0]["id"]
    assert out["page_id"] == f"pg_{db.created[0]['id']}"


# (c) ────────────────────────────────────────────────────

def test_remember_then_recall_finds_new_memory_via_local_path():
    """end-to-end: 오래된 메모리로 색인을 시딩한 뒤 새 메모리를 remember 하고, 새
    메모리의 검색어로 recall 하면 로컬 랭킹 경로(fallback:False)로 새 메모리가
    나와야 한다 — write-through 전에는 다음 reindex 전까지 색인에 안 보였다."""
    _seed_old_memory()
    db = FakeDB()
    store = _store(db)

    out = store.remember("쿠버네티스 오토스케일링 정책 변경", mem_type="architecture",
                         concepts=["k8s-autoscaling"], project="p")
    new_id = out["mem_id"]

    # 라이브 검증 왕복이 "살아있다"고 답하도록 새/구 메모리 둘 다 FakeDB 에 등록한다.
    db.live["old1"] = {"title": "옛날 메모", "content": "예전 내용", "type": "fact",
                       "concepts": [], "project": "p", "status": "Active"}
    db.live[new_id] = {"title": "쿠버네티스 오토스케일링 정책 변경",
                       "content": "쿠버네티스 오토스케일링 정책 변경", "type": "architecture",
                       "concepts": ["k8s-autoscaling"], "project": "p", "status": "Active"}

    result = store.recall("쿠버네티스 오토스케일링", project="p", top=5)

    assert result["fallback"] is False
    assert new_id in [r["mem_id"] for r in result["results"]]
