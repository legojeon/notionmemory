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
    # Status: Active뿐 아니라 Draft도 포함 — Second Brain v2에서 새 메모리는 Draft로
    # 시작해 consolidation(별도 배치)이 Active로 승격/가지치기한다. Active만 걸면
    # consolidation 전까지 방금 저장한 메모리가 recall에서 보이지 않는다.
    clauses: list[dict] = [{"or": [
        {"property": "Status", "select": {"equals": "Active"}},
        {"property": "Status", "select": {"equals": "Draft"}},
    ]}]
    # Type=brief 는 consolidation 이 소유하는 프로젝트 롤업 예약 행(mem_id=brief-<project>)
    # — 일반 회수 결과로 절대 새어나가면 안 된다(notion_db.ALL_TYPES 에 브리프 추가 시
    # 이 제외절도 같이 추가됨).
    clauses.append({"property": "Type", "select": {"does_not_equal": "brief"}})
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
    # 인스턴스당 캐시 — 클래스 속성 기본값이라 테스트의 `MemoryStore.__new__(...)`
    # (=__init__ 우회) 헬퍼에서도 안전하게 조회된다.
    _ds_cache: str = ""

    def __init__(self, session, config: Config, log=None):
        self.db = SecondBrainDB(session, log=log)
        self.config = config
        self.meta = ConfigMeta(config)

    def _data_source(self) -> str:
        """data_source id — 인스턴스당 최대 1회만 `db.ensure()`(Notion GET 왕복)를
        타도록 캐시한다. ensure()는 캐시된 id가 살아있는지 매번 확인하는 네트워크
        호출이라, 캐시가 없으면 같은 인스턴스에서 project_brief 뒤에 top_memories
        를 부르는 것만으로도 이 왕복이 두 배가 된다(SessionStart memory_injection
        이 바로 이 패턴 — task-5 fix round 1). MemoryStore 는 CLI 커맨드/훅 호출/
        consolidate 실행 하나당 새로 만들어지고 그 이상 오래 살지 않으므로, 인스턴스
        수명 동안 데이터소스가 바뀔 일은 없다 — 캐시가 안전하다."""
        if not self._ds_cache:
            opts = self.config.skill_options("memory")
            self._ds_cache = self.db.ensure(str(opts.get("parent_page_id") or ""), self.meta)
        return self._ds_cache

    def remember(self, content: str, *, mem_type: str, concepts=(), project: str = "",
                 files=(), source: str = "manual", related=(), links=(),
                 supersedes: str = "", url: str = "",
                 status: str = "Active", strength: int = 7) -> dict:
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
            "concepts": list(concepts), "strength": strength, "status": status,
            "source": source,
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

    def project_brief(self, project: str) -> str:
        """프로젝트 롤업 브리프 본문(mem_id=f"brief-{project}") — 없으면 "".

        SessionStart 훅(Task 5)의 헤더 주입 전용. 일반 recall/top_memories 는
        Type=brief 를 제외하므로(build_filter) 여기서만 조회한다."""
        page = self.db.find_page_by_mem_id(self._data_source(), f"brief-{project}")
        if page is None:
            return ""
        return self.db.page_content(page["id"])

    def top_memories(self, project: str, *, min_strength: int = 8, limit: int = 3) -> list[dict]:
        """고Strength Active 메모리 top-K(Strength desc). Type=brief 는 build_filter 가
        이미 제외한다 — 브리프는 project_brief 전용 경로로만 노출된다(recall 과 동일
        규율). Draft 는 아직 정제 전이라 제외(Status=Active 만)."""
        ds = self._data_source()
        pages = self.db.query(ds, build_filter())
        hits = []
        for p in pages:
            props = p.get("properties", {})
            status = (props.get("Status", {}).get("select") or {}).get("name", "")
            if status != "Active":
                continue
            strength = (props.get("Strength", {}) or {}).get("number") or 0
            if strength < min_strength:
                continue
            summary = page_summary(p)
            if project and summary["project"] not in ("", project):
                continue
            summary["strength"] = strength
            hits.append(summary)
        hits.sort(key=lambda s: s["strength"], reverse=True)
        return hits[:limit]

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
