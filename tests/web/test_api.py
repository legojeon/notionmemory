import yaml

from notionmemory.core.config import Config
from notionmemory.core.integrations import Integration, build_integrations
from notionmemory.core.registry import Registry
from notionmemory.core.skill_base import Skill, RunResult, VALID_KINDS
from notionmemory.web.server import create_app
from notionmemory.core import notion_auth


class Demo(Skill):
    id, name, kinds, requires = "demo", "Demo", ("capture",), ["notion"]
    def options_schema(self): return {
        "dry_run": {"type": "bool", "default": True},
        "input_dir": {"type": "str", "runtime": True},
    }
    def clean_options(self, options):
        out = {}
        for k, v in (options or {}).items():
            if v == "":
                continue
            if k == "dry_run" and isinstance(v, str):
                v = v.strip().lower() in {"1", "true", "on", "yes"}
            out[k] = v
        return out
    def run(self, options, log):
        log("hi"); return RunResult(True, "ok")


class NeedsBoom(Skill):
    id, name, kinds, requires = "demo", "Demo", ("capture",), ["boom"]
    def options_schema(self): return {}
    def run(self, options, log): return RunResult(True)


class RaisingIntegration(Integration):
    id, name = "boom", "Boom"
    def status(self, config):
        raise RuntimeError("integration blew up")


def _client(cfg_dict):
    cfg = Config(cfg_dict)
    reg = Registry([Demo()], build_integrations(cfg), cfg)
    return create_app(reg).test_client()


def test_integrations_endpoint_lists_three():
    resp = _client({}).get("/api/integrations")
    ids = {i["id"] for i in resp.get_json()}
    assert ids == {"notion", "agent", "git"}


def test_skills_endpoint_reports_blocked_without_notion():
    card = _client({}).get("/api/skills").get_json()[0]
    assert card["status"] == "blocked" and card["missing"] == ["notion"]


def test_options_endpoint_returns_schema():
    schema = _client({}).get("/api/skills/demo/options").get_json()
    assert schema["dry_run"]["default"] is True


def test_run_returns_job_and_status_streams_logs():
    c = _client({"integrations": {"notion": {"token": "x"}}})
    resp = c.post("/api/skills/demo/run", json={})
    assert resp.status_code == 202
    job_id = resp.get_json()["job_id"]
    import time
    for _ in range(50):
        st = c.get(f"/api/skills/demo/status/{job_id}").get_json()
        if st["done"]:
            break
        time.sleep(0.02)
    assert st["done"] is True and st["ok"] is True and st["logs"] == ["hi"]


def test_status_unknown_job_404():
    c = _client({"integrations": {"notion": {"token": "x"}}})
    assert c.get("/api/skills/demo/status/nope").status_code == 404


def test_run_blocked_skill_returns_409():
    c = _client({})  # notion 미연결 → demo blocked
    assert c.post("/api/skills/demo/run", json={}).status_code == 409


def test_run_error_status_skill_returns_409():
    cfg = Config({})
    reg = Registry([NeedsBoom()], {"boom": RaisingIntegration()}, cfg)
    c = create_app(reg).test_client()
    assert c.post("/api/skills/demo/run", json={}).status_code == 409


def _client_with_file(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("integrations: {}\n")
    cfg = Config.load(str(cfg_file))
    reg = Registry([Demo()], build_integrations(cfg), cfg)
    return create_app(reg).test_client(), cfg_file


def test_integration_test_unknown_returns_404(tmp_path):
    client, _ = _client_with_file(tmp_path)
    assert client.post("/api/integrations/nope/test").status_code == 404


def test_notion_connect_saves_pat_and_meta(tmp_path, monkeypatch):
    client, cfg_file = _client_with_file(tmp_path)
    monkeypatch.setattr(notion_auth, "verify_token", lambda t: {"ok": True, "name": "WS"})
    resp = client.post("/api/integrations/notion/connect", json={"token": "ntn_z"})
    assert resp.status_code == 200
    assert resp.get_json()["connected"] is True
    assert notion_auth.load_pat() == "ntn_z"
    raw = yaml.safe_load(cfg_file.read_text())["integrations"]["notion"]
    assert raw["workspace_name"] == "WS"
    assert raw["token"] == ""  # 토큰은 파일에 절대 없음


def test_notion_connect_rejects_invalid_token(tmp_path, monkeypatch):
    client, _ = _client_with_file(tmp_path)
    monkeypatch.setattr(notion_auth, "verify_token",
                        lambda t: {"ok": False, "error": "검증 실패(HTTP 401)"})
    resp = client.post("/api/integrations/notion/connect", json={"token": "bad"})
    assert resp.status_code == 401
    assert notion_auth.load_pat() == ""


def test_notion_connect_requires_token(tmp_path):
    client, _ = _client_with_file(tmp_path)
    assert client.post("/api/integrations/notion/connect", json={}).status_code == 400
    assert client.post("/api/integrations/agent/connect", json={"token": "x"}).status_code == 404


def test_notion_disconnect_clears_pat(tmp_path, monkeypatch):
    client, cfg_file = _client_with_file(tmp_path)
    monkeypatch.setattr(notion_auth, "verify_token", lambda t: {"ok": True, "name": "WS"})
    client.post("/api/integrations/notion/connect", json={"token": "ntn_z"})
    resp = client.post("/api/integrations/notion/disconnect")
    assert resp.status_code == 200
    assert resp.get_json()["connected"] is False
    assert notion_auth.load_pat() == ""
    raw = yaml.safe_load(cfg_file.read_text())["integrations"]["notion"]
    assert "workspace_name" not in raw


def test_skill_config_get_returns_saved_options(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("skills:\n  demo:\n    dry_run: false\n", encoding="utf-8")
    cfg = Config.load(str(cfg_file))
    reg = Registry([Demo()], build_integrations(cfg), cfg)
    client = create_app(reg).test_client()
    assert client.get("/api/skills/demo/config").get_json() == {"dry_run": False}


def test_skill_config_post_persists_whitelisted_and_coerced(tmp_path):
    client, cfg_file = _client_with_file(tmp_path)
    resp = client.post("/api/skills/demo/config",
                       json={"dry_run": "true", "token": "secret", "junk": "x"})
    assert resp.status_code == 200
    assert resp.get_json() == {"dry_run": True}
    saved = yaml.safe_load(cfg_file.read_text())["skills"]["demo"]
    assert saved == {"dry_run": True}          # 스키마 밖 junk 제거
    assert "token" not in saved                # 토큰 파일 기록 금지


def test_skill_config_unknown_skill_404(tmp_path):
    client, _ = _client_with_file(tmp_path)
    assert client.get("/api/skills/nope/config").status_code == 404
    assert client.post("/api/skills/nope/config", json={}).status_code == 404


def test_skill_config_post_excludes_runtime_fields(tmp_path):
    client, cfg_file = _client_with_file(tmp_path)
    resp = client.post("/api/skills/demo/config",
                       json={"dry_run": "true", "input_dir": "/some/path"})
    assert resp.status_code == 200
    saved = yaml.safe_load(cfg_file.read_text())["skills"]["demo"]
    assert saved == {"dry_run": True}      # runtime field 'input_dir' excluded from persistence
    assert "input_dir" not in saved


def test_config_save_rejects_bad_number(tmp_path):
    from notionmemory.app import build_app
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("integrations: {}\n")
    client = build_app(str(cfg_file)).test_client()  # 기본 등록 skills=None → memory
    r = client.post("/api/skills/memory/config", json={"top_n": "true"})
    assert r.status_code == 400


def test_skill_config_post_disk_merge_wins_over_stray_in_memory_key(tmp_path):
    """save_skill_options 의 병합 결과가 in-memory skills[sid] 를 완전히 대체해야 한다 —
    디스크에 없는 미저장 stray 키가 in-memory 에만 남아 발산하면 안 된다
    (ConfigMeta.set_meta 와 동일한 디스크=단일 소스 계약)."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("skills:\n  demo:\n    dry_run: false\n", encoding="utf-8")
    cfg = Config.load(str(cfg_file))
    reg = Registry([Demo()], build_integrations(cfg), cfg)
    # 다른 호출자가 config.data 를 직접 건드려 저장 없이 stray 키를 남겨둔 상황을 재현
    reg.config.data.setdefault("skills", {})["demo"]["stray"] = "leftover"
    client = create_app(reg).test_client()

    resp = client.post("/api/skills/demo/config", json={"dry_run": "true"})

    assert resp.status_code == 200
    assert resp.get_json() == {"dry_run": True}
    assert "stray" not in resp.get_json()
    get_resp = client.get("/api/skills/demo/config").get_json()
    assert get_resp == {"dry_run": True}
    assert "stray" not in get_resp


def test_config_save_token_barrier_with_base_clean_options(tmp_path):
    """베이스 clean_options 는 unknown 키를 통과시킨다 — whitelist 가 유일한 방벽임을 고정."""
    from notionmemory.app import build_app
    from notionmemory.core.skill_base import RunResult, Skill

    class BareSkill(Skill):
        id, name, kinds, requires = "bare", "Bare", ("capture",), []

        def options_schema(self):
            return {"quality": {"type": "str", "default": "fast"}}

        def run(self, options, log):
            return RunResult(True)

    cfg = tmp_path / "config.yaml"
    app = build_app(str(cfg), skills=[BareSkill()])
    c = app.test_client()
    r = c.post("/api/skills/bare/config", json={"token": "sekret", "quality": "slow"})
    assert r.status_code == 200
    saved = cfg.read_text(encoding="utf-8")
    assert "sekret" not in saved and "slow" in saved


def test_skills_endpoint_exposes_usage_and_setup_steps():
    """대시보드가 verb 스킬에 틀린 `run` 안내를 내지 않도록 카드가 사용법을 실어 보낸다."""
    from notionmemory.app import build_registry
    from notionmemory.web.server import create_app
    import json
    reg = build_registry("config.yaml")
    resp = create_app(reg).test_client().get("/api/skills")
    cards = {c["id"]: c for c in json.loads(resp.data)}
    assert cards["calendar"]["usage"] == "notionmemory calendar list/add/update/cancel"
    assert any("default calendar" in s.lower() for s in cards["calendar"]["setup_steps"])
    assert cards["memory"]["usage"].startswith("notionmemory remember")


def test_cards_expose_function_kinds():
    from notionmemory.app import build_registry
    from notionmemory.web.server import create_app
    import json
    resp = create_app(build_registry("config.yaml")).test_client().get("/api/skills")
    cards = {c["id"]: c for c in json.loads(resp.data)}
    assert cards["memory"]["kinds"] == ["capture", "recall"]
    assert cards["calendar"]["kinds"] == ["recall", "action"]
    assert all("kind" not in c for c in cards.values())   # 단수 필드 잔존 금지


def test_all_registered_skill_cards_have_valid_kinds():
    """등록된 모든 스킬 카드의 kinds가 VALID_KINDS 안이고 비어 있지 않은지 강제 —
    신규 스킬이 오타·엉뚱한 kind를 넣으면 이 테스트가 잡아낸다."""
    from notionmemory.app import build_registry
    registry = build_registry("config.yaml")
    for card in registry.cards():
        assert card.kinds, f"{card.id}: kinds가 비어 있음"
        assert set(card.kinds) <= VALID_KINDS, f"{card.id}: 잘못된 kind {card.kinds}"


def test_templates_list_and_prompt_save(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    from notionmemory.app import build_registry
    from notionmemory.web.server import create_app
    P.save(P.Profile(slug="job", name="Job", page_id="pg", page_url="u",
                     databases=[{"key": "apps", "title": "Applications"}]))
    client = create_app(build_registry(str(tmp_path / "none.yaml"))).test_client()

    got = client.get("/api/templates").get_json()
    assert any(t["slug"] == "job" and t["name"] == "Job" for t in got)

    r = client.post("/api/templates/job/prompt", json={"prompt": "표로 정리"})
    assert r.status_code == 200 and r.get_json()["prompt"] == "표로 정리"
    assert P.load("job").prompt == "표로 정리"


def test_templates_prompt_whitelists_to_prompt_field(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    from notionmemory.app import build_registry
    from notionmemory.web.server import create_app
    P.save(P.Profile(slug="job", name="Job", page_id="pg", page_url="u"))
    client = create_app(build_registry(str(tmp_path / "none.yaml"))).test_client()
    # 임의 키(page_id 등)는 무시 — 프로필이 오염되지 않는다
    client.post("/api/templates/job/prompt", json={"prompt": "x", "page_id": "HACKED"})
    assert P.load("job").page_id == "pg"


def test_templates_prompt_404_for_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.app import build_registry
    from notionmemory.web.server import create_app
    client = create_app(build_registry(str(tmp_path / "none.yaml"))).test_client()
    assert client.post("/api/templates/nope/prompt", json={"prompt": "x"}).status_code == 404


def test_templates_refresh_reintrospects_and_preserves_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    from notionmemory.app import build_registry
    from notionmemory.web import server
    P.save(P.Profile(slug="job", name="Job", page_id="pg", page_url="u",
                     databases=[{"key": "old", "title": "Old"}], prompt="keep me"))

    def fake_refresh(session, slug, *, runtime=None, log=print):
        p = P.load(slug)
        p.databases = [{"key": "new", "title": "New DB"}]   # 재조회로 구조 갱신
        P.save(p)
        return p
    monkeypatch.setattr(server, "NotionSession", lambda *a, **k: object())
    monkeypatch.setattr(server.templates_introspect, "refresh", fake_refresh)
    client = server.create_app(build_registry(str(tmp_path / "none.yaml"))).test_client()

    r = client.post("/api/templates/job/refresh")
    assert r.status_code == 200
    body = r.get_json()
    assert body["databases"] == [{"key": "new", "title": "New DB"}]
    assert body["prompt"] == "keep me"                      # 프롬프트 보존
    assert client.post("/api/templates/nope/refresh").status_code == 404


def test_templates_delete_removes_profile_and_404s_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    from notionmemory.app import build_registry
    from notionmemory.web.server import create_app
    P.save(P.Profile(slug="job", name="Job", page_id="pg", page_url="u"))
    client = create_app(build_registry(str(tmp_path / "none.yaml"))).test_client()

    r = client.delete("/api/templates/job")
    assert r.status_code == 200 and r.get_json()["deleted"] is True
    assert not P.exists("job")                                  # 프로필만 제거(Notion 은 안 건드림)
    assert client.get("/api/templates").get_json() == []
    assert client.delete("/api/templates/nope").status_code == 404   # 없는 슬러그


def test_create_prompt_only_template(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    from notionmemory.app import build_registry
    from notionmemory.web.server import create_app
    client = create_app(build_registry(str(tmp_path / "none.yaml"))).test_client()

    r = client.post("/api/templates", json={"name": "강의노트", "prompt": "개념별 헤딩"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["name"] == "강의노트" and body["prompt"] == "개념별 헤딩"
    p = P.load(body["slug"])
    assert p.page_id == "" and p.databases == []


def test_create_prompt_only_whitelists_and_slugifies(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    from notionmemory.app import build_registry
    from notionmemory.web.server import create_app
    client = create_app(build_registry(str(tmp_path / "none.yaml"))).test_client()
    r = client.post("/api/templates", json={"name": "회의록", "prompt": "요약",
                                            "page_id": "HACK", "databases": [{"k": 1}]})
    p = P.load(r.get_json()["slug"])
    assert p.page_id == "" and p.databases == []      # 임의 키 무시


def test_create_prompt_only_rejects_blank_name(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.app import build_registry
    from notionmemory.web.server import create_app
    client = create_app(build_registry(str(tmp_path / "none.yaml"))).test_client()
    assert client.post("/api/templates", json={"name": "", "prompt": "x"}).status_code == 400


def test_refresh_on_prompt_only_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    from notionmemory.app import build_registry
    from notionmemory.web.server import create_app
    P.save(P.Profile(slug="bp", name="청사진", page_id="", prompt="p"))
    client = create_app(build_registry(str(tmp_path / "none.yaml"))).test_client()
    r = client.post("/api/templates/bp/refresh")
    assert r.status_code == 400
    assert "prompt-only" in r.get_json()["error"]


def _register_client(tmp_path, monkeypatch, fake_register):
    from notionmemory.app import build_registry
    from notionmemory.web import server
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(server, "NotionSession", lambda *a, **k: object())
    monkeypatch.setattr(server.templates_introspect, "register", fake_register)
    return server.create_app(build_registry(str(tmp_path / "none.yaml"))).test_client()


def test_register_endpoint_success_returns_template_dict(tmp_path, monkeypatch):
    from notionmemory.skills.templates import profile as P

    def fake_register(session, target, *, slug="", runtime=None, log=print):
        return P.Profile(slug="rjt", name="Research", page_id="pg_9", page_url="u",
                         databases=[{"key": "d", "title": "Papers"}])
    client = _register_client(tmp_path, monkeypatch, fake_register)
    r = client.post("/api/templates/register", json={"url": "https://notion.so/x"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["slug"] == "rjt" and body["page_id"] == "pg_9"   # 인스턴스 계약
    assert body["databases"] == [{"key": "d", "title": "Papers"}]


def test_register_endpoint_runs_without_agent_runtime(tmp_path, monkeypatch):
    """settings register 는 runtime=None(사용 노트 없이) — Flask 는 agent 아님."""
    from notionmemory.skills.templates import profile as P
    seen = {}

    def fake_register(session, target, *, slug="", runtime="SENTINEL", log=print):
        seen["runtime"] = runtime
        return P.Profile(slug="x", name="X", page_id="p", page_url="u")
    client = _register_client(tmp_path, monkeypatch, fake_register)
    client.post("/api/templates/register", json={"url": "u"})
    assert seen["runtime"] is None


def test_register_endpoint_ambiguous_lists_candidates(tmp_path, monkeypatch):
    from notionmemory.skills.templates import introspect as I

    def fake_register(session, target, *, slug="", runtime=None, log=print):
        raise I.AmbiguousTarget("후보가 여럿입니다", [
            {"id": "a", "title": "Papers", "url": "https://n/a"},
            {"id": "b", "title": "Reading", "url": ""}])
    client = _register_client(tmp_path, monkeypatch, fake_register)
    r = client.post("/api/templates/register", json={"url": "u"})
    assert r.status_code == 400
    err = r.get_json()["error"]
    assert "후보가 여럿입니다" in err and "Papers" in err and "Reading" in err


def test_register_endpoint_failure_is_400(tmp_path, monkeypatch):
    def fake_register(session, target, *, slug="", runtime=None, log=print):
        raise RuntimeError("페이지가 공유되지 않았습니다")
    client = _register_client(tmp_path, monkeypatch, fake_register)
    r = client.post("/api/templates/register", json={"url": "u"})
    assert r.status_code == 400
    assert "공유되지" in r.get_json()["error"]


def test_register_endpoint_blank_url_is_400(tmp_path, monkeypatch):
    def fake_register(session, target, *, slug="", runtime=None, log=print):
        raise AssertionError("빈 URL 이면 register 를 부르면 안 된다")
    client = _register_client(tmp_path, monkeypatch, fake_register)
    assert client.post("/api/templates/register", json={"url": ""}).status_code == 400


def test_templates_list_includes_page_id_for_modal_contract(tmp_path, monkeypatch):
    """app.js 가 t.page_id 로 '프롬프트 전용 vs 인스턴스'를 판정하므로 응답에 반드시 포함.
    빠지면 모든 템플릿 모달이 오인 렌더된다(최종 리뷰 CRITICAL 회귀 가드)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    from notionmemory.app import build_registry
    from notionmemory.web.server import create_app
    P.save(P.Profile(slug="inst", name="인스턴스", page_id="pg_1", page_url="u"))
    P.save(P.Profile(slug="bp", name="청사진", page_id="", prompt="p"))
    client = create_app(build_registry(str(tmp_path / "none.yaml"))).test_client()
    got = {t["slug"]: t for t in client.get("/api/templates").get_json()}
    assert got["inst"]["page_id"] == "pg_1"      # 인스턴스는 page_id 전달
    assert got["bp"]["page_id"] == ""            # 청사진은 빈 값
