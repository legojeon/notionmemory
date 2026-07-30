"""조회 경로는 절대 Second Brain DB 를 만들지 않는다 — 고아 DB 문제의 실제 기전.

calendar 의 `ensure(create=False)` 규율과 동일: PAT 만 연결한 사용자가 `library
search`(→ MemoryStore.recall) 한 번, 또는 SessionStart 훅(project_brief/top_memories,
예외 전부 삼킴) 한 번에 **아무 말 없이** 워크스페이스 최상위 DB 를 떠안았고, 그 뒤
온보딩 넛지는 memory 가 바인딩됐다고 보고 침묵했다(opus 스윕 재현). 쓰기(remember)는
기존처럼 부트스트랩한다."""
import pytest

from notionmemory.core.config import Config
from notionmemory.skills.memory.store import MemoryStore


class _Resp:
    def __init__(self, code=200, body=None):
        self.status_code = code
        self._body = body or {}
        self.text = ""

    def json(self):
        return self._body


class _Session:
    """모든 요청 기록 — POST /databases(생성)가 오면 표시."""
    def __init__(self):
        self.created = []

    def request(self, method, path, **kw):
        if method == "POST" and path == "/databases":
            self.created.append(path)
            return _Resp(200, {"id": "db-new", "data_sources": [{"id": "ds-new"}]})
        if method == "POST" and path.endswith("/query"):
            return _Resp(200, {"results": [], "has_more": False})
        return _Resp(404)      # 캐시 검증 GET 등 — 아무것도 없음


def _store():
    return MemoryStore(_Session(), Config({}), log=lambda *_: None)


def test_recall_unbound_returns_empty_and_creates_nothing():
    store = _store()
    out = store.recall("kubernetes")
    assert out == {"results": [], "fallback": False}
    assert store.db.session.created == []


def test_project_brief_unbound_is_empty_and_creates_nothing():
    store = _store()
    assert store.project_brief("proj") == ""
    assert store.db.session.created == []


def test_top_memories_unbound_is_empty_and_creates_nothing():
    store = _store()
    assert store.top_memories("proj") == []
    assert store.db.session.created == []


def test_get_and_forget_unbound_create_nothing():
    store = _store()
    assert store.get("mem_x") is None
    assert store.forget("mem_x") is False
    assert store.db.session.created == []


def test_remember_still_bootstraps():
    store = _store()
    with pytest.raises(Exception):
        # 부트스트랩 뒤 페이지 생성 등에서 fake 가 404 를 내 실패하는 건 상관없다 —
        # 핵심은 쓰기 경로가 생성을 '시도'한다는 것.
        store.remember("내용", mem_type="fact")
    assert store.db.session.created == ["/databases"]


def test_read_miss_does_not_poison_cache_for_later_write():
    store = _store()
    store.recall("x")                          # create=False → "" (캐시 금지)
    with pytest.raises(Exception):
        store.remember("내용", mem_type="fact")
    assert store.db.session.created == ["/databases"]   # 쓰기가 여전히 부트스트랩
