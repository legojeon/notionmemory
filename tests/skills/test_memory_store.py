import json

import pytest
from notionmemory.core.config import Config
from notionmemory.skills.memory.store import (
    ConfigMeta, MemoryStore, build_filter, new_mem_id, page_summary, score_page, tokenize)


# ── 순수 함수 ──────────────────────────────────────────

def test_new_mem_id_format():
    mid = new_mem_id(now_ms=1752624000000, rand="abcdefghijkl")
    assert mid.startswith("mem_") and mid.endswith("_abcdefghijkl")
    ts36 = mid.split("_")[1]
    assert int(ts36, 36) == 1752624000000
    auto = new_mem_id()
    assert auto.split("_")[2].isalnum() and len(auto.split("_")[2]) == 12


def test_tokenize_lowercases_and_splits():
    assert tokenize("JWT Refresh-Rotation 토큰") == ["jwt", "refresh", "rotation", "토큰"]
    assert tokenize("") == []


def test_score_weights_3_2_1():
    tokens = ["jwt"]
    assert score_page(tokens, title="JWT rotation", concepts=[], excerpt="") == 3
    assert score_page(tokens, title="", concepts=["jwt-refresh"], excerpt="") == 2
    assert score_page(tokens, title="", concepts=[], excerpt="uses jwt") == 1
    assert score_page(tokens, title="jwt", concepts=["jwt"], excerpt="jwt") == 6
    assert score_page(["없는말"], title="jwt", concepts=["jwt"], excerpt="jwt") == 0


def test_score_ascii_token_uses_word_boundary_korean_uses_substring():
    # ASCII 토큰은 단어 경계 — 'jwt' 가 'jwtx' 안에 걸리지 않는다(부분매칭 오탐 방지)
    assert score_page(["jwt"], title="jwtx handler", concepts=[], excerpt="") == 0
    assert score_page(["jwt"], title="jwt handler", concepts=[], excerpt="") == 3
    # 한글은 부분 매칭 유지 — 조사가 붙어도 회수된다
    assert score_page(["쿠버네티스"], title="쿠버네티스의 운영", concepts=[], excerpt="") == 3


def test_build_filter_active_plus_type_without_project():
    assert build_filter() == {"and": [
        {"property": "Status", "select": {"equals": "Active"}}]}
    f = build_filter(mem_type="bug")
    assert {"property": "Type", "select": {"equals": "bug"}} in f["and"]
    # Project 옵션은 저장 시점에 동적으로 생기므로, 스키마에 없는 값으로 select 필터를
    # 걸면 Notion이 400을 낸다 — 서버 필터에서 제외하고 recall이 클라이언트에서 거른다.
    assert "Project" not in json.dumps(f)


def _page(mem_id, title, concepts=(), excerpt="", edited="2026-07-16T00:00:00.000Z",
          project="p"):
    return {"id": f"pg_{mem_id}", "last_edited_time": edited, "properties": {
        "Mem ID": {"rich_text": [{"plain_text": mem_id}]},
        "Title": {"title": [{"plain_text": title}]},
        "Type": {"select": {"name": "fact"}},
        "Concepts": {"multi_select": [{"name": c} for c in concepts]},
        "Excerpt": {"rich_text": [{"plain_text": excerpt}]},
        "Project": {"select": {"name": project} if project else None},
    }}


def test_page_summary_extracts_fields():
    s = page_summary(_page("mem_1", "T", ["a"], "ex"))
    assert s == {"mem_id": "mem_1", "title": "T", "type": "fact", "concepts": ["a"],
                 "excerpt": "ex", "project": "p", "files": [], "url": "",
                 "last_edited": "2026-07-16T00:00:00.000Z", "page_id": "pg_mem_1"}


def test_page_summary_tolerates_missing_props():
    s = page_summary({"id": "pg", "properties": {}})
    assert s["mem_id"] == "" and s["concepts"] == [] and s["excerpt"] == ""


# ── ConfigMeta ─────────────────────────────────────────

def test_config_meta_persists_to_file_and_memory(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("skills: {}\n")
    cfg = Config.load(str(p))
    meta = ConfigMeta(cfg)
    assert meta.get_meta("data_source_id") == ""
    meta.set_meta("data_source_id", "ds_1")
    assert meta.get_meta("data_source_id") == "ds_1"
    assert Config.load(str(p)).skill_options("memory")["data_source_id"] == "ds_1"


def test_config_meta_without_path_stays_in_memory():
    cfg = Config({}, "")
    meta = ConfigMeta(cfg)
    meta.set_meta("database_id", "db_1")
    assert meta.get_meta("database_id") == "db_1"


def test_config_meta_set_syncs_memory_section_with_disk(tmp_path):
    import yaml
    p = tmp_path / "config.yaml"
    p.write_text("skills:\n  memory:\n    top_n: 5\n", encoding="utf-8")
    cfg = Config.load(str(p))
    # 다른 호출자가 디스크 저장 없이 in-memory 만 직접 변경한 상황
    cfg.data["skills"]["memory"]["stray"] = "in-memory-only"
    ConfigMeta(cfg).set_meta("data_source_id", "ds_1")
    on_disk = yaml.safe_load(p.read_text())["skills"]["memory"]
    # 디스크가 단일 소스 — 저장 안 된 stray 는 in-memory 에서도 떨어져 나간다
    assert on_disk == {"top_n": 5, "data_source_id": "ds_1"}
    assert cfg.data["skills"]["memory"] == on_disk


# ── MemoryStore (FakeDB 주입) ──────────────────────────

class FakeDB:
    def __init__(self, pages=(), page=None, content="", set_status_error=None):
        self.pages, self.page, self.content = list(pages), page, content
        self.created, self.statuses = [], []
        self.set_status_error = set_status_error

    def ensure(self, parent, meta):
        meta.set_meta("data_source_id", "ds_1")
        return "ds_1"

    def query(self, ds, filt):
        self.last_filter = filt
        return self.pages

    def find_page_by_mem_id(self, ds, mem_id):
        return self.page

    def create_page(self, ds, memory):
        self.created.append(memory)
        return "pg_new"

    def page_content(self, page_id):
        return self.content

    def set_status(self, page_id, status):
        if self.set_status_error is not None:
            raise self.set_status_error
        self.statuses.append((page_id, status))


def _store(db, cfg=None):
    s = MemoryStore.__new__(MemoryStore)
    s.db, s.config = db, (cfg or Config({}, ""))
    s.meta = ConfigMeta(s.config)
    return s


def test_remember_builds_memory_and_echoes_concepts():
    db = FakeDB()
    out = _store(db).remember("첫 줄 제목\n본문", mem_type="preference",
                              concepts=["a", "b"], project="p", files=["x.py"],
                              source="claude", links=[])
    mem = db.created[0]
    assert mem["type"] == "preference" and mem["source"] == "claude"
    assert mem["title"] == "첫 줄 제목" and mem["strength"] == 7
    assert mem["project"] == "p" and mem["files"] == ["x.py"]
    assert out["mem_id"] == mem["id"] and out["page_id"] == "pg_new"
    assert out["concepts"] == ["a", "b"]


def test_remember_title_strips_leading_hashes_only():
    db = FakeDB()
    _store(db).remember("# #tag 로 시작하는 제목\n본문", mem_type="fact")
    assert db.created[0]["title"] == "#tag 로 시작하는 제목"  # 선두 '# '만 제거, 내용의 #은 보존


def test_remember_link_urls_become_page_ids():
    db = FakeDB()
    hex32 = "a488cdd5b1e24f0e8b1cdd5b1e24f0e8"
    _store(db).remember("c", mem_type="fact",
                        links=[f"https://www.notion.so/Note-{hex32}"])
    assert db.created[0]["linkPageIds"] == ["a488cdd5-b1e2-4f0e-8b1c-dd5b1e24f0e8"]


def test_remember_supersedes_marks_old_page():
    db = FakeDB(page={"id": "pg_old"})
    _store(db).remember("new", mem_type="fact", supersedes="mem_old")
    assert db.statuses == [("pg_old", "Superseded")]


def test_remember_supersedes_missing_raises():
    db = FakeDB(page=None)
    with pytest.raises(ValueError):
        _store(db).remember("new", mem_type="fact", supersedes="mem_x")
    assert db.created == []  # 대상 확인이 저장보다 먼저


def test_remember_supersede_failure_still_returns_new_mem_id():
    # create_page 성공 후 set_status 가 실패해도 새 mem_id는 유실되면 안 된다.
    db = FakeDB(page={"id": "pg_old"}, set_status_error=RuntimeError("429 exhausted"))
    out = _store(db).remember("new", mem_type="fact", supersedes="mem_old")
    assert len(db.created) == 1  # 페이지는 이미 생성됨
    assert out["mem_id"] == db.created[0]["id"]
    assert out["page_id"] == "pg_new"
    assert out["supersede_error"] == "429 exhausted"
    assert out["supersede_target"] == "pg_old"


def test_recall_scores_filters_and_caps_top():
    pages = [_page("m1", "jwt rotation", ["jwt"], "jwt", "2026-07-01T00:00:00.000Z"),
             _page("m2", "기타", [], "jwt 언급", "2026-07-02T00:00:00.000Z"),
             _page("m3", "무관", [], "없음", "2026-07-03T00:00:00.000Z")]
    out = _store(FakeDB(pages=pages)).recall("jwt", top=1)
    assert out["fallback"] is False
    assert [r["mem_id"] for r in out["results"]] == ["m1"]  # 최고점만 (top=1)


def test_recall_tie_breaks_by_recency():
    pages = [_page("old", "jwt", [], "", "2026-07-01T00:00:00.000Z"),
             _page("new", "jwt", [], "", "2026-07-10T00:00:00.000Z")]
    out = _store(FakeDB(pages=pages)).recall("jwt", top=5)
    assert [r["mem_id"] for r in out["results"]] == ["new", "old"]


def test_recall_zero_hits_falls_back_to_recent():
    pages = [_page("m1", "a", [], "", "2026-07-01T00:00:00.000Z"),
             _page("m2", "b", [], "", "2026-07-05T00:00:00.000Z")]
    out = _store(FakeDB(pages=pages)).recall("없는검색어", top=1)
    assert out["fallback"] is True
    assert [r["mem_id"] for r in out["results"]] == ["m2"]  # 최근 수정순


def test_recall_empty_query_is_recent_fallback():
    pages = [_page("m1", "a", [], "", "2026-07-01T00:00:00.000Z")]
    out = _store(FakeDB(pages=pages)).recall("", top=5)
    assert out["fallback"] is True and len(out["results"]) == 1


def test_recall_passes_server_filter_without_project():
    db = FakeDB(pages=[])
    _store(db).recall("q", mem_type="bug", project="p", top=5)
    assert db.last_filter == build_filter(mem_type="bug")


def test_recall_scopes_project_client_side():
    pages = [_page("mine", "jwt", project="p"),
             _page("shared", "jwt", project=""),
             _page("other", "jwt", project="q")]
    out = _store(FakeDB(pages=pages)).recall("jwt", project="p", top=5)
    assert sorted(r["mem_id"] for r in out["results"]) == ["mine", "shared"]


def test_recall_unseen_project_is_empty_fallback_not_error():
    # 새 프로젝트(스키마에 없는 Project 옵션)에서 recall 해도 400 없이 폴백해야 한다.
    pages = [_page("m1", "a", project="p")]
    out = _store(FakeDB(pages=pages)).recall("a", project="brand-new", top=5)
    assert out["fallback"] is True and out["results"] == []


def test_get_returns_summary_with_content():
    db = FakeDB(page=_page("m1", "T"), content="본문 전체")
    got = _store(db).get("m1")
    assert got["mem_id"] == "m1" and got["content"] == "본문 전체"


def test_get_missing_returns_none():
    assert _store(FakeDB(page=None)).get("mem_x") is None


def test_forget_sets_status_or_false():
    db = FakeDB(page={"id": "pg_1"})
    assert _store(db).forget("m1") is True
    assert db.statuses == [("pg_1", "Forgotten")]
    assert _store(FakeDB(page=None)).forget("m_x") is False


# ── 포인터(Files/Link) 노출 ────────────────────────────
# git 캡처는 diff 원문을 저장하지 않고 해시·Files·Link 포인터만 남긴다. 그 포인터가
# 저장은 되는데 page_summary 가 뽑지를 않아 recall 출력에 한 번도 나온 적이 없었다 —
# 그래서 에이전트는 "그런 결정이 있었다"까지만 받고 "그 코드가 어디 있다"는 못 받았다.

def _page_with_pointers(files="a.py, b.py", url="https://github.com/o/r/commit/abc"):
    page = _page("mem_1", "T")
    page["properties"]["Files"] = {"rich_text": [{"plain_text": files}]}
    page["properties"]["Link"] = {"url": url}
    return page


def test_page_summary_exposes_files_and_url():
    s = page_summary(_page_with_pointers())
    assert s["files"] == ["a.py", "b.py"]
    assert s["url"] == "https://github.com/o/r/commit/abc"


def test_page_summary_pointers_default_to_empty():
    s = page_summary(_page("mem_1", "T"))
    assert s["files"] == [] and s["url"] == ""


def test_page_summary_files_ignores_blank_entries():
    """Files 는 ', '.join 으로 저장된 평문이라 빈 값·여분 공백이 섞일 수 있다."""
    s = page_summary(_page_with_pointers(files="a.py,  , b.py, "))
    assert s["files"] == ["a.py", "b.py"]


def test_page_summary_url_tolerates_null_link():
    """Link 는 url 프로퍼티라 값이 없으면 None 이 온다(빈 dict 가 아니라)."""
    page = _page("mem_1", "T")
    page["properties"]["Link"] = {"url": None}
    assert page_summary(page)["url"] == ""
