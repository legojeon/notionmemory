import math

from notionmemory.skills.memory import mem_index
from notionmemory.skills.memory import mem_index as mi


def _mem(mid, title, concepts, strength=7, typ="fact", project="p", status="Active", excerpt=""):
    return {"id": mid, "title": title, "concepts": list(concepts), "strength": strength,
            "type": typ, "project": project, "status": status, "content": excerpt}


def test_build_excludes_brief_and_keeps_fields():
    idx = mi.build([_mem("m1", "jwt refresh", ["jwt-refresh"], 9),
                    _mem("b1", "brief", [], 10, typ="brief")])
    d = mi.docs(idx)
    assert "m1" in d and "b1" not in d
    assert d["m1"]["strength"] == 9 and d["m1"]["concepts"] == ["jwt-refresh"]


def test_search_scores_and_strength_weights_and_gates():
    idx = mi.build([_mem("m1", "jwt refresh rotation", ["jwt-refresh"], 9),
                    _mem("m2", "unrelated note", ["cooking"], 3)])
    hits = mi.search(idx, "how did we do jwt refresh", project="p", limit=3)
    assert [h["mem_id"] for h in hits] == ["m1"]  # 관련만, 무관은 게이트 아래

    # Strength 가중: 동점 관련이면 고Strength 우선
    idx2 = mi.build([_mem("a", "token revocation", ["token-revocation"], 2),
                     _mem("b", "token revocation", ["token-revocation"], 10)])
    top = mi.search(idx2, "token revocation", project="p", limit=1)
    assert top[0]["mem_id"] == "b"


def test_search_project_scope_and_save_load(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.paths, "state_dir", lambda: tmp_path)
    idx = mi.build([_mem("m1", "alpha", ["a"], 8, project="proj-x")])
    mi.save(idx)
    assert mi.load() == idx
    assert mi.search(idx, "alpha", project="proj-y") == []  # 다른 프로젝트 → 없음


def _mems():
    return [
        {"id": "m1", "title": "JWT refresh rotation 결정", "concepts": ["jwt-refresh"],
         "content": "인증을 JWT refresh token 회전으로 변경. 만료 15분.",
         "strength": 8, "type": "architecture", "project": "p", "status": "Active",
         "last_edited": "2026-07-30T00:00:00Z"},
        {"id": "m2", "title": "일반 노트", "concepts": [],
         "content": "회의 내용 정리. token 이라는 단어가 한 번 나온다.",
         "strength": 3, "type": "fact", "project": "p", "status": "Active",
         "last_edited": "2026-07-29T00:00:00Z"},
        {"id": "m3", "title": "브리프", "concepts": [], "content": "롤업",
         "strength": 10, "type": "brief", "project": "p", "status": "Active",
         "last_edited": "2026-07-28T00:00:00Z"},
    ]


def test_build_v2_shape_and_stats():
    idx = mem_index.build(_mems())
    assert idx["version"] == 2
    assert mem_index.count(idx) == 2                    # brief 제외
    d = mem_index.docs(idx)["m1"]
    assert d["excerpt"].startswith("인증을")
    assert d["tf"] and d["dl"] > 0
    assert idx["meta"]["n"] == 2 and idx["meta"]["avgdl"] > 0
    assert idx["meta"]["df"].get("jwt", 0) >= 1


def test_title_and_concepts_weighting_folded_into_tf():
    idx = mem_index.build(_mems())
    tf1 = mem_index.docs(idx)["m1"]["tf"]
    # 제목 토큰은 ×3, concepts ×2, 본문 ×1 로 접힌다 — jwt 는 제목+concepts+본문 출현
    assert tf1["jwt"] >= 3 + 2 + 1 - 1   # 최소 제목 가중이 반영된 값 (정확 값은 구현 고정)


def test_bm25_rare_term_beats_common_and_strength_boosts():
    idx = mem_index.build(_mems())
    hits = mem_index.search(idx, "jwt refresh 회전", project="p", min_score=0.01)
    assert [h["mem_id"] for h in hits][:1] == ["m1"]
    assert hits[0]["score"] > 0
    # Strength 부스트: 같은 문서라도 strength 10 이면 ×1.5
    lo = mem_index.build([dict(_mems()[0], id="lo", strength=0)])
    hi = mem_index.build([dict(_mems()[0], id="hi", strength=10)])
    s_lo = mem_index.search(lo, "jwt", min_score=0.001)[0]["score"]
    s_hi = mem_index.search(hi, "jwt", min_score=0.001)[0]["score"]
    assert math.isclose(s_hi / s_lo, 1.5, rel_tol=1e-6)


def test_korean_josa_absorption_still_recalls():
    mems = [{"id": "k1", "title": "쿠버네티스의 운영", "concepts": [],
             "content": "클러스터 운영 노트", "strength": 5, "type": "fact",
             "project": "", "status": "Active", "last_edited": "t"}]
    idx = mem_index.build(mems)
    assert mem_index.search(idx, "쿠버네티스", min_score=0.001)[0]["mem_id"] == "k1"


def test_gate_silences_weak_common_match():
    idx = mem_index.build(_mems())
    # 'token' 은 m2 본문에 1회 — 낮은 점수라 기본 게이트(1.0) 아래여야 침묵
    hits = mem_index.search(idx, "token", project="p")
    assert all(h["mem_id"] != "m2" for h in hits)


def test_legacy_v1_index_still_searchable_and_countable():
    v1 = {"m1": {"title": "JWT 회전", "concepts": ["jwt"], "excerpt": "refresh 회전",
                 "strength": 8, "type": "architecture", "project": "p",
                 "status": "Active"}}
    assert mem_index.count(v1) == 1
    hits = mem_index.search(v1, "jwt", project="p", min_score=0.001)
    assert hits and hits[0]["mem_id"] == "m1"


def test_status_and_brief_filters_preserved():
    mems = _mems() + [{"id": "gone", "title": "jwt", "concepts": [], "content": "jwt",
                       "strength": 9, "type": "fact", "project": "p",
                       "status": "Forgotten", "last_edited": "t"}]
    idx = mem_index.build(mems)
    ids = [h["mem_id"] for h in mem_index.search(idx, "jwt", min_score=0.001)]
    assert "gone" not in ids and "m3" not in ids


# ── fix round: C1 write-through (add_memory) ──────────────

def test_add_memory_incrementally_updates_v2_index(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.paths, "state_dir", lambda: tmp_path)
    old = _mem("old", "옛 메모리", ["a"], 5, excerpt="옛 내용")
    new = {"id": "new", "title": "jwt refresh rotation", "content": "본문",
           "type": "architecture", "concepts": ["jwt-refresh"], "strength": 8,
           "status": "Active", "project": "p", "last_edited": "t"}
    mi.save(mi.build([old]))

    mi.add_memory(new)

    idx = mi.load()
    docs = mi.docs(idx)
    assert "new" in docs and docs["new"]["title"] == "jwt refresh rotation"
    assert docs["new"]["strength"] == 8
    assert idx["meta"]["n"] == 2
    assert idx["meta"]["df"].get("jwt", 0) >= 1
    # 증분 avgdl 은 build() 로 두 문서를 한 번에 다시 계산한 것과 일치해야 한다.
    rebuilt = mi.build([old, new])
    assert math.isclose(idx["meta"]["avgdl"], rebuilt["meta"]["avgdl"], rel_tol=1e-9)


def test_add_memory_creates_fresh_v2_index_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.paths, "state_dir", lambda: tmp_path)
    assert mi.load() == {}

    mi.add_memory({"id": "m1", "title": "새 메모리", "content": "본문", "type": "fact",
                   "concepts": [], "strength": 5, "status": "Active", "project": "p",
                   "last_edited": "t"})

    idx = mi.load()
    assert idx["version"] == 2
    assert mi.count(idx) == 1
    assert mi.docs(idx)["m1"]["title"] == "새 메모리"


def test_add_memory_creates_fresh_v2_index_when_legacy_v1_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.paths, "state_dir", lambda: tmp_path)
    mi.save({})                          # 비어있는 v1(빈 평면 dict) — 부재와 동치로 취급

    mi.add_memory({"id": "m1", "title": "새 메모리", "content": "본문", "type": "fact",
                   "concepts": [], "strength": 5, "status": "Active", "project": "p",
                   "last_edited": "t"})

    idx = mi.load()
    assert idx["version"] == 2
    assert set(mi.docs(idx)) == {"m1"}


def test_add_memory_converts_populated_legacy_v1_instead_of_replacing_it(tmp_path, monkeypatch):
    """모든 기존 사용자가 v1→v2 업그레이드 직후 첫 remember 에서 겪는 경로 — 채워진 v1
    을 통째로 버리고 새 메모리 하나만 남기면, 다음 전체 reindex 전까지 로컬 경로의
    커버리지가 이 메모리 하나로 뭉개진다(C1 과 같은 부류의 '조용한 stale', 대상만
    색인 자체로 바뀐 것). 기존 v1 항목은 변환돼 살아남아야 하고(BM25 로 검색 가능),
    새 메모리도 함께 더해져야 한다."""
    monkeypatch.setattr(mi.paths, "state_dir", lambda: tmp_path)
    mi.save({
        "v1a": {"title": "JWT 회전", "concepts": ["jwt"], "excerpt": "refresh 회전 정책",
               "strength": 8, "type": "architecture", "project": "p", "status": "Active"},
        "v1b": {"title": "쿠버네티스 운영", "concepts": [], "excerpt": "클러스터 운영 노트",
               "strength": 5, "type": "fact", "project": "p", "status": "Active"},
    })

    mi.add_memory({"id": "new", "title": "새 메모리", "content": "본문", "type": "fact",
                   "concepts": [], "strength": 5, "status": "Active", "project": "p",
                   "last_edited": "t"})

    idx = mi.load()
    assert idx["version"] == 2
    assert mi.count(idx) == 3
    assert idx["meta"]["n"] == 3
    docs = mi.docs(idx)
    assert set(docs) == {"v1a", "v1b", "new"}
    assert docs["v1a"]["excerpt"] == "refresh 회전 정책"      # v1 의 excerpt → v2 의 발췌
    # 변환된 옛 항목이 BM25 경로로 계속 검색 가능해야 한다(read-only 로 죽지 않는다).
    assert mi.search(idx, "jwt 회전", min_score=0.001)[0]["mem_id"] == "v1a"
    assert mi.search(idx, "쿠버네티스", min_score=0.001)[0]["mem_id"] == "v1b"


def test_add_memory_skips_brief_and_missing_id(tmp_path, monkeypatch):
    monkeypatch.setattr(mi.paths, "state_dir", lambda: tmp_path)

    mi.add_memory({"id": "b1", "title": "브리프", "content": "롤업", "type": "brief",
                   "concepts": [], "strength": 10, "status": "Active", "project": "p",
                   "last_edited": "t"})
    mi.add_memory({"title": "id 없음", "content": "x", "type": "fact", "concepts": [],
                   "strength": 5, "status": "Active", "project": "p", "last_edited": "t"})

    assert mi.load() == {}               # 둘 다 스킵 — 색인 파일조차 만들어지지 않는다


# ── fix round: I2 --type prefilter before truncation ──────

def test_search_mem_type_prefilters_before_limit_truncation():
    """색인 검색이 limit(top*2 상당) 으로 자르기 전에 mem_type 을 걸지 않으면, 더 높은
    score 의 다른 type 문서가 절단 안을 채워 사후 필터 후 후보가 말라버린다."""
    mems = [_mem(f"fact{i}", "공통 제목 매치", [], strength=0, typ="fact")
            for i in range(12)] + [
            _mem(f"bug{i}", "공통 제목 매치", [], strength=20, typ="bug")
            for i in range(8)]
    for m in mems:
        m["content"] = "본문 매치"
    idx = mi.build(mems)

    # 옛 버그 재현: mem_type 없이 top*2=10 으로 자른 뒤 타입을 사후 필터하면 bug(더 높은
    # strength 부스트) 8개가 절단 안을 채워 fact 는 2개만 남는다.
    unfiltered_top10 = mi.search(idx, "공통 제목 매치", limit=10, min_score=0.0)
    assert len([h for h in unfiltered_top10 if h["type"] == "fact"]) == 2

    # mem_type 선필터: 절단 전에 걸러 12개 fact 후보가 전부 살아남는다.
    prefiltered = mi.search(idx, "공통 제목 매치", mem_type="fact", limit=100, min_score=0.0)
    assert len(prefiltered) == 12
    assert all(h["type"] == "fact" for h in prefiltered)


# ── fix round: I3 docs() must not treat unknown version as v1 ──

def test_docs_treats_unknown_version_as_empty_not_flat_v1():
    """version 키가 있지만 2가 아니면(예: 3, 미래 포맷) 레거시 v1 평면으로 오인해
    meta/docs 같은 최상위 키를 mem_id 로 잘못 읽으면 안 된다 — 그러면 count()>0 이
    되고 뒤이은 search() 가 non-dict 항목에서 트레이스백을 낸다."""
    idx = {"version": 3, "meta": 1, "docs": {}}
    assert mem_index.docs(idx) == {}
    assert mem_index.count(idx) == 0


# ── 색인 슬림화: 전문 대신 발췌 200자 저장, tf 는 8000자 창에서 ──────

def test_build_stores_excerpt_only_tf_from_full_window():
    """v2 doc 은 전문(≤8000자)을 저장하지 않는다 — 표시용 발췌 200자만. 점수는
    사전계산 tf 로만 내므로 발췌 밖(>200자) 토큰도 계속 검색돼야 한다."""
    deep = "본문 시작. " + ("filler " * 100) + "deepwatermarkzz 끝."
    idx = mi.build([{"id": "m1", "title": "제목", "concepts": [], "content": deep,
                     "strength": 5, "type": "fact", "project": "p",
                     "status": "Active", "last_edited": ""}])
    d = mi.docs(idx)["m1"]
    assert "content" not in d
    assert d["excerpt"] == deep[:200]
    hits = mi.search(idx, "deepwatermarkzz", project="p", limit=3, min_score=0.001)
    assert [h["mem_id"] for h in hits] == ["m1"]
    assert hits[0]["excerpt"] == deep[:200]


def test_dup_id_rebuild_preserves_deep_tf(tmp_path, monkeypatch):
    """중복-id 재-add 의 전체 재빌드가 다른 doc 의 tf 를 200자 발췌에서 재계산하면
    발췌 밖 토큰이 조용히 사라진다 — 저장된 tf/dl 을 그대로 승계해야 한다."""
    monkeypatch.setattr(mi.paths, "state_dir", lambda: tmp_path)
    deep = "본문 시작. " + ("filler " * 100) + "deepwatermarkzz 끝."
    base = {"concepts": [], "strength": 5, "type": "fact", "project": "p",
            "status": "Active", "last_edited": ""}
    mi.save(mi.build([dict(base, id="a", title="깊은 문서", content=deep),
                      dict(base, id="b", title="다른 문서", content="짧은 본문")]))
    mi.add_memory(dict(base, id="b", title="다른 문서 v2", content="갱신 본문"))
    hits = mi.search(mi.load(), "deepwatermarkzz", project="p", limit=3, min_score=0.001)
    assert [h["mem_id"] for h in hits] == ["a"]


def test_add_memory_same_id_does_not_double_count_meta():
    """재리뷰 N1 — 같은 mem_id 재-add 는 증분 meta 이중계산 대신 전체 재빌드로
    처리한다(미래의 제자리-갱신 호출자 대비). 발췌 필드도 보존돼야 한다."""
    m1 = {"id": "m1", "title": "jwt 회전", "concepts": ["jwt"],
          "content": "refresh 회전 본문", "strength": 5, "type": "fact",
          "project": "p", "status": "Active", "last_edited": "t"}
    m2 = dict(m1, id="m2", title="다른 메모")
    mem_index.save(mem_index.build([m1, m2]))
    mem_index.add_memory(dict(m1, strength=9))       # 같은 id 재-add(갱신)
    idx = mem_index.load()
    assert mem_index.count(idx) == 2                  # 문서 수 불변
    assert idx["meta"]["n"] == 2                      # 이중계산 없음
    fresh = mem_index.build([dict(m1, strength=9), m2])
    assert idx["meta"]["df"] == fresh["meta"]["df"]
    assert abs(idx["meta"]["avgdl"] - fresh["meta"]["avgdl"]) < 1e-9
    assert mem_index.docs(idx)["m1"]["excerpt"] == "refresh 회전 본문"   # 발췌 보존
    assert mem_index.docs(idx)["m1"]["strength"] == 9
