"""memory consolidate — Draft 검토(LLM)→승격/드롭/병합/브리프 upsert, 큐 드레인.

비중첩 전제(사용자 터미널/cron): FakeRuntime 이 결정적 JSON 을 돌려주고, FakeDB 가
Notion 쓰기를 기록만 한다. 큐는 실제 `consolidation_queue` 모듈을 env 격리로 쓴다
(git 큐 테스트와 같은 패턴 — 잡 소비/보존을 진짜 파일 상태로 검증)."""
from __future__ import annotations

import json

import pytest
import requests

from notionmemory.core.agent_runtime import AgentRuntimeError
from notionmemory.core.config import Config
from notionmemory.skills.memory import consolidate
from notionmemory.skills.memory import consolidation_queue as q
from notionmemory.skills.memory import transcripts

CFG = Config({"skills": {}})


@pytest.fixture
def qroot(tmp_path, monkeypatch):
    monkeypatch.setenv(q.QUEUE_ROOT_ENV, str(tmp_path / "memq"))
    return tmp_path / "memq"


@pytest.fixture(autouse=True)
def _noop_reindex(monkeypatch):
    """consolidate.run 은 성공 경로 끝에 항상 reindex.run(config, log) 을 부른다
    (best-effort 색인 갱신). 기본값으로 no-op 시켜 이 파일의 기존 테스트들이 실제
    Notion/keyring 을 건드리지 않게 한다 — 자동 트리거 자체를 검증하는 테스트만
    아래에서 다시 monkeypatch 해 호출을 기록한다."""
    monkeypatch.setattr(consolidate.reindex, "run", lambda cfg, log: 0)


class FakeRuntime:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    def generate(self, system, user):
        self.calls.append((system, user))
        return self.text


class FakeDB:
    """query_drafts/set_properties/find_page_by_mem_id/create_page/replace_content
    를 기록만 하는 페이크 — `db.props[page_id]` 로 마지막 set_properties 누적본을 본다."""

    def __init__(self, drafts):
        self.drafts = list(drafts)
        self.props: dict[str, dict] = {}
        self.created: list[dict] = []
        self.replaced: dict[str, str] = {}
        self.brief_page: dict | None = None

    def query_drafts(self, ds, project):
        return [d for d in self.drafts if not project or d["project"] == project]

    def set_properties(self, page_id, props):
        self.props.setdefault(page_id, {}).update(props)

    def find_page_by_mem_id(self, ds, mem_id):
        if mem_id.startswith("brief-"):
            return self.brief_page
        return None

    def create_page(self, ds, memory):
        self.created.append(memory)
        page_id = f"pg_{memory['id']}"
        if memory["id"].startswith("brief-"):
            self.brief_page = {"id": page_id}
        return page_id

    def replace_content(self, page_id, content):
        self.replaced[page_id] = content


def _draft(mem_id, project="proj", page_id=None, content="c", mem_type="fact"):
    return {"mem_id": mem_id, "page_id": page_id or f"{mem_id}_page",
            "type": mem_type, "concepts": [], "content": content, "project": project}


class FakeStoreFactory:
    """`MemoryStore(NotionSession(), config)` 자리를 대신하는 페이크 — `.db` 와
    `_data_source()` 만 있으면 consolidate.run 이 필요로 하는 전부다."""

    def __init__(self, db, ds="ds_1"):
        self.db, self.ds = db, ds

    def __call__(self, *a, **k):
        store = object.__new__(_FakeStore)
        store.db, store._ds = self.db, self.ds
        store.remembered = []
        return store


class _FakeStore:
    """`_data_source()`(기존)에 더해 `remember()` 를 흉내낸다 — `action:"new"` 발굴
    항목이 `store.remember(...)` 로 곧장 Active 로 랜딩하는 경로를 검증할 때 쓴다.
    실제 `MemoryStore.remember` 처럼 mem_id/page_id 를 새로 발급하고 호출 인자를
    `self.remembered` 에 그대로 기록한다."""

    def _data_source(self, *, create: bool = True):
        # 실제 MemoryStore 와 같은 계약(C1) — create=False 인데 아직 바인딩 전(빈 ds)
        # 이면 "" 를 돌려준다(부트스트랩 안 함). create=True 는 그대로 self._ds.
        if not self._ds and not create:
            return ""
        return self._ds

    def remember(self, content, *, mem_type, concepts=(), project="", source="manual",
                status="Active", strength=7):
        rec = {"content": content, "mem_type": mem_type, "concepts": list(concepts),
              "project": project, "source": source, "status": status, "strength": strength}
        self.remembered.append(rec)
        n = len(self.remembered)
        return {"mem_id": f"mined_{n}", "page_id": f"pg_mined_{n}", "concepts": list(concepts)}


@pytest.fixture
def fake_store():
    """`_apply()` 단위테스트용 최소 store — `.db`(빈 FakeDB) + `.remembered` 기록."""
    store = object.__new__(_FakeStore)
    store.db, store._ds = FakeDB([]), "ds_1"
    store.remembered = []
    return store


def _wire(monkeypatch, runtime_text, drafts):
    db = FakeDB(drafts)
    runtime = FakeRuntime(runtime_text)
    monkeypatch.setattr(consolidate, "build_runtime", lambda cfg: runtime)
    monkeypatch.setattr(consolidate, "MemoryStore", FakeStoreFactory(db))
    monkeypatch.setattr(consolidate, "NotionSession", lambda: object())
    return db, runtime


# ── 승격/드롭 + 브리프 ─────────────────────────────────

def test_consolidate_promotes_scores_drops_and_updates_brief(qroot, monkeypatch):
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    drafts = [_draft("m1"), _draft("m2")]
    fake_json = json.dumps({
        "items": [{"mem_id": "m1", "action": "keep", "strength": 9},
                  {"mem_id": "m2", "action": "drop"}],
        "merges": [], "brief": "- 결정 A"})
    db, runtime = _wire(monkeypatch, fake_json, drafts)

    res = consolidate.run(CFG, print, project="proj")

    assert res["promoted"] == 1 and res["dropped"] == 1
    assert db.props["m1_page"]["Strength"]["number"] == 9
    assert db.props["m1_page"]["Status"]["select"]["name"] == "Active"
    assert db.props["m2_page"]["Status"]["select"]["name"] == "Forgotten"
    assert res["brief_updated"] is True
    assert db.created[0]["id"] == "brief-proj"
    assert db.created[0]["type"] == "brief" and db.created[0]["strength"] == 10
    assert "error" not in res
    assert q.list_jobs() == []                       # 성공 → ack


def test_consolidate_updates_existing_brief_in_place(qroot, monkeypatch):
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    fake_json = json.dumps({"items": [], "merges": [], "brief": "- 업데이트된 브리프"})
    db, _ = _wire(monkeypatch, fake_json, [_draft("m1")])
    db.brief_page = {"id": "pg_brief_existing"}       # 이미 브리프 페이지가 있음

    res = consolidate.run(CFG, print, project="proj")

    assert res["brief_updated"] is True
    assert db.created == []                            # create 아닌 update 경로
    assert db.props["pg_brief_existing"]["Strength"]["number"] == 10
    assert db.replaced["pg_brief_existing"] == "- 업데이트된 브리프"


# ── 병합 ────────────────────────────────────────────────

def test_consolidate_merge_losers_become_superseded(qroot, monkeypatch):
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    drafts = [_draft("m1"), _draft("m2"), _draft("m3")]
    fake_json = json.dumps({
        "items": [{"mem_id": "m1", "action": "keep", "strength": 8}],
        "merges": [{"keep": "m1", "drop": ["m2", "m3"]}],
        "brief": ""})
    db, _ = _wire(monkeypatch, fake_json, drafts)

    res = consolidate.run(CFG, print, project="proj")

    assert res["merged"] == 2
    assert db.props["m2_page"]["Status"]["select"]["name"] == "Superseded"
    assert db.props["m3_page"]["Status"]["select"]["name"] == "Superseded"
    assert res["brief_updated"] is False               # 빈 문자열 브리프는 upsert 안 함


# ── 실패 경로: LLM 실패 → Draft/큐 보존 ────────────────

def test_consolidate_preserves_drafts_on_llm_failure(qroot, monkeypatch):
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    db = FakeDB([_draft("m1")])
    monkeypatch.setattr(consolidate, "build_runtime",
                        lambda cfg: (_ for _ in ()).throw(AgentRuntimeError("boom")))
    monkeypatch.setattr(consolidate, "MemoryStore", FakeStoreFactory(db))
    monkeypatch.setattr(consolidate, "NotionSession", lambda: object())

    res = consolidate.run(CFG, print, project="proj")

    assert q.list_jobs() != []                         # 잡 보존(ack 안 됨)
    assert res.get("error")
    assert db.props == {}                               # Draft 무변경


def test_consolidate_preserves_drafts_on_bad_json(qroot, monkeypatch):
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    db, _ = _wire(monkeypatch, "이건 JSON이 아니다", [_draft("m1")])

    res = consolidate.run(CFG, print, project="proj")

    assert q.list_jobs() != []
    assert res.get("error")
    assert db.props == {}


def test_consolidate_strips_code_fence_before_parsing(qroot, monkeypatch):
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    fenced = "```json\n" + json.dumps({
        "items": [{"mem_id": "m1", "action": "keep", "strength": 7}],
        "merges": [], "brief": ""}) + "\n```"
    db, _ = _wire(monkeypatch, fenced, [_draft("m1")])

    res = consolidate.run(CFG, print, project="proj")

    assert res["promoted"] == 1
    assert "error" not in res


# ── 큐/프로젝트 스코프 ──────────────────────────────────

def test_consolidate_no_jobs_is_noop(qroot):
    res = consolidate.run(CFG, print, project="proj")
    assert res == {"promoted": 0, "dropped": 0, "merged": 0, "brief_updated": False, "mined": 0}


def test_consolidate_project_filter_ignores_other_projects_jobs(qroot, monkeypatch):
    q.enqueue("other", "/cwd", "2026-07-29T00:00:00Z")
    db, runtime = _wire(monkeypatch, "{}", [_draft("m1", project="proj")])

    res = consolidate.run(CFG, print, project="proj")

    assert res == {"promoted": 0, "dropped": 0, "merged": 0, "brief_updated": False, "mined": 0}
    assert runtime.calls == []                          # LLM 호출 자체가 안 됨
    assert len(q.list_jobs()) == 1                       # other 잡은 그대로


def test_consolidate_processes_multiple_projects_and_partial_failure(qroot, monkeypatch):
    q.enqueue("good", "/cwd", "2026-07-29T00:00:00Z")
    q.enqueue("bad", "/cwd", "2026-07-29T00:00:01Z")
    drafts = [_draft("g1", project="good"), _draft("b1", project="bad")]
    db = FakeDB(drafts)

    calls = {"n": 0}

    class MultiRuntime:
        def generate(self, system, user):
            calls["n"] += 1
            if "bad" in user:
                raise AgentRuntimeError("bad project boom")
            return json.dumps({"items": [{"mem_id": "g1", "action": "keep", "strength": 6}],
                               "merges": [], "brief": ""})

    monkeypatch.setattr(consolidate, "build_runtime", lambda cfg: MultiRuntime())
    monkeypatch.setattr(consolidate, "MemoryStore", FakeStoreFactory(db))
    monkeypatch.setattr(consolidate, "NotionSession", lambda: object())

    res = consolidate.run(CFG, print)

    assert res["promoted"] == 1
    assert res.get("error") and "bad" in res["error"]
    remaining = q.list_jobs()
    assert len(remaining) == 1 and remaining[0]["project"] == "bad"  # good 만 ack


def test_consolidate_drafts_missing_for_project_still_acks_stale_job(qroot, monkeypatch):
    # 초안이 이미 다 정리된(또는 아예 없는) 프로젝트의 고아 잡 — LLM 호출 없이 잡만 정리.
    q.enqueue("empty", "/cwd", "2026-07-29T00:00:00Z")
    db, runtime = _wire(monkeypatch, "{}", [])

    res = consolidate.run(CFG, print, project="empty")

    assert res == {"promoted": 0, "dropped": 0, "merged": 0, "brief_updated": False, "mined": 0}
    assert runtime.calls == []
    assert q.list_jobs() == []


# ── Fix round 1 ──────────────────────────────────────────

def test_consolidate_partial_write_failure_leaves_job_queued_then_retry_is_safe(
        qroot, monkeypatch):
    """mid-loop Notion 쓰기 실패 → job 미ack, {"error":...} 반환(트레이스백 없음),
    이미 반영된 앞부분은 그대로 둔다(품질 저하, 데이터 유실 아님). 재실행하면 이미
    Draft 를 벗어난 페이지는 다시 안 건드리고 나머지만 처리해 정상 완료된다."""
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    fake_json = json.dumps({
        "items": [{"mem_id": "m1", "action": "keep", "strength": 8},
                  {"mem_id": "m2", "action": "drop"}],
        "merges": [], "brief": ""})
    db, runtime = _wire(monkeypatch, fake_json, [_draft("m1"), _draft("m2")])

    calls = {"n": 0}
    real_set_properties = db.set_properties

    def flaky(page_id, props):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("Notion 500")
        real_set_properties(page_id, props)

    db.set_properties = flaky

    res = consolidate.run(CFG, print, project="proj")

    assert res.get("error")
    assert q.list_jobs() != []                          # job 보존
    assert db.props["m1_page"]["Status"]["select"]["name"] == "Active"  # 앞부분은 반영됨
    assert "m2_page" not in db.props                      # 실패한 항목은 미반영

    # 재시도: m1 은 더 이상 Draft 가 아니므로 다음 query_drafts 에 안 잡힌다고 가정
    db.set_properties = real_set_properties
    db.drafts = [d for d in db.drafts if d["mem_id"] != "m1"]

    res2 = consolidate.run(CFG, print, project="proj")

    assert "error" not in res2
    assert res2["dropped"] == 1
    assert q.list_jobs() == []


def test_consolidate_isolates_network_error_per_project(qroot, monkeypatch):
    """한 프로젝트에서 requests.RequestException 이 나도 같은 run() 안의 다른
    프로젝트는 계속 처리된다(flusher.py 와 동일 규율)."""
    q.enqueue("good", "/cwd", "2026-07-29T00:00:00Z")
    q.enqueue("flaky", "/cwd", "2026-07-29T00:00:01Z")
    drafts = [_draft("g1", project="good"), _draft("f1", project="flaky")]
    db = FakeDB(drafts)
    good_json = json.dumps({"items": [{"mem_id": "g1", "action": "drop"}],
                            "merges": [], "brief": ""})

    class NetworkFlakyRuntime:
        def generate(self, system, user):
            if "flaky" in user:
                raise requests.ConnectionError("offline")
            return good_json

    monkeypatch.setattr(consolidate, "build_runtime", lambda cfg: NetworkFlakyRuntime())
    monkeypatch.setattr(consolidate, "MemoryStore", FakeStoreFactory(db))
    monkeypatch.setattr(consolidate, "NotionSession", lambda: object())

    res = consolidate.run(CFG, print)

    assert res["dropped"] == 1
    assert res.get("error") and "flaky" in res["error"]
    remaining = q.list_jobs()
    assert len(remaining) == 1 and remaining[0]["project"] == "flaky"


def test_consolidate_bootstrap_network_error_returns_clean_error(qroot, monkeypatch):
    """store bootstrap(_data_source) 단계의 네트워크 오류도 트레이스백 없이 정리된
    {"error":...} 로 반환하고 큐를 건드리지 않는다."""
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")

    class FailingBootstrapStore:
        def __init__(self, *a, **k):
            raise requests.ConnectionError("offline")

    monkeypatch.setattr(consolidate, "build_runtime", lambda cfg: FakeRuntime("{}"))
    monkeypatch.setattr(consolidate, "MemoryStore", FailingBootstrapStore)
    monkeypatch.setattr(consolidate, "NotionSession", lambda: object())

    res = consolidate.run(CFG, print, project="proj")

    assert res.get("error")
    assert len(q.list_jobs()) == 1


# ── Strength clamp ───────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [(15, 10), (-3, 1), ("abc", 5), (None, 5)])
def test_consolidate_clamps_strength_before_writing(qroot, monkeypatch, raw, expected):
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    fake_json = json.dumps({"items": [{"mem_id": "m1", "action": "keep", "strength": raw}],
                            "merges": [], "brief": ""})
    db, _ = _wire(monkeypatch, fake_json, [_draft("m1")])

    res = consolidate.run(CFG, print, project="proj")

    assert "error" not in res
    assert db.props["m1_page"]["Strength"]["number"] == expected


# ── Defensive parse of malformed LLM output ──────────────

def test_consolidate_skips_malformed_items_without_crashing(qroot, monkeypatch):
    """mem_id 가 리스트인 항목(비-해시가능 타입), dict 가 아닌 item, 존재하지 않는
    mem_id, 알 수 없는 action 이 섞여 있어도 트레이스백 없이 정상 항목만 반영된다."""
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    fake_json = json.dumps({
        "items": [
            {"mem_id": ["m1"], "action": "keep", "strength": 9},   # mem_id 가 리스트
            "그냥 문자열",                                          # dict 아님
            {"mem_id": "nope", "action": "keep", "strength": 9},   # 존재하지 않는 mem_id
            {"mem_id": "m2", "action": "explode"},                  # 알 수 없는 action
            {"mem_id": "m1", "action": "keep", "strength": 7},      # 정상 항목
        ],
        "merges": [{"keep": "m1", "drop": [["m2"], "m1", "m2"]}],   # loser 가 리스트인 것도 섞임
        "brief": ""})
    db, _ = _wire(monkeypatch, fake_json, [_draft("m1"), _draft("m2")])

    res = consolidate.run(CFG, print, project="proj")

    assert "error" not in res
    # merges: 리스트 loser 무시, "m1"은 keep 과 같아 스킵, "m2"만 실제로 superseded
    assert res["merged"] == 1
    assert db.props["m2_page"]["Status"]["select"]["name"] == "Superseded"
    # items: m2 는 이미 merge 로 superseded 됐으니 "explode" 액션이든 아니든 건너뛰어
    # Superseded 그대로다(다시 덮어써지지 않음).
    assert db.props["m2_page"]["Status"]["select"]["name"] == "Superseded"
    # m1 은 정상 keep 항목이 반영됨
    assert db.props["m1_page"]["Status"]["select"]["name"] == "Active"
    assert db.props["m1_page"]["Strength"]["number"] == 7
    assert q.list_jobs() == []


# ── fix round: I4 프롬프트 창을 저장된 Excerpt 창(6000)에 맞춘다 ──

def test_build_prompt_widens_excerpt_cap_to_6000():
    """Draft 는 저장된 Excerpt 창(excerpt_rt 의 3×2000 유닛 청크, ≈6000)에서 읽힌다 —
    프롬프트 구축이 그보다 좁은 상한(옛 1500)으로 자르면 저장 창을 다시 좁히는
    꼴이 된다."""
    from notionmemory.skills.memory.consolidate import _build_prompt
    long_content = "x" * 7000
    prompt = _build_prompt("proj", [{"mem_id": "m1", "type": "fact", "concepts": [],
                                     "content": long_content}])
    assert "content: " + "x" * 6000 in prompt
    assert "x" * 6001 not in prompt


# ── 검색지향 프롬프트 + concepts (Task 5) ─────────────────

def test_system_prompt_demands_searchable_distillation():
    from notionmemory.skills.memory.consolidate import SYSTEM
    for marker in ("고유명사", "수치", "그대로 보존", "concepts", "3~6"):
        assert marker in SYSTEM, marker


def test_apply_updates_concepts_when_present(qroot, monkeypatch):
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    fake_json = json.dumps({
        "items": [
            {"mem_id": "m1", "action": "keep", "strength": 8,
             "concepts": ["jwt-refresh", "만료,정책"]},
            {"mem_id": "m2", "action": "keep", "strength": 6},
        ],
        "merges": [], "brief": ""})
    db, _ = _wire(monkeypatch, fake_json, [_draft("m1"), _draft("m2")])

    res = consolidate.run(CFG, print, project="proj")

    assert "error" not in res
    assert db.props["m1_page"]["Concepts"] == {
        "multi_select": [{"name": "jwt-refresh"}, {"name": "만료·정책"}]}
    assert "Concepts" not in db.props["m2_page"]


def test_apply_skips_concepts_when_all_invalid(qroot, monkeypatch):
    """M9a — concepts 가 전부 비-문자열(예: dict)이면 정제 결과가 빈 리스트가 된다.
    그걸 그대로 Concepts:[] 로 써버리면 기존 Concepts 옵션을 지워버리는 사고가 나므로
    정제 결과가 비면 Concepts 키 자체를 안 보내야 한다(no-op, 기존 값 보존)."""
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    fake_json = json.dumps({
        "items": [{"mem_id": "m1", "action": "keep", "strength": 7,
                   "concepts": [{"x": 1}]}],
        "merges": [], "brief": ""})
    db, _ = _wire(monkeypatch, fake_json, [_draft("m1")])

    res = consolidate.run(CFG, print, project="proj")

    assert "error" not in res
    assert "Concepts" not in db.props["m1_page"]


# ── reindex 자동 트리거 (Task 2) ──────────────────────────

def test_consolidate_triggers_reindex_after_success(qroot, monkeypatch):
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    fake_json = json.dumps({"items": [{"mem_id": "m1", "action": "keep", "strength": 8}],
                            "merges": [], "brief": ""})
    _wire(monkeypatch, fake_json, [_draft("m1")])
    calls = []
    monkeypatch.setattr(consolidate.reindex, "run",
                        lambda cfg, log: calls.append((cfg, log)) or 3)

    res = consolidate.run(CFG, print, project="proj")

    assert "error" not in res
    assert len(calls) == 1 and calls[0][0] is CFG


def test_consolidate_reindex_failure_does_not_fail_consolidation(qroot, monkeypatch):
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    fake_json = json.dumps({"items": [{"mem_id": "m1", "action": "keep", "strength": 8}],
                            "merges": [], "brief": ""})
    db, _ = _wire(monkeypatch, fake_json, [_draft("m1")])

    def boom(cfg, log):
        raise RuntimeError("색인 디스크 오류")

    monkeypatch.setattr(consolidate.reindex, "run", boom)

    res = consolidate.run(CFG, print, project="proj")

    assert "error" not in res
    assert res["promoted"] == 1
    assert db.props["m1_page"]["Status"]["select"]["name"] == "Active"  # consolidate 성공은 유효


# ── 세션 발췌 발굴 (Task 3) ────────────────────────────────

def _claude_line(role, content):
    return json.dumps({"type": role, "isSidechain": False,
                       "message": {"role": role, "content": content}}, ensure_ascii=False)


def _write_transcript(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _enqueue_session(project, sid, transcript_path, harness="claude",
                     ts="2026-08-01T00:00:00Z"):
    q.enqueue(project, "/cwd", ts,
             session={"session_id": sid, "transcript_path": str(transcript_path),
                      "harness": harness, "ts": ts})


def test_prompt_includes_excerpts_and_active_dedup_context():
    drafts = [{"mem_id": "m1", "type": "fact", "concepts": ["a"], "content": "d"}]
    excerpts = [{"session_id": "s1", "harness": "claude", "text": "[user] 결정 X"}]
    active = [{"title": "기존 결정", "concepts": ["x-y"]}]
    p = consolidate._build_prompt("proj", drafts, excerpts=excerpts, active_summaries=active)
    assert "세션 대화 발췌" in p and "[user] 결정 X" in p
    assert "기존 결정" in p and "이미 커버" in consolidate.SYSTEM


def test_apply_creates_new_item_as_active(fake_store):
    result = {"items": [{"action": "new", "type": "architecture",
                         "content": "BM25 로 간다\n근거...", "concepts": ["bm25-choice"],
                         "strength": 8}], "merges": [], "brief": ""}
    totals = dict(consolidate._EMPTY_TOTALS)
    consolidate._apply(fake_store, "ds", "proj", [], result, totals,
                       harness_by_default="claude")
    assert totals["mined"] == 1
    saved = fake_store.remembered[0]
    assert saved["status"] == "Active" and saved["strength"] == 8
    assert saved["mem_type"] == "architecture"


def test_apply_new_item_invalid_type_falls_back_to_fact(fake_store):
    result = {"items": [{"action": "new", "type": "not-a-real-type",
                         "content": "그래도 저장은 된다", "strength": 5}],
             "merges": [], "brief": ""}
    totals = dict(consolidate._EMPTY_TOTALS)
    consolidate._apply(fake_store, "ds", "proj", [], result, totals,
                       harness_by_default="claude")
    assert fake_store.remembered[0]["mem_type"] == "fact"


def test_apply_new_item_with_empty_content_is_ignored(fake_store):
    result = {"items": [{"action": "new", "type": "fact", "content": "   ", "strength": 5}],
             "merges": [], "brief": ""}
    totals = dict(consolidate._EMPTY_TOTALS)
    consolidate._apply(fake_store, "ds", "proj", [], result, totals,
                       harness_by_default="claude")
    assert totals["mined"] == 0
    assert fake_store.remembered == []


def test_apply_new_item_uses_harness_default_as_source(fake_store):
    result = {"items": [{"action": "new", "type": "fact", "content": "출처 확인용",
                         "strength": 4}], "merges": [], "brief": ""}
    totals = dict(consolidate._EMPTY_TOTALS)
    consolidate._apply(fake_store, "ds", "proj", [], result, totals,
                       harness_by_default="codex")
    assert fake_store.remembered[0]["source"] == "codex"


def test_run_mines_when_no_drafts_but_sessions_exist(qroot, tmp_path, monkeypatch):
    # 큐: drafts 0 + 세션 1(발췌 임계치 이상) → 예전엔 ack-and-skip 하던 경로가 이제
    # LLM 패스를 돈다.
    transcript = _write_transcript(tmp_path, "s1.jsonl", [
        _claude_line("user", "x" * 2100),
        _claude_line("user", "y" * 2100),
    ])
    _enqueue_session("proj", "s1", transcript)
    fake_json = json.dumps({
        "items": [{"action": "new", "type": "fact", "content": "발굴된 사실", "strength": 5}],
        "merges": [], "brief": ""})
    db, runtime = _wire(monkeypatch, fake_json, [])   # drafts 없음

    res = consolidate.run(CFG, print, project="proj")

    assert runtime.calls                                # LLM 이 실제로 불림
    assert "세션 대화 발췌" in runtime.calls[0][1]
    assert res["mined"] == 1
    assert q.list_jobs() == []                          # 성공 → ack


def test_run_skips_llm_below_min_excerpt_chars(qroot, tmp_path, monkeypatch):
    # drafts 0 + 발췌 합계가 MIN_EXCERPT_CHARS 미만 → generate 미호출, 잡 미ack(보존).
    transcript = _write_transcript(tmp_path, "s1.jsonl", [_claude_line("user", "x" * 100)])
    _enqueue_session("proj", "s1", transcript)
    db, runtime = _wire(monkeypatch, "{}", [])          # drafts 없음

    res = consolidate.run(CFG, print, project="proj")

    assert not runtime.calls
    assert res["mined"] == 0
    assert q.list_jobs()                                # 큐 보존 — ack 안 됨


def test_run_gate_still_acks_when_no_drafts_and_no_sessions(qroot, monkeypatch):
    """레거시 잡(sessions 없음) + drafts 도 없음 — 기존 ack-and-skip 동작 유지."""
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")   # session 인자 없음
    db, runtime = _wire(monkeypatch, "{}", [])

    res = consolidate.run(CFG, print, project="proj")

    assert not runtime.calls
    assert q.list_jobs() == []


def test_run_updates_ledger_on_success(qroot, tmp_path, monkeypatch):
    transcript = _write_transcript(tmp_path, "s1.jsonl", [
        _claude_line("user", "x" * 2100),
        _claude_line("user", "y" * 2100),
    ])
    _enqueue_session("proj", "s1", transcript)
    fake_json = json.dumps({"items": [], "merges": [], "brief": ""})
    db, runtime = _wire(monkeypatch, fake_json, [])

    res = consolidate.run(CFG, print, project="proj")

    assert "error" not in res
    led = transcripts.load_ledger()
    assert led["s1"]["bytes"] > 0


# ── fix round 1 ────────────────────────────────────────────

def test_run_survives_ledger_write_failure_and_still_acks(qroot, tmp_path, monkeypatch):
    """finding 1(reviewer) — `save_ledger` 는 내부적으로 mkdir/write_text 를 하고 OSError
    를 안 삼킨다. 이게 per-project try 안에서 잡히지 않고 밖으로 새면 같은 run() 안의
    나머지 프로젝트까지 끌고 내려간다(per-project 격리 불변식 위반). 디스크 풀/권한
    같은 상황에서도 Notion 반영은 이미 끝났으니 ack 은 그대로 진행해야 한다(품질
    저하: 원장이 안 앞당겨져 다음 회차에 같은 발췌를 다시 읽는다 — dedup 컨텍스트가
    흡수) — job 을 큐에 남기면 디스크가 고쳐지기 전까지 매 회차 계속 실패할 뿐이다."""
    transcript = _write_transcript(tmp_path, "s1.jsonl", [
        _claude_line("user", "x" * 2100),
        _claude_line("user", "y" * 2100),
    ])
    _enqueue_session("proj", "s1", transcript)
    fake_json = json.dumps({"items": [], "merges": [], "brief": ""})
    db, runtime = _wire(monkeypatch, fake_json, [])

    def boom(led, now=None):
        raise OSError("disk full")

    monkeypatch.setattr(consolidate.transcripts, "save_ledger", boom)

    res = consolidate.run(CFG, print, project="proj")

    assert "error" not in res                # 트레이스백/에러로 안 번짐
    assert runtime.calls                       # LLM 패스는 정상적으로 돌았다
    assert q.list_jobs() == []                 # ledger 쓰기 실패해도 ack 은 그대로 진행


def test_run_isolates_ledger_write_failure_per_project(qroot, tmp_path, monkeypatch):
    """ledger 쓰기 실패가 이 프로젝트만의 일이어야 한다 — 같은 run() 안의 다른
    프로젝트는 영향받지 않는다(flusher.py 와 동일 규율)."""
    t_good = _write_transcript(tmp_path, "good.jsonl", [
        _claude_line("user", "x" * 2100), _claude_line("user", "y" * 2100)])
    t_flaky = _write_transcript(tmp_path, "flaky.jsonl", [
        _claude_line("user", "x" * 2100), _claude_line("user", "y" * 2100)])
    _enqueue_session("good", "sg", t_good, ts="2026-08-01T00:00:00Z")
    _enqueue_session("flaky", "sf", t_flaky, ts="2026-08-01T00:00:01Z")
    fake_json = json.dumps({"items": [], "merges": [], "brief": ""})
    db, runtime = _wire(monkeypatch, fake_json, [])

    real_save_ledger = consolidate.transcripts.save_ledger

    def flaky_save(led, now=None):
        if "sf" in led:
            raise OSError("disk full")
        return real_save_ledger(led, now=now)

    monkeypatch.setattr(consolidate.transcripts, "save_ledger", flaky_save)

    res = consolidate.run(CFG, print)

    assert "error" not in res
    assert q.list_jobs() == []                 # 둘 다 ack(쓰기 실패해도 ack 은 진행)
    led = transcripts.load_ledger()
    assert "sg" in led                          # 정상 프로젝트는 원장 갱신됨
    assert "sf" not in led                      # 실패한 프로젝트만 원장 미갱신


def test_run_skips_ledger_update_for_truncated_excerpt_but_advances_others(
        qroot, tmp_path, monkeypatch):
    """finding 2(controller) — TOTAL_CAP 에 걸려 잘린 세션은 `consumed_bytes` 가
    (파싱은 끝까지 됐으니) 여전히 파일 전체 오프셋이다. 그걸 원장에 그대로 쓰면 LLM
    이 못 본 뒷부분이 "이미 발굴됨"으로 표시돼 영원히 유실된다 — 잘린 세션은 원장을
    건너뛰고, 안 잘린 세션은 정상 갱신돼야 한다."""
    monkeypatch.setattr(consolidate.transcripts, "TOTAL_CAP", 2500)
    t1 = _write_transcript(tmp_path, "s1.jsonl", [_claude_line("user", "x" * 2100)])
    t2 = _write_transcript(tmp_path, "s2.jsonl", [_claude_line("user", "y" * 2100)])
    _enqueue_session("proj", "s1", t1, ts="2026-08-01T01:00:00Z")   # 최신 → 먼저 처리, 안 잘림
    _enqueue_session("proj", "s2", t2, ts="2026-08-01T00:00:00Z")   # 오래됨 → 나중 처리, 잘림
    fake_json = json.dumps({"items": [], "merges": [], "brief": ""})
    db, runtime = _wire(monkeypatch, fake_json, [])

    res = consolidate.run(CFG, print, project="proj")

    assert "error" not in res
    assert q.list_jobs() == []
    led = transcripts.load_ledger()
    assert "s1" in led                          # 안 잘린 세션은 원장 갱신
    assert "s2" not in led                       # 잘린 세션은 원장 미갱신 — 재발굴 대기


def test_run_does_not_update_ledger_when_gated_below_min_chars(qroot, tmp_path, monkeypatch):
    """게이트에 걸려 LLM 패스를 안 돌면 원장도 안 건드려야 다음 회차에 같은 발췌가
    다시 잡힌다(누적을 위해 소비량을 미리 기록하면 안 된다)."""
    transcript = _write_transcript(tmp_path, "s1.jsonl", [_claude_line("user", "x" * 100)])
    _enqueue_session("proj", "s1", transcript)
    _wire(monkeypatch, "{}", [])

    consolidate.run(CFG, print, project="proj")

    assert transcripts.load_ledger() == {}


# ── I3: dedup 컨텍스트는 Notion 전체 스캔이 아니라 로컬 mem_index 에서만 뽑는다
# (network 0) ────────────────────────────────────────────────────────────

def _fake_index(docs):
    return {"version": 2, "meta": {"n": len(docs), "avgdl": 0.0, "df": {}}, "docs": docs}


def test_dedup_context_built_from_local_index(monkeypatch):
    idx = _fake_index({
        "m1": {"title": "이미 아는 결정", "concepts": ["x"], "type": "fact",
              "project": "proj", "status": "Active"},
        "m2": {"title": "다른 프로젝트", "concepts": ["y"], "type": "fact",
              "project": "other", "status": "Active"},
        "m3": {"title": "아직 초안", "concepts": ["z"], "type": "fact",
              "project": "proj", "status": "Draft"},
    })
    monkeypatch.setattr(consolidate.mem_index, "load", lambda: idx)

    out = consolidate._dedup_context("proj")

    assert out == [{"title": "이미 아는 결정", "concepts": ["x"]}]


def test_dedup_context_excludes_brief_rows(monkeypatch):
    idx = _fake_index({
        "brief-proj": {"title": "Project brief: proj", "concepts": [], "type": "brief",
                      "project": "proj", "status": "Active"},
        "m1": {"title": "진짜 메모리", "concepts": ["a"], "type": "fact",
              "project": "proj", "status": "Active"},
    })
    monkeypatch.setattr(consolidate.mem_index, "load", lambda: idx)

    out = consolidate._dedup_context("proj")

    assert out == [{"title": "진짜 메모리", "concepts": ["a"]}]


def test_dedup_context_empty_when_index_missing(monkeypatch):
    monkeypatch.setattr(consolidate.mem_index, "load", lambda: {})
    assert consolidate._dedup_context("proj") == []


def test_run_wires_dedup_context_into_prompt(qroot, tmp_path, monkeypatch):
    transcript = _write_transcript(tmp_path, "s1.jsonl", [
        _claude_line("user", "x" * 2100),
        _claude_line("user", "y" * 2100),
    ])
    _enqueue_session("proj", "s1", transcript)
    fake_json = json.dumps({"items": [], "merges": [], "brief": ""})
    db, runtime = _wire(monkeypatch, fake_json, [])
    idx = _fake_index({"m1": {"title": "이미 아는 결정", "concepts": ["x"], "type": "fact",
                              "project": "proj", "status": "Active"}})
    monkeypatch.setattr(consolidate.mem_index, "load", lambda: idx)

    consolidate.run(CFG, print, project="proj")

    assert "이미 아는 결정" in runtime.calls[0][1]


def test_run_continues_when_index_missing(qroot, tmp_path, monkeypatch):
    """색인이 없거나 손상됐어도(mem_index.load()가 이미 {} 로 방어) 발굴 패스는
    dedup 컨텍스트 없이 계속 돈다 — 옛 Notion query_active_summaries 실패-흡수
    테스트의 후신(I3 이후로는 네트워크 자체가 없어 실패할 일도 없다)."""
    transcript = _write_transcript(tmp_path, "s1.jsonl", [
        _claude_line("user", "x" * 2100),
        _claude_line("user", "y" * 2100),
    ])
    _enqueue_session("proj", "s1", transcript)
    fake_json = json.dumps({"items": [], "merges": [], "brief": ""})
    db, runtime = _wire(monkeypatch, fake_json, [])
    monkeypatch.setattr(consolidate.mem_index, "load", lambda: {})

    res = consolidate.run(CFG, print, project="proj")

    assert "error" not in res
    assert runtime.calls
    assert q.list_jobs() == []


# ── M1: ack 는 LLM 패스 도중 끼어든 새 세션을 지우지 않는다(compare-and-delete) ──

def test_ack_preserves_session_enqueued_during_llm_call(qroot, tmp_path, monkeypatch):
    """Stop 이 LLM 패스 도중(스냅샷~ack 사이, 최대 600초) 같은 프로젝트에 새 세션을
    enqueue 하면, 옛 `ack()`(무조건 unlink)는 그 새 세션까지 함께 날려버렸다.
    compare-and-delete(`ack_sessions`)는 ts 변경을 감지해 새로 들어온 세션만 남기고
    다시 쓴다."""
    t1 = _write_transcript(tmp_path, "s1.jsonl", [
        _claude_line("user", "x" * 2100), _claude_line("user", "y" * 2100)])
    _enqueue_session("proj", "s1", t1, ts="2026-08-01T00:00:00Z")
    fake_json = json.dumps({"items": [], "merges": [], "brief": ""})
    db = FakeDB([])

    class RacyRuntime:
        def __init__(self):
            self.calls = []

        def generate(self, system, user):
            self.calls.append((system, user))
            # LLM 호출 도중 같은 프로젝트에 새 Stop 이 도착했다고 시뮬레이션 —
            # 스냅샷(run() 시작 시점의 queue.list_jobs())과 이 시점 사이의 race.
            _enqueue_session("proj", "s2", tmp_path / "s2.jsonl",
                             ts="2026-08-01T00:05:00Z")
            return fake_json

    runtime = RacyRuntime()
    monkeypatch.setattr(consolidate, "build_runtime", lambda cfg: runtime)
    monkeypatch.setattr(consolidate, "MemoryStore", FakeStoreFactory(db))
    monkeypatch.setattr(consolidate, "NotionSession", lambda: object())

    res = consolidate.run(CFG, print, project="proj")

    assert "error" not in res
    remaining = q.list_jobs()
    assert len(remaining) == 1                      # 잡 자체는 남아있다(완전 ack 아님)
    sids = {s["session_id"] for s in remaining[0]["sessions"]}
    assert sids == {"s2"}         # s1 은 처리 완료로 제거, s2 는 레이스로 살아남음


def test_run_sets_recursion_guard_env(qroot, tmp_path, monkeypatch):
    monkeypatch.delenv("NOTIONMEMORY_CONSOLIDATE", raising=False)
    _wire(monkeypatch, "{}", [])

    consolidate.run(CFG, print, project="proj")

    assert consolidate.os.environ.get("NOTIONMEMORY_CONSOLIDATE") == "1"


# ── C1: 무인 백그라운드(--auto) 경로는 Second Brain DB 를 절대 만들지 않는다 ──

def test_run_auto_true_with_unbound_store_does_not_create_or_ack(qroot, monkeypatch):
    """memory 가 아직 바인딩 안 된 상태(ds="")에서 `auto=True` 로 부르면 —
    `_data_source(create=False)` 가 ""를 돌려주고, 그 자리에서 바로 빈 totals 로
    돌아온다. Draft 조회(query_drafts)도, LLM 호출도, 큐 ack 도 전혀 일어나면 안
    된다(큐 보존 — 다음 회차/수동 실행이 여전히 이 잡을 볼 수 있어야 한다)."""
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    db = FakeDB([_draft("m1")])
    runtime = FakeRuntime("{}")
    monkeypatch.setattr(consolidate, "build_runtime", lambda cfg: runtime)
    monkeypatch.setattr(consolidate, "MemoryStore", FakeStoreFactory(db, ds=""))
    monkeypatch.setattr(consolidate, "NotionSession", lambda: object())

    res = consolidate.run(CFG, print, project="proj", auto=True)

    assert res == dict(consolidate._EMPTY_TOTALS)
    assert runtime.calls == []                    # LLM 패스 자체가 안 돎(Draft 조회 전 bail)
    assert db.props == {}                          # Notion 에 아무것도 안 씀
    assert len(q.list_jobs()) == 1                  # 잡 보존(ack 안 됨)


def test_run_auto_true_with_bound_store_behaves_normally(qroot, monkeypatch):
    """이미 바인딩된 memory(ds 존재)면 `auto=True` 도 평소처럼 LLM 패스를 돌고
    ack 한다 — C1 가드는 "미바인딩일 때만" 막는다."""
    q.enqueue("proj", "/cwd", "2026-07-29T00:00:00Z")
    fake_json = json.dumps({"items": [{"mem_id": "m1", "action": "keep", "strength": 8}],
                            "merges": [], "brief": ""})
    db, runtime = _wire(monkeypatch, fake_json, [_draft("m1")])

    res = consolidate.run(CFG, print, project="proj", auto=True)

    assert "error" not in res
    assert res["promoted"] == 1
    assert q.list_jobs() == []


def test_cli_consolidate_output_includes_mined_count(qroot, tmp_path, monkeypatch, capsys):
    from notionmemory import cli

    transcript = _write_transcript(tmp_path, "s1.jsonl", [
        _claude_line("user", "x" * 2100),
        _claude_line("user", "y" * 2100),
    ])
    _enqueue_session("proj", "s1", transcript)
    fake_json = json.dumps({
        "items": [{"action": "new", "type": "fact", "content": "발굴된 사실", "strength": 5}],
        "merges": [], "brief": ""})
    _wire(monkeypatch, fake_json, [])

    class Args:
        config = str(tmp_path / "config.yaml")   # 존재하지 않음 → 빈 Config
        action = "consolidate"
        project = "proj"
        auto = False

    rc = cli._cmd_memory(Args())

    assert rc == 0
    out = capsys.readouterr().out
    assert "발굴 1건" in out


def test_cli_consolidate_auto_logs_exception_and_releases_lock(tmp_path, monkeypatch):
    """fix round 1 finding 1: run() 내부 per-project try/except 를 벗어난 예외
    (여기선 monkeypatch 로 직접 시뮬레이션)가 `--auto` 경로에서 stderr=DEVNULL 로
    조용히 삼켜지지 않고 file_log 에 남아야 하며, rc 는 여전히 0(백그라운드는 절대
    비정상 종료코드를 내지 않는다) 이고 락은 finally 로 반드시 풀려야 한다."""
    from notionmemory import cli
    from notionmemory.skills.memory import autorun

    monkeypatch.setattr(autorun.paths, "state_dir", lambda: tmp_path)

    def _boom(config, log, project="", auto=False):
        raise OSError("ledger 로드 실패")

    monkeypatch.setattr(cli.mem_consolidate, "run", _boom)

    class Args:
        config = str(tmp_path / "config.yaml")   # 존재하지 않음 → 빈 Config
        action = "consolidate"
        project = ""
        auto = True

    rc = cli._cmd_memory(Args())

    assert rc == 0
    assert not autorun.lock_path().exists()                        # 락 해제됨
    log_text = autorun.log_path().read_text(encoding="utf-8")
    assert "consolidate --auto 실패" in log_text
    assert "ledger 로드 실패" in log_text
