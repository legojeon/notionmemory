"""memory 로컬 색인 재생성 — Notion Second Brain DB 전체(Active+Draft, Type≠brief)를
읽어 `mem_index.build`/`save` 로 온디스크 색인(`index.json`)을 통째로 새로 만든다.

호출자 둘: CLI `notionmemory memory reindex`(수동/cron)와 `consolidate.run` 성공 경로
끝(방금 Notion 을 갱신했으니 색인도 최신으로 맞춘다, best-effort — 실패해도 consolidate
자체의 성공 판정을 무르지 않는다, consolidate.py 참고).

Notion/네트워크 실패는 여기서 흡수해 생 traceback 을 호출자에 새지 않게 한다 — 실패 시
-1 을 반환하고 log 로만 알린다. 색인은 recall 의 오프라인 폴백 경로일 뿐 정합성
크리티컬은 아니므로, 실패하면 이전 색인을 그대로 둔 채 다음 회차 재시도로 충분하다."""
from __future__ import annotations

import requests

from notionmemory.core.config import Config
from notionmemory.core.notion_client import NotionSession
from notionmemory.skills.memory import mem_index
from notionmemory.skills.memory.store import MemoryStore, build_filter, page_summary


def _to_memory(page: dict) -> dict:
    """page_summary(recall/get 공용 매퍼) 를 재사용하고 mem_index 가 기대하는 필드로
    맞춘다(mem_id→id, excerpt→content) + Strength/Status 를 추가로 뽑는다.

    page_summary 자체에 Strength/Status 를 얹지 않는 이유: 그 함수는 recall/get 계약이
    exact-dict 테스트로 고정돼 있다(test_memory_store.test_page_summary_extracts_fields)
    — top_memories 가 이미 쓰는 것과 같은 패턴으로, 필요한 호출부에서 속성을 직접
    더 뽑는다."""
    s = page_summary(page)
    props = page.get("properties", {})
    strength = (props.get("Strength", {}) or {}).get("number") or 0
    status = (props.get("Status", {}).get("select") or {}).get("name", "")
    return {
        "id": s["mem_id"], "title": s["title"], "concepts": s["concepts"],
        "strength": strength, "type": s["type"], "project": s["project"],
        "status": status, "content": s["excerpt"],
    }


def run(config: Config, log) -> int:
    """전체 Active+Draft(non-brief) 메모리를 조회해 로컬 색인을 다시 쓴다. 반환값 =
    색인된 건수, 실패 시 -1(생 traceback 없이)."""
    try:
        store = MemoryStore(NotionSession(), config, log=log)
        # 조회 경로 — 미바인딩이면 DB 를 만들지 말고(고아 DB 기전) 안내하고 끝낸다.
        ds = store._data_source(create=False)
        if not ds:
            log("memory reindex 실패 — memory 가 아직 연결되지 않았습니다: "
                "`notionmemory memory connect --new`(또는 --url) 먼저 (기존 색인 유지)")
            return -1
        pages = store.db.query(ds, build_filter())
    except (RuntimeError, requests.RequestException) as e:
        log(f"memory reindex 실패 — Notion 조회 불가: {e} (기존 색인 유지)")
        return -1
    memories = [_to_memory(p) for p in pages]
    idx = mem_index.build(memories)
    mem_index.save(idx)
    log(f"memory reindex 완료 — {len(idx)}건 색인")
    return len(idx)
