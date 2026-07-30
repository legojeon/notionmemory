"""memory 로컬 색인 — Notion 없이 메시지당(per-message) 회수하기 위한 온디스크 인덱스.

library.index 와 같은 패턴(state_dir() 아래 index.json, load/save)이지만 내용은
memory 전용이다: 페이지 포인터가 아니라 title/concepts/excerpt/strength/type/
project/status 를 그대로 담아 네트워크 없이 lexical 스코어링한다.

어휘 매칭(ASCII 단어경계 + 한글 부분매칭)은 새로 만들지 않고 `store.score_page`/
`store.tokenize` 를 그대로 재사용한다 — 스코어링 규율을 리포 전체에서 한 곳에만
둔다(recall 과 여기가 다른 결과를 내면 혼란만 커진다).

Type=="brief" 는 build() 에서부터 걸러 색인에 절대 들어오지 않는다 — 브리프는
세션-시작 헤더 전용(project_brief)이고 메시지당 검색 결과로 새면 안 된다
(store.build_filter 의 Type != brief 규율과 동일).
"""
from __future__ import annotations

import json
from pathlib import Path

from notionmemory.core import paths
from notionmemory.skills.memory.store import score_page, tokenize

_EXCERPT_MAX = 2000


def index_path() -> Path:
    return paths.state_dir() / "memory" / "index.json"


def build(memories: list) -> dict:
    """메모리 목록 → {mem_id: {...}} 색인. Type=="brief" 는 제외."""
    idx: dict = {}
    for m in memories:
        if m.get("type") == "brief":
            continue
        mem_id = m.get("id", "")
        if not mem_id:
            continue
        excerpt = (m.get("content") or "")[:_EXCERPT_MAX]
        idx[mem_id] = {
            "title": m.get("title", ""),
            "concepts": list(m.get("concepts") or []),
            "excerpt": excerpt,
            "strength": m.get("strength", 0),
            "type": m.get("type", ""),
            "project": m.get("project", ""),
            "status": m.get("status", ""),
        }
    return idx


def load() -> dict:
    p = index_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {}


def save(idx: dict) -> None:
    p = index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")


def search(idx: dict, query: str, *, project: str = "", limit: int = 3,
           min_score: int = 1) -> list:
    """lexical 점수(store.score_page) × Strength 가중 → gate → top-N.

    랭킹 키 = (score, strength) desc — score 가 1차(관련성), 동점일 때만 Strength 로
    깨진다. min_score 가 관련성 게이트: 이 아래는 아예 반환하지 않는다(메시지당
    주입이 조용해지는 핵심 장치 — 무관한 메모리가 새어들지 않게 한다)."""
    tokens = tokenize(query)
    hits = []
    for mem_id, e in idx.items():
        if e.get("type") == "brief":
            continue
        if e.get("status") not in ("Active", "Draft"):
            continue
        if project and e.get("project") not in ("", project):
            continue
        score = score_page(tokens, title=e.get("title", ""),
                            concepts=e.get("concepts") or [],
                            excerpt=e.get("excerpt", ""))
        if score < min_score:
            continue
        strength = e.get("strength", 0)
        hits.append((score, strength, mem_id, e))
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    return [{"mem_id": mem_id, "title": e.get("title", ""),
             "strength": e.get("strength", 0), "concepts": e.get("concepts") or [],
             "excerpt": e.get("excerpt", ""), "type": e.get("type", ""),
             "project": e.get("project", ""), "status": e.get("status", "")}
            for _, _, mem_id, e in hits[:limit]]
