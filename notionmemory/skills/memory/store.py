"""memory direct mode 핵심 — remember/recall/get/forget (스펙 §5–6).

recall 3단 기준: 서버측 하드 필터(Status=Active+project+type) → 로컬 키워드
스코어링(제목3/Concepts2/Excerpt1, 동점은 최근 수정순, 전원 0점이면 최근 N건 폴백)
→ top-N 게이트(에이전트 토큰 상한).
"""
from __future__ import annotations

import re
import secrets
import string
import time
from datetime import datetime, timezone

from notionmemory.core.config import Config, SkillMeta
from notionmemory.skills.memory.notion_db import SecondBrainDB, page_id_from_url

_BASE36 = string.digits + string.ascii_lowercase


def new_mem_id(now_ms: int | None = None, rand: str | None = None) -> str:
    ts = int(time.time() * 1000) if now_ms is None else now_ms
    digits = ""
    while ts:
        ts, d = divmod(ts, 36)
        digits = _BASE36[d] + digits
    rand = rand or "".join(secrets.choice(_BASE36) for _ in range(12))
    return f"mem_{digits or '0'}_{rand}"


def tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^0-9a-z가-힣]+", (text or "").lower()) if t]


def _matches(token: str, text: str) -> bool:
    """ASCII 토큰은 단어 경계로, 한글 등 비ASCII 토큰은 부분 매칭으로 판정한다.

    ASCII 에 부분 매칭을 쓰면 짧은 토큰이 긴 단어 안에 걸려 오탐이 난다('ray'→'array').
    한글은 조사·어미가 공백 없이 붙어 '쿠버네티스의' 안의 '쿠버네티스'를 잡아야 하므로
    부분 매칭이 맞다(library.index._matches 와 같은 규율 — 회수 스코어링 일관성)."""
    if token.isascii():
        return re.search(rf"\b{re.escape(token)}\b", text) is not None
    return token in text


def score_page(tokens: list[str], *, title: str, concepts: list[str], excerpt: str) -> int:
    title_l = title.lower()
    concepts_l = " ".join(concepts).lower()
    excerpt_l = excerpt.lower()
    score = 0
    for t in tokens:
        if _matches(t, title_l):
            score += 3
        if _matches(t, concepts_l):
            score += 2
        if _matches(t, excerpt_l):
            score += 1
    return score


def build_filter(mem_type: str = "") -> dict:
    # Status/Type 옵션은 스키마에 시드되어 있어 서버 필터가 안전하다. Project 옵션은
    # 저장 시점에 동적으로 생기므로 스키마에 없는 값으로 select 필터를 걸면 Notion이
    # 400을 낸다 — recall이 클라이언트에서 project를 거른다.
    clauses: list[dict] = [{"property": "Status", "select": {"equals": "Active"}}]
    if mem_type:
        clauses.append({"property": "Type", "select": {"equals": mem_type}})
    return {"and": clauses}


def _plain(rich) -> str:
    return "".join(i.get("plain_text", "") for i in rich or [])


def page_summary(page: dict) -> dict:
    props = page.get("properties", {})
    return {
        "mem_id": _plain(props.get("Mem ID", {}).get("rich_text")),
        "title": _plain(props.get("Title", {}).get("title")),
        "type": (props.get("Type", {}).get("select") or {}).get("name", ""),
        "concepts": [o["name"] for o in props.get("Concepts", {}).get("multi_select", [])],
        "excerpt": _plain(props.get("Excerpt", {}).get("rich_text")),
        # 포인터 — git 캡처는 diff 원문 대신 이것만 남긴다(notion_db.py:172/180).
        # 뽑지 않으면 recall 이 "그런 결정이 있었다"까지만 전하고 "그 코드가 어디
        # 있다"를 못 전한다. Files 는 ", ".join 으로 저장된 평문이라 되돌려 쪼갠다.
        "files": [f for f in (t.strip() for t in
                              _plain(props.get("Files", {}).get("rich_text")).split(","))
                  if f],
        "url": props.get("Link", {}).get("url") or "",
        "project": (props.get("Project", {}).get("select") or {}).get("name", ""),
        "last_edited": page.get("last_edited_time", ""),
        "page_id": page.get("id", ""),
    }


class ConfigMeta(SkillMeta):
    """기존 계약 유지 — skills.memory 섹션 고정 (구현은 core SkillMeta로 일반화됨)."""

    def __init__(self, config: Config):
        super().__init__(config, "memory")


class MemoryStore:
    def __init__(self, session, config: Config, log=None):
        self.db = SecondBrainDB(session, log=log)
        self.config = config
        self.meta = ConfigMeta(config)

    def _data_source(self) -> str:
        opts = self.config.skill_options("memory")
        return self.db.ensure(str(opts.get("parent_page_id") or ""), self.meta)

    def remember(self, content: str, *, mem_type: str, concepts=(), project: str = "",
                 files=(), source: str = "manual", related=(), links=(),
                 supersedes: str = "", url: str = "") -> dict:
        ds = self._data_source()
        old = None
        if supersedes:
            old = self.db.find_page_by_mem_id(ds, supersedes)
            if old is None:
                raise ValueError(f"supersede 대상 mem_id 없음: {supersedes}")
        now = datetime.now(timezone.utc).isoformat()
        mem_id = new_mem_id()
        first_line = (content.strip().splitlines() or [""])[0]
        # lstrip("# ")은 문자 집합 제거라 내용의 #까지 벗긴다 — 선두 마크업만 제거
        title = re.sub(r"^#+\s*", "", first_line).strip()[:200] or mem_id
        memory = {
            "id": mem_id, "title": title, "content": content, "type": mem_type,
            "concepts": list(concepts), "strength": 7, "source": source,
            "project": project, "files": list(files), "version": 1,
            "relatedIds": list(related),
            "linkPageIds": [page_id_from_url(u) for u in links],
            "url": url,
            "createdAt": now, "updatedAt": now,
        }
        page_id = self.db.create_page(ds, memory)
        result = {"mem_id": mem_id, "page_id": page_id, "concepts": list(concepts)}
        if old is not None:
            try:
                self.db.set_status(old["id"], "Superseded")
            except Exception as e:  # noqa: BLE001 — 저장은 이미 성공, mem_id는 반드시 알려야 함
                result["supersede_error"] = str(e)
                result["supersede_target"] = old["id"]
        return result

    def recall(self, query: str = "", *, mem_type: str = "", project: str = "",
               top: int = 5) -> dict:
        ds = self._data_source()
        pages = self.db.query(ds, build_filter(mem_type=mem_type))
        summaries = [page_summary(p) for p in pages]
        if project:
            summaries = [s for s in summaries if s["project"] in ("", project)]
        tokens = tokenize(query)
        scored = [(score_page(tokens, title=s["title"], concepts=s["concepts"],
                              excerpt=s["excerpt"]), s) for s in summaries]
        hits = [x for x in scored if x[0] > 0]
        hits.sort(key=lambda x: (x[0], x[1]["last_edited"]), reverse=True)
        if hits:
            return {"results": [s for _, s in hits[:top]], "fallback": False}
        recent = sorted(summaries, key=lambda s: s["last_edited"], reverse=True)
        return {"results": recent[:top], "fallback": True}

    def get(self, mem_id: str) -> dict | None:
        page = self.db.find_page_by_mem_id(self._data_source(), mem_id)
        if page is None:
            return None
        summary = page_summary(page)
        summary["content"] = self.db.page_content(page["id"])
        return summary

    def forget(self, mem_id: str) -> bool:
        page = self.db.find_page_by_mem_id(self._data_source(), mem_id)
        if page is None:
            return False
        self.db.set_status(page["id"], "Forgotten")
        return True
