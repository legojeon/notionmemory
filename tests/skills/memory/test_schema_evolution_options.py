"""Fix round 1 — select 프로퍼티 옵션 재조정(ensure/adopt).

리뷰가 잡은 CRITICAL: build_filter()가 Status=Draft 로 서버 필터를 걸게 됐지만,
이미 존재하는 Second Brain DB 의 Status select 프로퍼티는 옵션에 "Draft" 가
없다. Notion API 는 select 필터 값이 그 프로퍼티의 옵션 목록에 없으면 400을
낸다(store.py:63-64 근처 주석과 같은 함정 — Project 를 서버 필터에서 뺀 이유와
동형). 기존 `ensure()`/`adopt()` 스키마 진화는 "빠진 프로퍼티 키"만 추가하고
"이미 있는 select 프로퍼티의 새 옵션"은 절대 추가하지 않았다 — 그래서 기존
설치는 이 변경 이후 recall 마다 400 이 난다.

이 테스트는 그 gap을 `SecondBrainDB._select_option_gaps`(ensure/adopt 공용)로
막는다: 원격 select 옵션이 canonical 상수(STATUSES/ALL_TYPES/SOURCES)를 다
담고 있는지 비교해 빠진 게 있으면 그 프로퍼티만 옵션 전체를 실어 PATCH하고,
이미 다 있으면 PATCH 자체를 안 한다(멱등 — 매 remember/recall 마다 불필요한
쓰기가 나가면 안 된다).
"""
from __future__ import annotations

from notionmemory.skills.memory import notion_db as nd
from tests.skills.memory.conftest import FakeResp


class _EvoSession:
    """GET 은 경로별 canned 응답, PATCH 는 기록만 하는 세션 — ensure()/adopt() 둘
    다 GET /databases 와 GET(+PATCH) /data_sources 를 쓰므로 conftest.FakeSession
    (PATCH /pages 전용)로는 커버가 안 돼 여기서 따로 둔다."""

    def __init__(self, ds_props: dict, db_body: dict | None = None):
        self.ds_props = ds_props
        self.db_body = db_body or {"id": "DB", "data_sources": [{"id": "DS"}]}
        self.patches: list[dict] = []

    def request(self, method: str, path: str, **kw):
        if method == "GET" and path.startswith("/databases/"):
            return FakeResp(200, self.db_body)
        if method == "GET" and path.startswith("/data_sources/"):
            return FakeResp(200, {"properties": self.ds_props})
        if method == "PATCH" and path.startswith("/data_sources/"):
            self.patches.append({"path": path, "json": kw.get("json", {})})
            return FakeResp(200, {})
        raise AssertionError(f"unexpected {method} {path}")


class _FakeMeta:
    def __init__(self, store: dict | None = None):
        self.store = dict(store or {})

    def get_meta(self, k):
        return self.store.get(k, "")

    def set_meta(self, k, v):
        self.store[k] = v


def _status_options(*names):
    return {"type": "select", "select": {"options": [{"name": n} for n in names]}}


# ---- ensure() — 캐시된 data source 경로 ----

def test_ensure_adds_missing_status_option_to_cached_data_source():
    ds_props = {
        "Title": {"type": "title"},
        "Mem ID": {"type": "rich_text"},
        "Status": _status_options("Active", "Superseded", "Forgotten", "Stale"),  # Draft 없음
        "Excerpt": {"type": "rich_text"},
        "Link": {"type": "url"},
    }
    sess = _EvoSession(ds_props)
    meta = _FakeMeta({"data_source_id": "DS_cached"})
    ds_id = nd.SecondBrainDB(sess).ensure("", meta)
    assert ds_id == "DS_cached"
    assert len(sess.patches) == 1
    patched_props = sess.patches[0]["json"]["properties"]
    assert set(patched_props.keys()) == {"Status"}  # Excerpt/Link 는 이미 있어 안 건드림
    names = {o["name"] for o in patched_props["Status"]["select"]["options"]}
    assert "Draft" in names
    assert names == set(nd.STATUSES)  # 전체 canonical 목록을 보냄(멱등 PATCH)


def test_ensure_does_not_patch_when_options_already_complete():
    ds_props = {
        "Title": {"type": "title"},
        "Mem ID": {"type": "rich_text"},
        "Status": _status_options(*nd.STATUSES),
        "Type": _status_options(*nd.ALL_TYPES),
        "Source": _status_options(*nd.SOURCES),
        "Excerpt": {"type": "rich_text"},
        "Link": {"type": "url"},
    }
    sess = _EvoSession(ds_props)
    meta = _FakeMeta({"data_source_id": "DS_cached"})
    ds_id = nd.SecondBrainDB(sess).ensure("", meta)
    assert ds_id == "DS_cached"
    assert sess.patches == []


def test_ensure_reconciles_type_and_source_options_generically():
    """Status 뿐 아니라 Type/Source 도 같은 경로로 재조정된다 — 앞으로 ALL_TYPES/
    SOURCES 에 값이 추가돼도 같은 잠재 버그가 안 난다는 걸 증명."""
    ds_props = {
        "Title": {"type": "title"},
        "Mem ID": {"type": "rich_text"},
        "Type": _status_options(*[t for t in nd.ALL_TYPES if t != "fact"]),  # fact 없음
        "Source": _status_options(*[s for s in nd.SOURCES if s != "git"]),  # git 없음
        "Excerpt": {"type": "rich_text"},
        "Link": {"type": "url"},
    }
    sess = _EvoSession(ds_props)
    meta = _FakeMeta({"data_source_id": "DS_cached"})
    nd.SecondBrainDB(sess).ensure("", meta)
    patched_props = sess.patches[0]["json"]["properties"]
    assert set(patched_props.keys()) == {"Type", "Source"}
    type_names = {o["name"] for o in patched_props["Type"]["select"]["options"]}
    source_names = {o["name"] for o in patched_props["Source"]["select"]["options"]}
    assert "fact" in type_names
    assert "git" in source_names


# ---- adopt() ----

def test_adopt_adds_missing_status_option():
    ds_props = {
        "Title": {"type": "title"},
        "Mem ID": {"type": "rich_text"},
        "Status": _status_options("Active", "Superseded", "Forgotten", "Stale"),
    }
    sess = _EvoSession(ds_props)
    added = nd.SecondBrainDB(sess).adopt("DB", _FakeMeta())
    assert "Status" in added
    patched = sess.patches[0]["json"]["properties"]
    names = {o["name"] for o in patched["Status"]["select"]["options"]}
    assert "Draft" in names


def test_adopt_does_not_repatch_options_already_complete():
    """이미 완전한 select 옵션은 adopt()의 '누락 프로퍼티 전체 추가' 대상이 아니다
    — 필요 없는 옵션 PATCH 로 확장되지 않는다."""
    ds_props = {
        "Title": {"type": "title"},
        "Mem ID": {"type": "rich_text"},
        "Status": _status_options(*nd.STATUSES),
        "Type": _status_options(*nd.ALL_TYPES),
        "Source": _status_options(*nd.SOURCES),
    }
    sess = _EvoSession(ds_props)
    added = nd.SecondBrainDB(sess).adopt("DB", _FakeMeta())
    assert "Status" not in added and "Type" not in added and "Source" not in added
