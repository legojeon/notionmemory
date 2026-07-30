from notionmemory.skills.memory import mem_index as mi


def _mem(mid, title, concepts, strength=7, typ="fact", project="p", status="Active", excerpt=""):
    return {"id": mid, "title": title, "concepts": list(concepts), "strength": strength,
            "type": typ, "project": project, "status": status, "content": excerpt}


def test_build_excludes_brief_and_keeps_fields():
    idx = mi.build([_mem("m1", "jwt refresh", ["jwt-refresh"], 9),
                    _mem("b1", "brief", [], 10, typ="brief")])
    assert "m1" in idx and "b1" not in idx
    assert idx["m1"]["strength"] == 9 and idx["m1"]["concepts"] == ["jwt-refresh"]


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
