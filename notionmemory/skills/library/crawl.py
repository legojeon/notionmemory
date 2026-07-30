"""library 크롤 — POST /search 로 공유 페이지 발견 + 증분/전체 색인.

증분은 `last_edited_time` watermark 이후만 걷는다(POST /search 를 edited desc 로
정렬해, watermark 이하를 만나면 멈춤). `--full` 은 전량을 훑고, 더 이상 공유되지
않는 항목을 색인에서 걷는다(prune). 증분은 삭제·공유해제를 못 보므로(검색에 안 나옴)
prune 하지 않는다 — 죽은 항목의 나머지 정리는 라이브 404 지연 삭제(retrieve/CLI)와
`--full` 재열거가 맡는다(스펙 §4).
"""
from __future__ import annotations

from datetime import datetime, timezone

from notionmemory.skills.library import index

SEARCH_PAGE_SIZE = 100


def _page_title(page: dict) -> str:
    for value in (page.get("properties") or {}).values():
        if value.get("type") == "title":
            return "".join(i.get("plain_text", "") for i in value.get("title") or [])
    return ""


def _page_headings(session, page_id: str, log=lambda *_: None) -> list:
    """최상위 children 한 페이지에서 heading_1/2/3 텍스트만. 깊이 순회 안 함
    (가벼운 색인 — 최상위 헤딩이면 충분, 페이지당 GET 한 번으로 묶는다)."""
    resp = session.request("GET", f"/blocks/{page_id}/children",
                           params={"page_size": 100})
    if resp.status_code >= 300:
        log(f"  · library: {page_id} 헤딩 조회 실패({resp.status_code}) — 제목만 색인")
        return []
    out = []
    for b in resp.json().get("results") or []:
        bt = b.get("type", "")
        if bt in ("heading_1", "heading_2", "heading_3"):
            rich = (b.get(bt) or {}).get("rich_text") or []
            out.append("".join(r.get("plain_text", "") for r in rich
                               if isinstance(r, dict)))
    return out


def refresh(session, *, full: bool = False, log=lambda *_: None) -> dict:
    idx = index.load()
    watermark = index.watermark(idx)
    seen: set = set()
    indexed = 0
    cursor = None
    stop = False
    completed = False
    while not stop:
        body = {"filter": {"property": "object", "value": "page"},
                "sort": {"timestamp": "last_edited_time", "direction": "descending"},
                "page_size": SEARCH_PAGE_SIZE}
        if cursor:
            body["start_cursor"] = cursor
        resp = session.request("POST", "/search", json=body)
        if resp.status_code >= 300:
            raise RuntimeError(f"Notion POST /search 실패: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        before = len(seen)
        for page in data.get("results") or []:
            if page.get("object") != "page":
                continue
            pid = page.get("id", "")
            edited = page.get("last_edited_time", "")
            seen.add(pid)
            # 증분: watermark 이하를 만나면 그 뒤는 더 오래됐으니(정렬 desc) 멈춘다.
            if not full and watermark and edited <= watermark:
                stop = True
                break
            headings = _page_headings(session, pid, log=log)
            index.upsert(idx, pid, title=_page_title(page), headings=headings,
                         url=page.get("url", ""), last_edited_time=edited)
            indexed += 1
        if stop:
            break
        if not data.get("has_more"):
            completed = True
            break
        # 진행 불변식 가드: has_more=true 인데 이번 요청이 새 페이지를 하나도 더하지
        # 못했다면(빈 결과·전부 중복·커서 정체) 멈춘다 — next_cursor 모양과 무관.
        # 자매 모듈 templates/store._fetch 가 실기 재현한 무한 요청(초당 수십만) 뒤
        # 추가한 STALLED 가드와 같은 방어: 커서만 믿고 전진을 보장하지 않는다.
        if len(seen) == before:
            log("  · library 크롤 중단 — /search 가 진행 없이 has_more=true (정체)")
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break

    pruned = 0
    if full and completed:      # 완전한 재열거였을 때만 prune — 중도 정체/커서 소실 시 여전히 공유된 페이지를 지우지 않는다
        # 전량 열거였으니, 이번에 안 보인 색인 항목은 공유 해제·삭제된 것.
        for pid in [p for p in idx["pages"] if p not in seen]:
            index.remove(idx, pid)
            pruned += 1

    if full and not idx["pages"]:
        idx["last_refreshed"] = ""       # full 인데 아무것도 안 남음 → watermark 초기화
    elif indexed:
        idx["last_refreshed"] = max(
            (e["last_edited_time"] for e in idx["pages"].values()
             if e.get("last_edited_time")), default=idx.get("last_refreshed", ""))
    # 벽시계 마커 — refresh 가 여기까지 왔으면 '한 번은 돌았다'. watermark(last_refreshed)
    # 는 빈 워크스페이스에선 "" 라 '미갱신'과 구분이 안 되므로 별도로 찍는다(스펙 §6 넛지).
    idx["last_run"] = datetime.now(timezone.utc).isoformat()
    if full:
        # `--full` 만이 prune 을 하므로 '마지막 전체 정리' 시각·드리프트 리셋도 여기서만.
        idx["last_full_run"] = idx["last_run"]
        idx["dirty_since_full"] = False
    index.save(idx)
    log(f"  · library 색인 갱신 — {indexed}건 색인, {pruned}건 정리, 총 {index.count(idx)}건")
    return {"indexed": indexed, "pruned": pruned, "total": index.count(idx)}
