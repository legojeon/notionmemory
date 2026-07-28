"""library 회수 — content 색인 + memory recall 팬아웃, 소스별 그룹."""
import pytest

from notionmemory.skills.library import index as I
from notionmemory.skills.library import retrieve as R


@pytest.fixture(autouse=True)
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


class FakeMemoryStore:
    last = None

    def __init__(self, session, config, log=None):
        FakeMemoryStore.last = self
        self.calls = []

    def recall(self, query="", *, mem_type="", project="", top=5):
        self.calls.append((query, top))
        return {"results": [{"mem_id": "mem_1", "title": "트랜스포머 어텐션 정리",
                             "type": "architecture", "concepts": ["attention"],
                             "excerpt": "...", "project": "", "last_edited": "t"}],
                "fallback": False}


@pytest.fixture(autouse=True)
def fake_memory(monkeypatch):
    # FakeMemoryStore.last 는 클래스 속성이라 테스트 간 누수된다(이전 테스트가
    # memory 를 호출했으면 다음 테스트 시작 시점에도 non-None) — 매 테스트 시작
    # 전에 리셋해 "memory 아예 안 부름" 단언이 실행 순서에 독립적이도록 한다.
    FakeMemoryStore.last = None
    monkeypatch.setattr(R, "MemoryStore", FakeMemoryStore)
    return FakeMemoryStore


def _seed_content():
    idx = I.load()
    I.upsert(idx, "pg1", title="논문정리 — 어텐션", headings=["요약"],
             url="https://n/pg1", last_edited_time="t")
    I.save(idx)


def test_search_fans_out_to_content_and_memory():
    _seed_content()
    hits = R.search(object(), object(), "어텐션")
    sources = {h["source"] for h in hits}
    assert sources == {"content", "memory"}


def test_content_hit_shape_has_page_id_and_pointer_fields():
    _seed_content()
    hits = R.search(object(), object(), "어텐션")
    content = [h for h in hits if h["source"] == "content"][0]
    assert content["id"] == "pg1" and content["title"].startswith("논문정리")


def test_memory_hit_shape_carries_mem_id():
    _seed_content()
    hits = R.search(object(), object(), "어텐션")
    mem = [h for h in hits if h["source"] == "memory"][0]
    assert mem["id"] == "mem_1" and "트랜스포머" in mem["title"]


def test_no_global_ranking_across_sources_grouped_by_source():
    """두 점수 척도가 달라 전역 정렬하지 않는다 — 소스별로 그룹진다."""
    _seed_content()
    hits = R.search(object(), object(), "어텐션")
    labels = [h["source"] for h in hits]
    # 같은 소스끼리 인접(그룹) — content 블록과 memory 블록이 섞이지 않는다
    assert labels == sorted(labels, key=lambda s: {"content": 0, "memory": 1}[s])


def test_source_filter_content_only_skips_memory():
    _seed_content()
    hits = R.search(object(), object(), "어텐션", sources=("content",))
    assert {h["source"] for h in hits} == {"content"}
    assert FakeMemoryStore.last is None      # memory 아예 안 부름


def test_limit_is_per_source():
    idx = I.load()
    for i in range(30):
        I.upsert(idx, f"pg{i}", title="어텐션", headings=[], url="u", last_edited_time="t")
    I.save(idx)
    hits = R.search(object(), object(), "어텐션", limit=5)
    assert len([h for h in hits if h["source"] == "content"]) == 5


class FakeMemoryStoreFallback:
    last = None

    def __init__(self, session, config, log=None):
        FakeMemoryStoreFallback.last = self

    def recall(self, query="", *, mem_type="", project="", top=5):
        # 토큰 미스 → 최근 N개 폴백. fallback=True 는 매칭이 아니다.
        return {"results": [{"mem_id": "mem_recent", "title": "무관한 최근 기억",
                             "type": "note", "concepts": [], "excerpt": "...",
                             "project": "", "last_edited": "t"}],
                "fallback": True}


def test_memory_recency_fallback_is_not_surfaced_as_a_match(monkeypatch):
    """recall 이 토큰 미스로 최근 N개를 폴백 반환하면(fallback=True) library search 는
    그걸 매칭처럼 내보내면 안 된다 — content 처럼 무매칭=무결과."""
    monkeypatch.setattr(R, "MemoryStore", FakeMemoryStoreFallback)
    hits = R.search(object(), object(), "완전히무관한질의")
    assert not any(h["source"] == "memory" for h in hits)
