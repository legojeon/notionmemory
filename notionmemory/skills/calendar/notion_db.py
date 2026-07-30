"""Notion 'Calendar' 데이터베이스 — 부트스트랩 + 일정 페이지 CRUD.

skills/memory/notion_db.py(SecondBrainDB)와 동형: ensure() 캐시 검증→404 재부트스트랩,
워크스페이스 최상위 폴백. 일정 하나 = DB 행 하나 = Notion 페이지(속성 + 본문 메모).
"""
from __future__ import annotations

from notionmemory.core.notion_markdown import markdown_to_blocks

DB_TITLE = "Calendar"
STATUSES = ("Scheduled", "Done", "Canceled")
SOURCES = ("manual", "claude", "codex")

PROPERTIES = {
    "Title": {"title": {}},
    "Event ID": {"rich_text": {}},
    "Date": {"date": {}},
    "Status": {"select": {"options": [{"name": s} for s in STATUSES]}},
    "Location": {"rich_text": {}},
    "Link": {"url": {}},
    "Source": {"select": {"options": [{"name": s} for s in SOURCES]}},
}

# Notion Calendar 앱 설정은 공개 API가 없어 자동 적용이 불가능하다(앱 로컬 설정) —
# 안내가 유일한 수단이므로 문구를 여기 한 곳에 두고 부트스트랩·setup 양쪽이 공유한다.
SETUP_STEPS = (
    "In the app: Settings → Add Notion workspace to connect your workspace",
    f"In the sidebar: workspace ••• → Add Notion database → add '{DB_TITLE}'",
    f"Hover over '{DB_TITLE}' → ••• → Make default calendar "
    "(important: if you don't, events created in the app are saved to your Google "
    "account and the agent can't read them)",
    f"To change the color, hover over '{DB_TITLE}' → ••• → pick a color (color is per DB)",
)

CONNECT_HINT = ("  · To also see it in the Notion Calendar app:\n"
                + "\n".join(f"    {i}. {s}" for i, s in enumerate(SETUP_STEPS, 1)))


class SchemaConflictError(ValueError):
    """기존 속성이 다른 타입이라 안전하게 채택할 수 없음."""


def db_url(database_id: str) -> str:
    """database_id → Notion DB 바로가기 URL (하이픈 제거 형식)."""
    return f"https://www.notion.so/{database_id.replace('-', '')}" if database_id else ""


def rt(text: str) -> list[dict]:
    """rich_text 프로퍼티 값 — Notion 항목당 2000자 한계 방어."""
    return [{"text": {"content": (text or "")[:2000]}}]


class CalendarDB:
    def __init__(self, session, log=None):
        self.session = session
        self.log = log or (lambda *_: None)

    def _req(self, method: str, path: str, **kwargs):
        resp = self.session.request(method, path, **kwargs)
        if resp.status_code >= 300:
            raise RuntimeError(f"Notion {method} {path} 실패: {resp.status_code} {resp.text[:200]}")
        return resp

    def ensure(self, parent_page_id: str, meta, *, create: bool = True) -> str:
        """data source id. `create=False`면 살아있는 캐시가 있을 때만 주고 없으면 "".

        조회 경로가 DB를 만드는 것은 그 자체로 잘못이고, 쓰기 라우팅의 되묻기를 무의미하게
        만든다 — 묻기도 전에 빈 Calendar DB 가 생겨 있으면 사용자가 그것을 떠안는다.
        """
        cached = meta.get_meta("data_source_id")
        if cached:
            r = self.session.request("GET", f"/data_sources/{cached}")
            if r.status_code == 200:
                body = r.json()
                # 휴지통/아카이브된 data source 는 GET 만 200 이고 쓰기는 다 실패한다 —
                # 무효 캐시로 보고 재부트스트랩(create=False면 아래에서 "" 반환).
                if not (body.get("in_trash") or body.get("archived")):
                    # 스키마 진화가 필요해지면 SecondBrainDB.ensure()의 evolutions 패턴 도입
                    return cached
                self.log(f"  ! 저장된 data source({cached})가 휴지통/아카이브 상태 → 재부트스트랩")
            elif r.status_code == 404:
                self.log(f"  ! 저장된 data source({cached}) 접근 불가(404) → 재부트스트랩")
            else:
                raise RuntimeError(
                    f"Notion GET /data_sources/{cached} 실패: {r.status_code} {r.text[:200]}")
        if not create:
            return ""
        parent = ({"type": "page_id", "page_id": parent_page_id} if parent_page_id
                  else {"type": "workspace", "workspace": True})
        resp = self._req("POST", "/databases", json={
            "parent": parent,
            "title": [{"type": "text", "text": {"content": DB_TITLE}}],
            "initial_data_source": {"properties": PROPERTIES},
        })
        body = resp.json()
        ds_id = body["data_sources"][0]["id"]
        meta.set_meta("database_id", body["id"])
        meta.set_meta("data_source_id", ds_id)
        self.log(f"  · Calendar DB 생성: database={body['id']} data_source={ds_id}")
        self.log(CONNECT_HINT)
        return ds_id

    def adopt(self, database_id: str, meta) -> list[str]:
        """기존 Notion DB를 Calendar로 채택 — 비파괴, 누락 속성만 추가·타입 충돌은 거부."""
        db = self._req("GET", f"/databases/{database_id}").json()
        ds_id = db["data_sources"][0]["id"]
        props = self._req("GET", f"/data_sources/{ds_id}").json().get("properties") or {}
        missing, conflicts = {}, []
        for name, spec in PROPERTIES.items():
            want = next(iter(spec))                 # {"date": {}} -> "date"
            cur = (props.get(name) or {}).get("type")
            if cur is None:
                missing[name] = spec
            elif cur != want:
                conflicts.append(f"'{name}' 은 {want} 가 필요한데 {cur} 로 존재")
        if conflicts:
            raise SchemaConflictError(
                "기존 DB 스키마 충돌 — " + "; ".join(conflicts)
                + ". 에이전트로 연결하거나 새 DB 를 만드세요.")
        if missing:
            self._req("PATCH", f"/data_sources/{ds_id}", json={"properties": missing})
        meta.set_meta("database_id", db["id"])
        meta.set_meta("data_source_id", ds_id)
        return sorted(missing)

    def find_page_by_event_id(self, data_source_id: str, event_id: str) -> dict | None:
        resp = self._req("POST", f"/data_sources/{data_source_id}/query", json={
            "filter": {"property": "Event ID", "rich_text": {"equals": event_id}},
            "page_size": 1})
        results = resp.json().get("results", [])
        return results[0] if results else None

    def query(self, data_source_id: str, filter_json: dict) -> list[dict]:
        """서버측 필터로 걸러진 페이지 전량 페치 (속성만 — 본문 블록은 별도)."""
        pages: list[dict] = []
        cursor = None
        while True:
            payload = {"filter": filter_json, "page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            data = self._req("POST", f"/data_sources/{data_source_id}/query", json=payload).json()
            pages += data.get("results", [])
            if not data.get("has_more"):
                return pages
            cursor = data.get("next_cursor")

    def create_page(self, data_source_id: str, props: dict, notes: str = "") -> dict:
        blocks = markdown_to_blocks(notes) if notes else []
        first, rest = blocks[:100], blocks[100:]
        resp = self._req("POST", "/pages", json={
            "parent": {"data_source_id": data_source_id},
            "properties": props, "children": first})
        page = resp.json()
        for k in range(0, len(rest), 100):
            self._req("PATCH", f"/blocks/{page['id']}/children", json={"children": rest[k:k + 100]})
        return page

    def update_page(self, page_id: str, props: dict) -> None:
        self._req("PATCH", f"/pages/{page_id}", json={"properties": props})

    def trash_page(self, page_id: str, props: dict | None = None) -> None:
        """페이지를 휴지통으로 — 속성 변경과 한 PATCH로 묶을 수 있다.
        2025-09 API는 구 `archived` 대신 `in_trash`만 받는다(실 400으로 확인).
        DB 하위 페이지는 API로 휴지통 이동 가능(워크스페이스 최상위 객체만 UI 전용)."""
        body: dict = {"in_trash": True}
        if props:
            body["properties"] = props
        self._req("PATCH", f"/pages/{page_id}", json=body)
