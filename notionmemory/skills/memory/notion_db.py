"""Notion 'Second Brain' 데이터베이스 — 부트스트랩 + 페이지 CRUD (memory direct mode).

skills/memory_capture/notion_db.py 이식·적응: Excerpt 속성(+기존 DB 스키마 진화),
Source 명시 인자화, ALL_TYPES 이 파일 소유, recall 용 query/본문 읽기 추가.
meta 는 get_meta/set_meta 프로토콜(현재 구현: config `skills.memory` 어댑터).
"""
from __future__ import annotations

import re

from notionmemory.core.notion_markdown import markdown_to_blocks

DB_TITLE = "Second Brain"
ALL_TYPES = ("pattern", "preference", "architecture", "bug", "workflow", "fact")
STATUSES = ("Active", "Superseded", "Forgotten", "Stale")
SOURCES = ("manual", "claude", "codex", "notes", "git")

PROPERTIES = {
    "Title": {"title": {}},
    "Mem ID": {"rich_text": {}},
    "Type": {"select": {"options": [{"name": t} for t in ALL_TYPES]}},
    "Concepts": {"multi_select": {}},
    "Strength": {"number": {}},
    "Source": {"select": {"options": [{"name": s} for s in SOURCES]}},
    "Project": {"select": {}},
    "Files": {"rich_text": {}},
    "Version": {"number": {}},
    "Related": {"rich_text": {}},  # mem_id 텍스트 + 관련 Notion 페이지 mention
    "Status": {"select": {"options": [{"name": s} for s in STATUSES]}},
    "Excerpt": {"rich_text": {}},  # 본문 앞 2000자 — 쿼리 필터가 본문을 못 보는 한계 우회
    "Link": {"url": {}},  # 외부 URL(예: GitHub 커밋) — --link(Notion 페이지 멘션)와 별개
    "Created": {"date": {}},
    "Updated": {"date": {}},
}


def db_url(database_id: str) -> str:
    """database_id → Notion DB 바로가기 URL (하이픈 제거 형식). calendar/notion_db.py 와 동형
    — status probe(core/status.py)가 두 skill 을 같은 방식으로 링크화한다."""
    return f"https://www.notion.so/{database_id.replace('-', '')}" if database_id else ""


def page_id_from_url(url: str) -> str:
    """Notion 페이지 URL 마지막 세그먼트의 32-hex → UUID."""
    tail = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    m = re.search(r"[0-9a-f]{32}$", tail.replace("-", ""))
    if not m:
        raise ValueError(f"Notion 페이지 URL에서 id를 찾지 못했습니다: {url}")
    h = m.group(0)
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _rt(text: str) -> list[dict]:
    """rich_text 프로퍼티 값 — Notion 항목당 2000자 한계 방어."""
    return [{"text": {"content": (text or "")[:2000]}}]


def _ms_name(name: str) -> str:
    """multi_select 옵션 이름 — 콤마 금지·100자 한계."""
    return name.replace(",", "·")[:100]


def _date(ts: str) -> dict | None:
    return {"start": ts} if ts else None


class NotASecondBrainError(ValueError):
    """채택 대상이 notionmemory second brain 스키마가 아님."""


def _related_rt(related_ids: list[str], link_page_ids: list[str]) -> list[dict]:
    """mem_id 텍스트 + 페이지 mention(클릭 가능 링크)을 한 rich_text 값으로."""
    rt: list[dict] = []
    text = ", ".join(related_ids)
    if text:
        rt.append({"text": {"content": text[:2000]}})
    for pid in link_page_ids:
        if rt:
            rt.append({"text": {"content": " "}})
        rt.append({"mention": {"page": {"id": pid}}})
    return rt


class SecondBrainDB:
    def __init__(self, session, log=None):
        self.session = session
        self.log = log or (lambda *_: None)

    # ---- 요청 공통 ----
    def _req(self, method: str, path: str, **kwargs):
        resp = self.session.request(method, path, **kwargs)
        if resp.status_code >= 300:
            raise RuntimeError(f"Notion {method} {path} 실패: {resp.status_code} {resp.text[:200]}")
        return resp

    # ---- 부트스트랩 ----
    def ensure(self, parent_page_id: str, meta) -> str:
        cached = meta.get_meta("data_source_id")
        if cached:
            r = self.session.request("GET", f"/data_sources/{cached}")
            if r.status_code == 200:
                props = r.json().get("properties") or {}
                # 스키마 진화 — 기존 data source 에 없는 속성만 골라 한 번의 PATCH로 추가
                # (마이그레이션 없음). 새 속성이 늘어나면 이 dict에만 추가하면 된다.
                evolutions = {"Excerpt": {"rich_text": {}}, "Link": {"url": {}}}
                missing = {k: v for k, v in evolutions.items() if k not in props}
                if missing:
                    self._req("PATCH", f"/data_sources/{cached}",
                              json={"properties": missing})
                return cached
            if r.status_code == 404:
                self.log(f"  ! 저장된 data source({cached}) 접근 불가({r.status_code}) → 재부트스트랩")
            else:
                raise RuntimeError(f"Notion GET /data_sources/{cached} 실패: {r.status_code} {r.text[:200]}")
        # parent_page_id 미지정 시 워크스페이스 최상위에 직접 생성 — 사이드바에서
        # 바로 DB가 열린다 (2025-09 API가 database의 workspace parent 지원).
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
        self.log(f"  · Second Brain DB 생성: database={body['id']} data_source={ds_id}")
        return ds_id

    def adopt(self, database_id: str, meta) -> list[str]:
        """기존 Notion DB를 second brain 으로 채택(strict) — 비파괴, 누락 속성만 추가."""
        db = self._req("GET", f"/databases/{database_id}").json()
        ds_id = db["data_sources"][0]["id"]
        props = self._req("GET", f"/data_sources/{ds_id}").json().get("properties") or {}
        # strict: 식별 속성 존재 + 타입 일치
        for name, want in (("Title", "title"), ("Mem ID", "rich_text")):
            if (props.get(name) or {}).get("type") != want:
                raise NotASecondBrainError(
                    f"'{name}'({want}) 속성이 없어 notionmemory second brain 이 아닙니다 "
                    f"— 새로 만들거나 이전 second brain DB URL 을 주세요")
        missing = {k: v for k, v in PROPERTIES.items() if k not in props}
        if missing:
            self._req("PATCH", f"/data_sources/{ds_id}", json={"properties": missing})
        meta.set_meta("database_id", db["id"])
        meta.set_meta("data_source_id", ds_id)
        return sorted(missing)

    # ---- 조회 ----
    def find_page_by_mem_id(self, data_source_id: str, mem_id: str) -> dict | None:
        resp = self._req("POST", f"/data_sources/{data_source_id}/query", json={
            "filter": {"property": "Mem ID", "rich_text": {"equals": mem_id}},
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

    def page_content(self, page_id: str) -> str:
        """블록 children 의 rich_text plain_text 를 줄 단위로 연결."""
        lines: list[str] = []
        cursor = None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._req("GET", f"/blocks/{page_id}/children", params=params).json()
            for block in data.get("results", []):
                payload = block.get(block.get("type"), {}) or {}
                if "rich_text" not in payload:
                    continue  # divider/이미지 등 텍스트 없는 블록 — 빈 줄 내지 않음
                lines.append("".join(rt.get("plain_text", "")
                                     for rt in payload.get("rich_text", [])))
            if not data.get("has_more"):
                return "\n".join(lines)
            cursor = data.get("next_cursor")

    # ---- 쓰기 ----
    def _props(self, memory: dict) -> dict:
        concepts = [c for c in (memory.get("concepts") or []) if isinstance(c, str) and c]
        props = {
            "Title": {"title": _rt(memory.get("title") or memory.get("id", ""))},
            "Mem ID": {"rich_text": _rt(memory["id"])},
            "Type": {"select": {"name": memory.get("type", "fact")}},
            "Concepts": {"multi_select": [{"name": _ms_name(c)} for c in concepts[:100]]},
            "Strength": {"number": memory.get("strength", 7)},
            "Source": {"select": {"name": memory.get("source", "manual")}},
            "Files": {"rich_text": _rt(", ".join(memory.get("files") or []))},
            "Version": {"number": memory.get("version", 1)},
            "Related": {"rich_text": _related_rt(memory.get("relatedIds") or [],
                                                 memory.get("linkPageIds") or [])},
            "Status": {"select": {"name": "Active"}},
            "Excerpt": {"rich_text": _rt(memory.get("content", ""))},
        }
        if memory.get("url"):
            props["Link"] = {"url": memory["url"]}
        if memory.get("project"):
            props["Project"] = {"select": {"name": _ms_name(memory["project"])}}
        created, updated = _date(memory.get("createdAt", "")), _date(memory.get("updatedAt", ""))
        if created:
            props["Created"] = {"date": created}
        if updated:
            props["Updated"] = {"date": updated}
        return props

    def _blocks(self, content: str) -> list[dict]:
        # rich_text 항목 2000자 한계 — 아주 긴 단일 행은 사전 분할
        lines = []
        for line in (content or "").splitlines():
            while len(line) > 1800:
                lines.append(line[:1800])
                line = line[1800:]
            lines.append(line)
        return markdown_to_blocks("\n".join(lines))

    def create_page(self, data_source_id: str, memory: dict) -> str:
        blocks = self._blocks(memory.get("content", ""))
        first, rest = blocks[:100], blocks[100:]
        resp = self._req("POST", "/pages", json={
            "parent": {"data_source_id": data_source_id},
            "properties": self._props(memory), "children": first})
        page_id = resp.json()["id"]
        for k in range(0, len(rest), 100):
            self._req("PATCH", f"/blocks/{page_id}/children", json={"children": rest[k:k + 100]})
        return page_id

    def set_status(self, page_id: str, status: str) -> None:
        self._req("PATCH", f"/pages/{page_id}",
                  json={"properties": {"Status": {"select": {"name": status}}}})
