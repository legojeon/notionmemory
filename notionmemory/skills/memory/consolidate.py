"""memory consolidation — Draft 초안을 LLM 이 검토해 승격/드롭/병합하고 프로젝트
브리프를 갱신한다(Second Brain v2 Phase 2a Task 4).

주 경로: `notionmemory memory consolidate`(사용자 터미널/cron, **비중첩** — 세션
안에서 재귀 호출하지 않는다). Stop 훅(Task 3)이 세션 종료마다 큐에 잡을 쌓아두고,
이 모듈이 그 큐를 드레인한다. 프로젝트 단위로 LLM 판정을 받아 Notion 에 반영하고
성공한 프로젝트의 잡만 ack 한다 — LLM 실패/파싱 실패/Notion 쓰기 실패 시 그
프로젝트의 잡은 큐에 남아 다음 회차에 재시도되고 Draft 는 그대로 보존된다."""
from __future__ import annotations

import json
import re
from collections import defaultdict

import requests

from notionmemory.core.agent_runtime import AgentRuntimeError, build_runtime
from notionmemory.core.config import Config
from notionmemory.core.notion_client import NotionSession
from notionmemory.skills.memory import consolidation_queue as queue
from notionmemory.skills.memory import reindex
from notionmemory.skills.memory.notion_db import _ms_name, excerpt_rt
from notionmemory.skills.memory.store import MemoryStore

SYSTEM = (
    "너는 한 프로젝트의 세션 초안 메모리를 정리하는 도우미다(claude-mem 의 관찰 정리 "
    "스타일 차용). 입력은 초안 목록 {mem_id, type, concepts, content} 이다. 각 항목을 "
    "판정하라: keep(요약·정제한 뒤 Strength 1~10 부여 — architecture/preference/durable "
    "패턴=8~10, workflow/재사용 가능한 bug=5~7, 스쳐가는 fact=1~4) 또는 drop(기록 가치 "
    "없음). 중복 초안은 merge 로 대표 하나만 keep 대상에 남기고 나머지 mem_id 를 "
    "drop 목록에 넣어라. "
    "keep 정제는 검색을 염두에 두고 써라: 고유명사·수치·날짜·제품명은 원문 표기 "
    "그대로 보존하고(일반화·바꿔쓰기 금지 — 나중에 이 값을 검색할 사람이 있다), "
    "요약은 3~8문장의 밀도 높은 사실 서술로 써서 나중에 물어볼 세부를 버리지 말 것. "
    "각 keep 항목에는 검색어로 쓸 concepts 도 함께 내라: 소문자·구체적인 개념 3~6개 "
    "(예: \"jwt-refresh-rotation\", 금지: \"auth\" 처럼 너무 넓은 단어). "
    "그리고 이 프로젝트의 핵심 개념·결정·선호를 롤업한 짧은 "
    "브리프(마크다운 8~15줄)를 작성하라. 설명·코드펜스 없이 JSON 객체 하나만 출력하라: "
    '{"items": [{"mem_id": "<mem_id>", "action": "keep|drop", "strength": 1-10, '
    '"content": "정제된 본문(선택, keep 일 때만 의미 있음)", '
    '"concepts": ["소문자-구체적", "..."] (선택, keep 일 때 3~6개 권장)}], '
    '"merges": [{"keep": "<mem_id>", "drop": ["<mem_id>", ...]}], '
    '"brief": "<마크다운 롤업>"}')

_EMPTY_TOTALS = {"promoted": 0, "dropped": 0, "merged": 0, "brief_updated": False}


def _parse_result(text: str) -> dict:
    cleaned = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text.strip())
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("JSON 객체가 아님")
    return data


def _build_prompt(project: str, drafts: list[dict]) -> str:
    parts = [f"프로젝트: {project}", "초안 메모리 목록:"]
    for d in drafts:
        concepts = ", ".join(d.get("concepts") or [])
        parts.append(f"- mem_id={d.get('mem_id', '')} type={d.get('type', '')} "
                     f"concepts=[{concepts}]")
        # 6000 — Draft 는 저장된 Excerpt 창(excerpt_rt 의 3×2000 유닛 청크, ≈6000)에서
        # 읽힌다. 그보다 좁은 상한으로 잘라 프롬프트에 넣으면 consolidation 이 distill
        # 해야 할 내용을 그 전에 이미 좁혀버리는 꼴이 된다(I4) — 저장 창과 맞춘다.
        parts.append(f"  content: {(d.get('content') or '')[:6000]}")
    return "\n".join(parts)


def _clamp_strength(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 5
    return max(1, min(10, n))


def _upsert_brief(db, ds: str, project: str, content: str) -> None:
    """프로젝트 롤업 1행 upsert — 예약 mem_id=f"brief-{project}", Type="brief",
    Strength=10, Status=Active. 있으면 속성 갱신 + 본문 전량 교체(`replace_content`),
    없으면 새로 만든다."""
    mem_id = f"brief-{project}"
    existing = db.find_page_by_mem_id(ds, mem_id)
    if existing:
        db.set_properties(existing["id"], {
            "Status": {"select": {"name": "Active"}},
            "Strength": {"number": 10},
            "Excerpt": {"rich_text": excerpt_rt(content)},
        })
        db.replace_content(existing["id"], content)
    else:
        db.create_page(ds, {
            "id": mem_id, "title": f"Project brief: {project}", "content": content,
            "type": "brief", "strength": 10, "status": "Active",
            "project": project, "concepts": [],
        })


def _apply(db, ds: str, project: str, drafts: list[dict], result: dict, totals: dict) -> None:
    """판정 결과를 Notion 에 반영한다.

    **재시도 안전성(진짜 트랜잭션은 불가능하므로)**: 이 함수는 원자적이지 않다 — 항목을
    순서대로 하나씩 쓰고, 중간에 Notion 쓰기가 실패하면 그 앞까지는 이미 반영된 채로
    예외가 올라간다(호출자 `run()`이 잡아 해당 프로젝트 잡을 ack 하지 않는다). 이건
    데이터 유실이 아니라 **품질 저하**로 받아들인다: 이미 Active/Forgotten/Superseded 로
    넘어간 페이지는 다음 회차의 `query_drafts`(Status=Draft)에 더는 잡히지 않으므로,
    재실행은 그 페이지를 건드리지 않고 나머지 Draft 만 다시 판정한다 — 같은 판정을
    다시 써도(Active→Active 등) `set_properties` 는 멱등이라 안전하다. `by_mem` 은 매
    호출마다 그 시점의 Draft 로만 새로 구성되므로, 이전 회차에 이미 승격/병합된
    mem_id 를 이번 회차 LLM 판정이 다시 언급해도(예: merge 가 참조) 그냥 무시된다."""
    by_mem = {d["mem_id"]: d for d in drafts if d.get("mem_id")}
    superseded: set[str] = set()
    for m in (result.get("merges") or []):
        if not isinstance(m, dict):
            continue
        keep = m.get("keep")
        drop_list = m.get("drop")
        if not isinstance(drop_list, list):
            continue
        for loser in drop_list:
            if (isinstance(loser, str) and loser in by_mem and loser != keep
                    and loser not in superseded):
                db.set_properties(by_mem[loser]["page_id"],
                                  {"Status": {"select": {"name": "Superseded"}}})
                superseded.add(loser)
                totals["merged"] += 1
    for item in (result.get("items") or []):
        if not isinstance(item, dict):
            continue
        mem_id = item.get("mem_id")
        if not isinstance(mem_id, str) or mem_id not in by_mem or mem_id in superseded:
            continue
        page_id = by_mem[mem_id]["page_id"]
        action = item.get("action")
        if action == "keep":
            props = {"Status": {"select": {"name": "Active"}},
                     "Strength": {"number": _clamp_strength(item.get("strength"))}}
            content = item.get("content")
            if isinstance(content, str) and content.strip():
                props["Excerpt"] = {"rich_text": excerpt_rt(content)}
            concepts = item.get("concepts")
            if isinstance(concepts, list):
                # 정제된 결과를 먼저 계산하고, 그게 비어있지 않을 때만 Concepts 를
                # 보낸다(M9a) — concepts 가 전부 비-문자열(예: dict)이라 정제 결과가
                # []이 되면, 그걸 그대로 multi_select:[] 로 보내 기존 옵션을 지워버리는
                # 사고를 막는다(all-invalid ≠ 의도적으로 비운 것).
                cleaned = [{"name": _ms_name(c)} for c in concepts[:6]
                          if isinstance(c, str) and c]
                if cleaned:
                    props["Concepts"] = {"multi_select": cleaned}
            db.set_properties(page_id, props)
            totals["promoted"] += 1
        elif action == "drop":
            db.set_properties(page_id, {"Status": {"select": {"name": "Forgotten"}}})
            totals["dropped"] += 1
        # 알 수 없는 action은 무시 — Draft 그대로 남아 다음 회차에 재고려된다.
    brief = result.get("brief")
    if isinstance(brief, str) and brief.strip():
        _upsert_brief(db, ds, project, brief.strip())
        totals["brief_updated"] = True


def run(config: Config, log, project: str = "") -> dict:
    jobs = queue.list_jobs()
    if project:
        jobs = [j for j in jobs if j.get("project") == project]
    if not jobs:
        log(f"'{project}' 프로젝트의 consolidation 잡이 없습니다" if project
            else "consolidation 큐가 비어 있습니다")
        return dict(_EMPTY_TOTALS)
    try:
        runtime = build_runtime(config)
    except AgentRuntimeError as e:
        log(f"consolidation 불가 — agent 런타임 미감지: {e} (Draft 보존)")
        return {**_EMPTY_TOTALS, "error": str(e)}
    try:
        store = MemoryStore(NotionSession(), config)
        db = store.db
        ds = store._data_source()
    except (RuntimeError, requests.RequestException) as e:
        log(f"Notion 세션 불가 — {e} (Draft 보존)")
        return {**_EMPTY_TOTALS, "error": str(e)}

    by_project: dict[str, list[dict]] = defaultdict(list)
    for j in jobs:
        by_project[j.get("project", "")].append(j)

    totals = dict(_EMPTY_TOTALS)
    errors: list[str] = []
    for proj, proj_jobs in by_project.items():
        job_ids = [j["id"] for j in proj_jobs]
        try:
            drafts = db.query_drafts(ds, proj)
            if not drafts:
                queue.ack(job_ids)  # 이미 정리된/빈 프로젝트 — 고아 잡만 치운다
                continue
            result = _parse_result(runtime.generate(SYSTEM, _build_prompt(proj, drafts)))
            _apply(db, ds, proj, drafts, result, totals)
        except (AgentRuntimeError, ValueError, json.JSONDecodeError, RuntimeError,
                requests.RequestException) as exc:
            # 이 프로젝트만 격리해서 실패시킨다 — 네트워크 순간 장애 하나가 같은 run()
            # 안의 다른 프로젝트 처리까지 끌고 내려가면 안 된다(flusher.py 와 동일 규율).
            log(f"consolidation 실패({proj}) — Draft 보존, 다음 회차에 재시도: {exc}")
            errors.append(f"{proj}: {exc}")
            continue
        queue.ack(job_ids)
        log(f"{proj}: consolidation 완료 (잡 {len(job_ids)}건 정리)")
    if errors:
        totals["error"] = "; ".join(errors)
    # Notion 을 방금 갱신했으니 로컬 색인도 최신으로 맞춘다 — best-effort: 이미 확정된
    # consolidate 의 성공/실패 판정(totals)을 reindex 실패가 무르면 안 된다. 색인은
    # 이제 recall 의 1차 로컬 랭킹 경로를 떠받치지만(remember 가 매 저장마다
    # write-through 하고, 라이브 검증이 사라진 항목을 read-repair 한다) 여전히 정합성
    # 크리티컬은 아니다 — 여기 이 전체 재계산이 실패해도 이전 색인이 그대로 남을
    # 뿐이고, 다음 회차에 다시 시도하면 된다.
    try:
        reindex.run(config, log)
    except Exception as e:  # noqa: BLE001 — 의도적으로 광범위: reindex 실패를 절대 전파 안 함
        log(f"memory reindex 갱신 실패(무시, 이전 색인 유지) — {e}")
    return totals
