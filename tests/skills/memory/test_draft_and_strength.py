"""Second Brain v2 phase 2a — Draft 상태 + status/strength 스레딩 + set_properties.

notion_db.py: STATUSES 에 Draft, _props 가 status/strength 를 memory dict 에서
읽음, set_properties 일반화. store.py: remember 가 status/strength 를 받아
memory dict 에 실음, build_filter 가 Active 뿐 아니라 Draft 도 회수한다(초안이
consolidation 전까지 안 사라지게).
"""
from __future__ import annotations

from notionmemory.core.config import Config
from notionmemory.skills.memory import notion_db as nd
from notionmemory.skills.memory import store as store_mod
from notionmemory.skills.memory.store import MemoryStore
from tests.skills.memory.conftest import FakeSession


# ---- notion_db.py ----

def test_statuses_include_draft():
    assert "Draft" in nd.STATUSES
    assert any(o["name"] == "Draft" for o in nd.PROPERTIES["Status"]["select"]["options"])


def test_props_threads_status_and_strength():
    db = nd.SecondBrainDB(FakeSession())
    p = db._props({"id": "m1", "content": "x", "type": "fact",
                   "status": "Draft", "strength": 3})
    assert p["Status"]["select"]["name"] == "Draft"
    assert p["Strength"]["number"] == 3


def test_props_defaults_active_strength7():
    p = nd.SecondBrainDB(FakeSession())._props({"id": "m1", "content": "x"})
    assert p["Status"]["select"]["name"] == "Active"
    assert p["Strength"]["number"] == 7


def test_set_properties_patches_page():
    sess = FakeSession()
    db = nd.SecondBrainDB(sess)
    db.set_properties("pg1", {"Status": {"select": {"name": "Active"}},
                              "Strength": {"number": 9}})
    assert sess.patched["path"] == "/pages/pg1"
    assert sess.patched["json"]["properties"]["Strength"]["number"] == 9


def test_set_status_still_works_via_set_properties():
    """set_status 는 그대로 유지 — 리팩터 후에도 기존 호출자(supersede/forget)가 깨지면 안 됨."""
    sess = FakeSession()
    db = nd.SecondBrainDB(sess)
    db.set_status("pg2", "Forgotten")
    assert sess.patched["path"] == "/pages/pg2"
    assert sess.patched["json"]["properties"]["Status"]["select"]["name"] == "Forgotten"


# ---- store.py ----

def test_build_filter_includes_active_and_draft():
    f = store_mod.build_filter()
    status_clause = next(c for c in f["and"] if "or" in c)
    names = {c["select"]["equals"] for c in status_clause["or"]
             if c.get("property") == "Status"}
    assert names == {"Active", "Draft"}


def test_build_filter_still_narrows_by_type():
    f = store_mod.build_filter(mem_type="fact")
    assert any("or" in c for c in f["and"])
    # Type 절이 둘 있다 — brief 제외(does_not_equal, 항상 존재)와 요청된 mem_type(equals)
    type_clauses = [c for c in f["and"] if c.get("property") == "Type"]
    assert {"select": {"does_not_equal": "brief"}} in [
        {k: v for k, v in c.items() if k != "property"} for c in type_clauses]
    equals_clause = next(c for c in type_clauses if "equals" in c["select"])
    assert equals_clause["select"]["equals"] == "fact"


class _RecordingDB:
    """MemoryStore.remember 이 만드는 memory dict 를 가로채는 스텁 — SecondBrainDB
    전체를 흉내내지 않고 remember 가 무엇을 create_page 에 넘기는지만 본다."""

    def __init__(self):
        self.created: dict | None = None

    def ensure(self, parent_page_id, meta):
        return "DS"

    def create_page(self, data_source_id, memory):
        self.created = memory
        return "page-x"


def test_remember_threads_status_and_strength_into_memory_dict():
    store = MemoryStore(FakeSession(), Config({}))
    store.db = _RecordingDB()
    store.remember("content here", mem_type="fact", status="Draft", strength=2)
    assert store.db.created["status"] == "Draft"
    assert store.db.created["strength"] == 2


def test_remember_defaults_status_active_strength7():
    store = MemoryStore(FakeSession(), Config({}))
    store.db = _RecordingDB()
    store.remember("content here", mem_type="fact")
    assert store.db.created["status"] == "Active"
    assert store.db.created["strength"] == 7
