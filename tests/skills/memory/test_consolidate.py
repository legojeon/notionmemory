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
        return store


class _FakeStore:
    def _data_source(self):
        return self._ds


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
    assert res == {"promoted": 0, "dropped": 0, "merged": 0, "brief_updated": False}


def test_consolidate_project_filter_ignores_other_projects_jobs(qroot, monkeypatch):
    q.enqueue("other", "/cwd", "2026-07-29T00:00:00Z")
    db, runtime = _wire(monkeypatch, "{}", [_draft("m1", project="proj")])

    res = consolidate.run(CFG, print, project="proj")

    assert res == {"promoted": 0, "dropped": 0, "merged": 0, "brief_updated": False}
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

    assert res == {"promoted": 0, "dropped": 0, "merged": 0, "brief_updated": False}
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
