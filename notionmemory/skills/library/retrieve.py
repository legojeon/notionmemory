"""library 회수 — content 색인 + memory recall 팬아웃.

두 소스의 점수는 척도가 달라(content 어휘 vs memory score_page) 전역 랭킹하지
않는다 — 각 소스 상위 N을 **출처 라벨 붙여 그룹으로** 낸다. 소스 간 우열은 에이전트가
라이브로 읽어 판단한다(스펙 §2, "의미는 에이전트가"). library 는 content 색인을
소유하고 memory recall 을 호출할 뿐 — calendar/templates 는 구조 질의라 부르지 않는다.
"""
from __future__ import annotations

from notionmemory.skills.library import index
from notionmemory.skills.memory.store import MemoryStore

SOURCES = ("content", "memory")


def search(session, config, query: str, *, limit: int = 25,
           sources=SOURCES) -> list[dict]:
    out: list = []
    if "content" in sources:
        idx = index.load()
        for h in index.search(idx, query, limit=limit):
            out.append({"source": "content", "id": h["page_id"], "title": h["title"],
                        "section": ", ".join(h["headings"]) if h["headings"] else "",
                        "score": h["score"]})
    if "memory" in sources:
        res = MemoryStore(session, config).recall(query, top=limit)
        if not res.get("fallback"):        # 폴백(최근 N개)은 매칭이 아니다 — content 처럼 무매칭=무결과
            for s in res.get("results", []):
                out.append({"source": "memory", "id": s.get("mem_id", ""),
                            "title": s.get("title", ""),
                            "section": s.get("type", ""), "score": 0})
    return out
