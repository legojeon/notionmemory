from __future__ import annotations
import os
from flask import Flask, jsonify, request
from notionmemory.core.registry import Registry
from notionmemory.core import notion_auth
from notionmemory.core.config import save_skill_options
from notionmemory.core.notion_client import NotionSession
from notionmemory.skills.templates import introspect as templates_introspect
from notionmemory.skills.templates import profile as templates_profile
from notionmemory.web.jobs import JobRegistry

ASSETS = os.path.join(os.path.dirname(__file__), "assets")


def create_app(registry: Registry) -> Flask:
    app = Flask(__name__, static_folder=ASSETS, static_url_path="/assets")
    jobs = JobRegistry()

    @app.get("/api/integrations")
    def integrations():
        cfg = registry.config
        out = []
        for integ in registry.integrations().values():
            st = integ.status(cfg)
            out.append({"id": integ.id, "name": integ.name,
                        "connected": st.connected, "detail": st.detail})
        return jsonify(out)

    @app.get("/api/skills")
    def skills():
        return jsonify([c.__dict__ for c in registry.cards()])

    @app.get("/api/language")
    def get_language():
        from notionmemory.core import i18n
        return jsonify({"language": i18n.language(registry.config)})

    @app.post("/api/language")
    def set_language():
        from notionmemory.core import config as cfg
        lang = (request.get_json(silent=True) or {}).get("language")
        if lang not in ("en", "ko"):
            return jsonify({"error": "language must be en or ko"}), 400
        if registry.config.path:
            cfg.save_language(registry.config.path, lang)
        registry.config.data["language"] = lang    # 재로드 없이 GET 에 반영
        return jsonify({"language": lang})

    @app.get("/api/skills/<sid>/options")
    def options(sid):
        s = registry.get(sid)
        if not s:
            return jsonify({"error": "not found"}), 404
        return jsonify(s.options_schema())

    @app.get("/api/skills/<sid>/config")
    def skill_config_get(sid):
        s = registry.get(sid)
        if not s:
            return jsonify({"error": "not found"}), 404
        return jsonify(registry.config.skill_options(sid))

    @app.post("/api/skills/<sid>/config")
    def skill_config_save(sid):
        s = registry.get(sid)
        if not s:
            return jsonify({"error": "not found"}), 404
        incoming = request.get_json(silent=True) or {}
        schema = s.options_schema()
        # 불변식: 이 schema-whitelist(스키마에 있고 runtime 아님)가 토큰/시크릿이
        # config.yaml 로 새는 것을 막는 유일한 방벽이다. clean_options 는 unknown 키를
        # 통과시키므로 이 필터를 제거하거나 완화하면 안 된다. (tests/web/test_api.py 의
        # token-barrier 회귀 테스트가 이를 고정한다)
        try:
            cleaned = {k: v for k, v in s.clean_options(incoming).items()
                       if k in schema and not schema[k].get("runtime")}
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if registry.config.path:
            merged = save_skill_options(registry.config.path, sid, cleaned)
            registry.config.data.setdefault("skills", {})[sid] = dict(merged)
        else:
            registry.config.data.setdefault("skills", {}).setdefault(sid, {}).update(cleaned)
        return jsonify(registry.config.skill_options(sid))

    @app.post("/api/skills/<sid>/run")
    def run(sid):
        s = registry.get(sid)
        if not s:
            return jsonify({"error": "not found"}), 404
        card = next(c for c in registry.cards() if c.id == sid)
        if card.status != "available":
            return jsonify({"error": "blocked", "missing": card.missing}), 409
        options = request.get_json(silent=True) or {}
        job = jobs.start(lambda log: s.run(options, log))
        return jsonify({"job_id": job.id}), 202

    @app.get("/api/skills/<sid>/status/<job_id>")
    def status(sid, job_id):
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
        return jsonify({"logs": job.logs, "done": job.done, "ok": job.ok, "message": job.message})

    def _integration_state(iid):
        integ = registry.integrations()[iid]
        st = integ.status(registry.config)
        return {"id": iid, "connected": st.connected, "detail": st.detail}

    @app.post("/api/integrations/<iid>/test")
    def integration_test(iid):
        integ = registry.integrations().get(iid)
        if not integ:
            return jsonify({"error": "not found"}), 404
        st = integ.test(registry.config)
        return jsonify({"id": iid, "connected": st.connected, "detail": st.detail})

    @app.post("/api/integrations/notion/connect")
    def notion_connect():
        token = str((request.get_json(silent=True) or {}).get("token", "")).strip()
        if not token:
            return jsonify({"error": "token 필요"}), 400
        result = notion_auth.verify_token(token)
        if not result["ok"]:
            return jsonify({"error": result["error"]}), 401
        notion_auth.save_pat(token)
        name = result.get("name", "")
        if registry.config.path:
            notion_auth.save_connection_meta(registry.config.path, name)
        notion_meta = registry.config.data.setdefault("integrations", {}).setdefault("notion", {})
        notion_meta["auth_mode"] = "pat"
        notion_meta["workspace_name"] = name
        notion_meta["token"] = ""
        return jsonify(_integration_state("notion"))

    @app.post("/api/integrations/notion/disconnect")
    def notion_disconnect():
        notion_auth.delete_pat()
        if registry.config.path:
            notion_auth.clear_connection_meta(registry.config.path)
        notion_meta = (registry.config.data.get("integrations") or {}).get("notion")
        if notion_meta:
            notion_meta.pop("auth_mode", None)
            notion_meta.pop("workspace_name", None)
            if "token" in notion_meta:
                notion_meta["token"] = ""
        return jsonify(_integration_state("notion"))

    def _template_dict(p):
        # page_id 는 app.js 가 "프롬프트 전용 vs 인스턴스"를 판정하는 키다 — 빠뜨리면
        # 모든 템플릿이 프롬프트 전용으로 오인돼 모달이 구조를 숨기고 동기화 버튼이
        # 사라진다(최종 리뷰 CRITICAL). JS↔API 계약이라 DOM 테스트 없이는 안 잡힌다.
        return {"slug": p.slug, "name": p.name, "prompt": p.prompt,
                "page_id": p.page_id,
                "databases": [{"key": d.get("key"), "title": d.get("title")}
                              for d in (p.databases or [])],
                "pages_count": len(p.pages or [])}

    @app.get("/api/templates")
    def templates_list():
        return jsonify([_template_dict(p) for p in templates_profile.load_all()])

    @app.post("/api/templates")
    def templates_create():
        incoming = request.get_json(silent=True) or {}
        name = str(incoming.get("name", "")).strip()
        if not name:
            return jsonify({"error": "이름이 필요합니다"}), 400
        from notionmemory.skills.templates.introspect import slugify
        slug = slugify(name)
        base, n = slug, 2
        while templates_profile.exists(slug):     # 중복이면 -2, -3 …
            slug = f"{base}-{n}"; n += 1
        # 화이트리스트: name/prompt 만 — page_id·구조는 항상 빈 값(청사진)
        p = templates_profile.Profile(slug=slug, name=name,
                                      page_id="", prompt=str(incoming.get("prompt", "")))
        templates_profile.save(p)
        return jsonify(_template_dict(p))

    @app.post("/api/templates/<slug>/prompt")
    def templates_prompt_save(slug):
        if not templates_profile.exists(slug):
            return jsonify({"error": "not found"}), 404
        incoming = request.get_json(silent=True) or {}
        # 화이트리스트: prompt 필드만 받는다 — 임의 키가 프로필로 새지 않게(토큰 장벽 규율)
        p = templates_profile.load(slug)
        p.prompt = str(incoming.get("prompt", ""))
        templates_profile.save(p)
        return jsonify({"slug": p.slug, "name": p.name, "prompt": p.prompt})

    @app.delete("/api/templates/<slug>")
    def templates_delete(slug):
        # 등록 해제 — 로컬 프로필만 지운다. Notion DB·페이지는 절대 건드리지 않는다
        # (profile.delete 는 프로필 JSON unlink 뿐). CLI `templates remove` 와 동일 의미.
        if not templates_profile.exists(slug):
            return jsonify({"error": "not found"}), 404
        templates_profile.delete(slug)
        return jsonify({"slug": slug, "deleted": True})

    @app.post("/api/templates/<slug>/refresh")
    def templates_refresh(slug):
        # 캐시된 구조를 Notion 에서 재조회(스키마만 — 사용 노트 재생성은 CLI 의 --refresh-notes).
        # runtime=None 이라 agent 를 안 부른다: 빠르고 안전(Notion 읽기). prompt 는 보존.
        if not templates_profile.exists(slug):
            return jsonify({"error": "not found"}), 404
        if not templates_profile.load(slug).page_id:
            return jsonify({"error": "프롬프트 전용 템플릿은 갱신할 연결 구조가 없습니다"}), 400
        try:
            p = templates_introspect.refresh(NotionSession(), slug, log=lambda *_: None)
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001 — 실제 Notion HTTP 라 예상 밖 예외 가능
            return jsonify({"error": f"구조 갱신 실패: {exc}"}), 500
        return jsonify(_template_dict(p))

    @app.post("/api/templates/register")
    def templates_register():
        # 기존 Notion 페이지/DB 를 인스턴스 템플릿으로 등록 — CLI 의 `templates register`
        # 와 같은 introspect.register 를 쓴다(등록 본체 동일). 단 runtime=None: Flask 는
        # agent 가 아니라 사용 노트를 생성하지 않는다(CLI 도 런타임 미감지 시 같은 폴백).
        # 화이트리스트: url 만 — 임의 키가 register 로 새지 않게(토큰 장벽 규율).
        url = str((request.get_json(silent=True) or {}).get("url", "")).strip()
        if not url:
            return jsonify({"error": "Notion URL 이 필요합니다"}), 400
        try:
            p = templates_introspect.register(NotionSession(), url,
                                              runtime=None, log=lambda *_: None)
        except templates_introspect.AmbiguousTarget as exc:
            # AmbiguousTarget 은 ValueError 서브클래스 — 반드시 ValueError 보다 먼저 잡아
            # 후보를 살린다. 후보를 텍스트로 이어붙여 인라인 메시지로 돌려준다.
            lines = [str(exc)] + [f"  · {c.get('title')} — {c.get('url') or c.get('id')}"
                                  for c in exc.candidates]
            return jsonify({"error": "\n".join(lines)}), 400
        except (RuntimeError, ValueError) as exc:   # 미공유·잘못된 URL 등
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001 — 실제 Notion HTTP 라 예상 밖 예외 가능
            return jsonify({"error": f"등록 실패: {exc}"}), 500
        return jsonify(_template_dict(p))

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    return app
