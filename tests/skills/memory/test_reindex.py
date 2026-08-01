"""memory reindex — Notion(Active+Draft, Type≠brief) 전량 조회 → mem_index.build/save.

consolidate.run 이 성공 경로 끝에 이걸 부르는지(+ 실패해도 무르지 않는지)는
test_consolidate.py 쪽에 있다(그 모듈의 FakeDB/FakeStoreFactory 재사용 패턴과 자연스럽게
묶인다). 여기는 reindex.run 자체의 조회→매핑→저장 계약만 검증한다."""
from __future__ import annotations

from notionmemory.core.config import Config
from notionmemory.skills.memory import mem_index, reindex
from notionmemory.skills.memory.store import build_filter

CFG = Config({"skills": {}})


def _page(mem_id, title, status="Active", mem_type="fact", strength=7, project="p",
          concepts=(), excerpt=""):
    props = {
        "Mem ID": {"rich_text": [{"plain_text": mem_id}]},
        "Title": {"title": [{"plain_text": title}]},
        "Type": {"select": {"name": mem_type}},
        "Concepts": {"multi_select": [{"name": c} for c in concepts]},
        "Excerpt": {"rich_text": [{"plain_text": excerpt}]},
        "Project": {"select": {"name": project} if project else None},
        "Status": {"select": {"name": status}},
        "Strength": {"number": strength},
    }
    return {"id": f"pg_{mem_id}", "last_edited_time": "2026-07-29T00:00:00.000Z",
            "properties": props}


class FakeDB:
    def __init__(self, pages):
        self.pages = pages
        self.queries = []

    def query(self, ds, filter_json):
        self.queries.append((ds, filter_json))
        return self.pages


class FakeStoreFactory:
    """`MemoryStore(NotionSession(), config, log=log)` 자리를 대신한다 — `.db` 와
    `_data_source()` 만 있으면 reindex.run 이 필요로 하는 전부다(test_consolidate.py 의
    동형 헬퍼와 같은 패턴)."""

    def __init__(self, db, ds="ds_1"):
        self.db, self.ds = db, ds

    def __call__(self, *a, **k):
        store = object.__new__(_FakeStore)
        store.db, store._ds = self.db, self.ds
        return store


class _FakeStore:
    def _data_source(self, *, create=True):
        return self._ds


def _wire(monkeypatch, pages, tmp_path):
    db = FakeDB(pages)
    monkeypatch.setattr(reindex, "MemoryStore", FakeStoreFactory(db))
    monkeypatch.setattr(reindex, "NotionSession", lambda: object())
    monkeypatch.setattr(mem_index.paths, "state_dir", lambda: tmp_path)
    return db


def test_reindex_excludes_brief_and_writes_index(tmp_path, monkeypatch):
    pages = [
        _page("m1", "Active one", status="Active"),
        _page("m2", "Active two", status="Active"),
        _page("b1", "brief roll-up", status="Active", mem_type="brief"),
        _page("d1", "Draft one", status="Draft"),
    ]
    db = _wire(monkeypatch, pages, tmp_path)

    count = reindex.run(CFG, print)

    assert count == 3
    idx = mem_index.load()
    assert mem_index.count(idx) == 3
    docs = mem_index.docs(idx)
    assert set(docs) == {"m1", "m2", "d1"}
    assert docs["m1"]["status"] == "Active" and docs["d1"]["status"] == "Draft"
    assert db.queries and db.queries[0] == ("ds_1", build_filter())


def test_reindex_maps_strength_concepts_and_content_fields(tmp_path, monkeypatch):
    _wire(monkeypatch, [_page("m1", "T", concepts=["a"], excerpt="ex", strength=9)], tmp_path)

    reindex.run(CFG, print)

    idx = mem_index.docs(mem_index.load())
    assert idx["m1"]["strength"] == 9
    assert idx["m1"]["concepts"] == ["a"]
    assert idx["m1"]["excerpt"] == "ex"
    assert idx["m1"]["title"] == "T"
    assert idx["m1"]["last_edited"] == "2026-07-29T00:00:00.000Z"


def test_reindex_returns_sentinel_and_logs_on_notion_error(tmp_path, monkeypatch):
    class BoomStore:
        def __init__(self, *a, **k):
            raise RuntimeError("Notion 토큰이 없습니다")

    monkeypatch.setattr(reindex, "MemoryStore", BoomStore)
    monkeypatch.setattr(reindex, "NotionSession", lambda: object())
    monkeypatch.setattr(mem_index.paths, "state_dir", lambda: tmp_path)

    logs = []
    count = reindex.run(CFG, logs.append)

    assert count == -1
    assert logs and "reindex" in logs[0]


def test_reindex_empty_workspace_writes_empty_index(tmp_path, monkeypatch):
    _wire(monkeypatch, [], tmp_path)

    count = reindex.run(CFG, print)

    assert count == 0
    assert mem_index.count(mem_index.load()) == 0
    assert mem_index.docs(mem_index.load()) == {}
