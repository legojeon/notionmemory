"""recall 로컬랭킹+배치검증 — 색인이 있으면 BM25 후보를 Mem ID or-필터 1왕복으로
검증하고(사라진 항목은 read-repair), 색인이 비면 기존 라이브 경로 그대로."""
import json

import pytest

from notionmemory.core.config import Config
from notionmemory.skills.memory import mem_index
from notionmemory.skills.memory.store import MemoryStore


def _page(mem_id, title, mem_type="fact"):
    return {"id": f"pg-{mem_id}", "last_edited_time": "2026-07-30T00:00:00.000Z",
            "properties": {
                "Title": {"title": [{"plain_text": title}]},
                "Mem ID": {"rich_text": [{"plain_text": mem_id}]},
                "Type": {"select": {"name": mem_type}},
                "Concepts": {"multi_select": []},
                "Project": {"select": {"name": "p"}},
                "Status": {"select": {"name": "Active"}},
                "Excerpt": {"rich_text": [{"plain_text": title}]},
            }}


class FakeDB:
    def __init__(self, live_mem_ids):
        self.live = set(live_mem_ids)
        self.queries = []

    def ensure(self, parent, meta, *, create=True):
        return "ds_1"

    def query(self, ds, filt):
        self.queries.append(filt)
        ids = [c["rich_text"]["equals"] for c in json.loads(json.dumps(filt)).get("and", [{}])[-1].get("or", [])
               if "rich_text" in c] if "and" in filt else []
        if ids:                                   # 검증 쿼리
            return [_page(i, f"제목 {i}") for i in ids if i in self.live]
        return [_page(i, f"제목 {i}") for i in sorted(self.live)]   # 전량 폴백 경로


@pytest.fixture(autouse=True)
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / ".local" / "state"))
    return tmp_path


def _seed_index(ids):
    mems = [{"id": i, "title": f"jwt 회전 {i}", "concepts": ["jwt"],
             "content": f"jwt refresh 내용 {i}", "strength": 5, "type": "fact",
             "project": "p", "status": "Active", "last_edited": "t"} for i in ids]
    mem_index.save(mem_index.build(mems))


def _store(db):
    s = MemoryStore.__new__(MemoryStore)
    s.db, s.config, s.log = db, Config({"skills": {"memory": {"data_source_id": "x"}}}), lambda *_: None
    from notionmemory.skills.memory.store import ConfigMeta
    s.meta, s._ds_cache = ConfigMeta(s.config), "ds_1"
    return s


def test_indexed_recall_verifies_batch_and_returns_live_summaries():
    _seed_index(["m1", "m2", "m3"])
    db = FakeDB(live_mem_ids=["m1", "m2", "m3"])
    out = _store(db).recall("jwt", project="p", top=2)
    assert out["fallback"] is False
    assert len(out["results"]) == 2
    assert len(db.queries) == 1                       # 배치 검증 1왕복
    assert "Mem ID" in json.dumps(db.queries[0])       # 검증 쿼리 판별(vacuous "and" 아님)


def test_missing_page_is_pruned_and_refilled():
    _seed_index(["m1", "m2", "m3"])
    db = FakeDB(live_mem_ids=["m2", "m3"])            # m1 은 Notion 에서 삭제됨
    out = _store(db).recall("jwt", project="p", top=2)
    ids = [r["mem_id"] for r in out["results"]]
    assert "m1" not in ids and len(ids) == 2
    assert "m1" not in mem_index.docs(mem_index.load())   # read-repair 지연삭제


def test_empty_index_falls_back_to_live_path():
    assert mem_index.count(mem_index.load()) == 0            # 색인 미시딩(비었음) 전제
    db = FakeDB(live_mem_ids=["m9"])
    out = _store(db).recall("jwt", project="", top=5)
    assert len(db.queries) == 1                               # 배치 검증 없이 전량 1왕복
    assert "Mem ID" not in json.dumps(db.queries[0])           # 전량 경로는 Mem ID 로 안 거름
    assert [r["mem_id"] for r in out["results"]] == ["m9"]     # 라이브 전량 경로 결과


def test_return_shape_unchanged():
    _seed_index(["m1"])
    out = _store(FakeDB(["m1"])).recall("jwt", project="p", top=1)
    r = out["results"][0]
    for key in ("mem_id", "title", "concepts", "excerpt", "type", "project", "last_edited"):
        assert key in r


def test_verification_filter_is_spliced_to_two_levels():
    """Notion 컴파운드 필터는 2단계(and/or)까지만 허용 — build_filter 를 그대로 한 겹
    더 감싸면 and→and→or 3단계가 되어 라이브에서 400 (templates/filters.py 의 splice
    규율과 동일 함정). or-필터는 바깥 and 리스트에 직접 있어야 하고, 그 리스트 안에
    중첩된 {"and": ...} 원소가 있으면 안 된다."""
    _seed_index(["m1", "m2"])
    db = FakeDB(live_mem_ids=["m1", "m2"])
    _store(db).recall("jwt", project="p", top=2)
    and_list = db.queries[0]["and"]
    assert not any(isinstance(clause, dict) and "and" in clause for clause in and_list)
    or_clauses = [c for c in and_list if isinstance(c, dict) and "or" in c]
    assert any("Mem ID" in json.dumps(c) for c in or_clauses)


# ── fix round: I2 --type prefilter survives candidate truncation ──

def test_recall_type_filter_survives_truncation_end_to_end():
    """I2 — 색인 검색이 limit(top*2) 절단 전에 mem_type 을 걸지 않으면, 더 높은 score
    의 다른 type 문서가 절단 안을 채워 recall(mem_type=...) 이 top 보다 훨씬 적게
    돌려줄 수 있다. 12건의 type=fact + 8건의 더 높은 score 인 type=bug 를 섞어 두면,
    옛 사후필터는 2건만 남기고 새 선필터는 top(5)건을 그대로 채운다."""
    mems = [{"id": f"fact{i}", "title": "공통 제목 매치", "concepts": [],
             "content": "본문 매치", "strength": 0, "type": "fact", "project": "p",
             "status": "Active", "last_edited": "t"} for i in range(12)] + [
            {"id": f"bug{i}", "title": "공통 제목 매치", "concepts": [],
             "content": "본문 매치", "strength": 20, "type": "bug", "project": "p",
             "status": "Active", "last_edited": "t"} for i in range(8)]
    mem_index.save(mem_index.build(mems))
    db = FakeDB(live_mem_ids=[m["id"] for m in mems])

    out = _store(db).recall("공통 제목 매치", mem_type="fact", project="p", top=5)

    assert len(out["results"]) == 5
    assert all(r["type"] == "fact" for r in out["results"])


def test_fully_stale_index_falls_through_to_live_path():
    """색인 후보가 전부 사라졌으면(verified == []) 빈 결과로 답하지 않고 기존 라이브
    전량 경로로 떨어져야 한다 — 검증 왕복과 전량 폴백 왕복 둘 다 일어난다."""
    _seed_index(["m1", "m2"])                     # 색인엔 있지만
    db = FakeDB(live_mem_ids=["m9"])               # Notion 엔 색인에 없는 페이지만 살아있음
    out = _store(db).recall("jwt", project="p", top=2)
    assert [r["mem_id"] for r in out["results"]] == ["m9"]
    assert len(db.queries) == 2                                # 검증 1왕복 + 전량 폴백 1왕복
    assert "Mem ID" in json.dumps(db.queries[0])                # 검증 쿼리
    assert "Mem ID" not in json.dumps(db.queries[1])            # 전량 폴백 쿼리
    assert "m1" not in mem_index.docs(mem_index.load())         # 전부 read-repair 로 지연삭제
    assert "m2" not in mem_index.docs(mem_index.load())


# ── fix round: I3 malformed/future-version index degrades, not tracebacks ──

def test_v3_index_falls_back_to_live_path_without_exception():
    idx_path = mem_index.index_path()
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path.write_text(json.dumps({"version": 3, "meta": 1, "docs": {}}), encoding="utf-8")
    db = FakeDB(live_mem_ids=["m9"])

    out = _store(db).recall("jwt", project="", top=5)

    assert out["fallback"] is True
    assert [r["mem_id"] for r in out["results"]] == ["m9"]


def test_non_dict_index_json_falls_back_to_live_path_without_exception():
    idx_path = mem_index.index_path()
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    db = FakeDB(live_mem_ids=["m9"])

    out = _store(db).recall("jwt", project="", top=5)

    assert out["fallback"] is True
    assert [r["mem_id"] for r in out["results"]] == ["m9"]


# ── fix round: M5 index/live type mismatch — not pruned, not returned ──

class TypedFakeDB(FakeDB):
    """검증 쿼리에서 mem_id 별로 다른(색인과 어긋날 수 있는) 라이브 type 을 응답하는
    페이크 — 살아있지만 타입이 색인과 다른 항목은 prune 되면 안 되고, 요청한 --type
    결과에도 안 보여야 한다."""

    def __init__(self, live_mem_ids, live_types):
        super().__init__(live_mem_ids)
        self.live_types = live_types

    def query(self, ds, filt):
        self.queries.append(filt)
        ids = [c["rich_text"]["equals"] for c in json.loads(json.dumps(filt)).get("and", [{}])[-1].get("or", [])
               if "rich_text" in c] if "and" in filt else []
        pool = ids if ids else sorted(self.live)
        return [_page(i, f"제목 {i}", mem_type=self.live_types.get(i, "fact"))
                for i in pool if i in self.live]


def test_type_mismatch_between_index_and_live_is_not_pruned_or_returned():
    """색인엔 type=fact 로 있지만(_seed_index 기본값) 그 사이 consolidation 등으로
    라이브 type 이 바뀐 경우(m1→architecture), 검증 왕복에서 '사라짐'으로 오인해
    지연삭제(prune)하면 안 된다 — 실제로는 살아있다. 대신 --type fact 결과에는
    빠져야 한다(사후 타입 필터, m2 는 진짜 fact 라 정상 반환)."""
    _seed_index(["m1", "m2"])
    db = TypedFakeDB(live_mem_ids=["m1", "m2"],
                     live_types={"m1": "architecture", "m2": "fact"})

    out = _store(db).recall("jwt", project="p", mem_type="fact", top=5)

    ids = [r["mem_id"] for r in out["results"]]
    assert "m1" not in ids and "m2" in ids
    assert out["fallback"] is False
    assert "m1" in mem_index.docs(mem_index.load())      # 살아있으므로 prune 되지 않는다
