"""memory consolidation — Draft 초안을 LLM 이 검토해 승격/드롭/병합하고 프로젝트
브리프를 갱신한다(Second Brain v2 Phase 2a Task 4).

주 경로: `notionmemory memory consolidate`(사용자 터미널/cron, **비중첩** — 세션
안에서 재귀 호출하지 않는다). Stop 훅(Task 2)이 세션 종료마다 큐에 잡을 쌓아두고,
이 모듈이 그 큐를 드레인한다. 프로젝트 단위로 LLM 판정을 받아 Notion 에 반영하고
성공한 프로젝트의 잡만 ack 한다 — LLM 실패/파싱 실패/Notion 쓰기 실패 시 그
프로젝트의 잡은 큐에 남아 다음 회차에 재시도되고 Draft 는 그대로 보존된다.

Task 3(발굴): 잡에는 Draft 뿐 아니라 세션 트랜스크립트 발췌(`sessions`)도 실려
있을 수 있다 — 이 모듈이 `transcripts.collect_excerpts` 로 대화 원문을 읽어 같은
LLM 패스에 얹고, 지속 가치가 있으면 `action:"new"` 로 곧장 Active 메모리를 만든다
(Draft 를 안 거친다 — 세션 발췌는 애초에 초안화할 대상이 아니라 발굴 원료다)."""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

import requests

from notionmemory.core.agent_runtime import AgentRuntimeError, build_runtime
from notionmemory.core.config import Config
from notionmemory.core.notion_client import NotionSession
from notionmemory.skills.memory import consolidation_queue as queue
from notionmemory.skills.memory import mem_index
from notionmemory.skills.memory import reindex
from notionmemory.skills.memory import transcripts
from notionmemory.skills.memory.notion_db import CAPTURE_TYPES, _ms_name, excerpt_rt
from notionmemory.skills.memory.store import MemoryStore

# SYSTEM 은 영어가 canonical 이다(사용자 결정 2026-08-02: 지시문은 영어가 토큰 효율이
# 좋고, 출력 언어는 config `language` 를 따르는 한 줄을 _system_for 가 덧붙인다).
# WHAT TO SKIP 목록과 GOOD/BAD 예시는 실측 결함에서 나왔다: 라이브 운용 첫날 저장분의
# ~40%가 "태스크 N 완료(커밋 해시…)" 류 진행 저널이었다 — git 히스토리가 이미 기록하는
# 것과 유효기간 지난 상태는 애초에 저장하지 않는다(claude-mem 의 recording_focus/
# skip_guidance 구조 차용).
SYSTEM = (
    "You are the memory curator for a coding agent's long-term memory; each pass covers one "
    "project. Input: a list of draft memories {mem_id, type, concepts, content}, and "
    "optionally session conversation excerpts ([USER]/[ASSISTANT] fragments per session) plus "
    "the project's existing Active memory list (title + concepts).\n"
    "\n"
    "JUDGE each draft: keep (refine it, assign Strength 1-10) or drop (no lasting value). "
    "Merge duplicate drafts: keep one representative, list the rest under merges. "
    "MINE the session excerpts for durable knowledge and emit each finding as a new item: "
    '{"action": "new", "type": "pattern|preference|architecture|bug|workflow|fact", '
    '"content": "...", "concepts": [...], "strength": 1-10}.\n'
    "\n"
    "WHAT TO RECORD — knowledge someone will still need a month from now:\n"
    "- decisions and their rationale (what was chosen, what was rejected, why)\n"
    "- durable patterns and architecture facts (how the system now works)\n"
    "- user preferences and corrections (include why, and how to apply them)\n"
    "- bug root causes and their fixes (the lesson, not the incident timeline)\n"
    "\n"
    "WHAT TO SKIP — never record:\n"
    "- session progress narration: 'completed task N', 'finished the design phase', "
    "'review found 3 issues', commit hashes and commit lineages — git history already records "
    "these\n"
    "- transient state that expires: missing env vars later fixed, temporary blockers, "
    "in-progress status\n"
    "- process descriptions ('analyzed X', 'reviewed Y and noted findings') — record what "
    "changed or what was learned, never what was done\n"
    "GOOD: 'Speech-style switching is a propose-accept-confirm three-way split; automatic "
    "switching on level-up was rejected because users must opt in.'\n"
    "BAD: 'Completed tasks 1-2 of Phase 1 (commits 86c76c6, 1dd0712).'\n"
    "Producing ZERO new items is normal when a session holds no durable knowledge — never "
    "force one. Prefer fewer, denser memories: merge related findings into one item.\n"
    "\n"
    "Strength rubric: architecture / preference / durable pattern = 8-10; workflow / reusable "
    "bug lesson = 5-7; passing fact = 1-4. Progress-journal content never deserves 5+ — it "
    "should have been skipped entirely.\n"
    "\n"
    "Write for future SEARCH: preserve proper nouns, numbers, dates and product names verbatim "
    "(no paraphrasing — someone will search for these exact values); 3-8 dense factual "
    "sentences per item; give each kept/new item 3-6 lowercase, specific concepts "
    '(e.g. "jwt-refresh-rotation"; never broad words like "auth").\n'
    "Deduplicate: a new item must not repeat a kept draft (keep only the draft), and must not "
    "repeat anything already covered by the existing Active memory list.\n"
    "Also write a short rolled-up project brief (8-15 lines of markdown) covering the "
    "project's core concepts, decisions and preferences.\n"
    "\n"
    "Output exactly one JSON object — no prose, no code fences:\n"
    '{"items": [{"mem_id": "<mem_id>", "action": "keep|drop", "strength": 1-10, '
    '"content": "refined body (keep only)", "concepts": ["lowercase-specific", ...]}, '
    '{"action": "new", "type": "...", "content": "...", "concepts": [...], '
    '"strength": 1-10}], '
    '"merges": [{"keep": "<mem_id>", "drop": ["<mem_id>", ...]}], '
    '"brief": "<markdown rollup>"}')

# 출력 언어 지시 — Notion 에 적히는 내용의 언어는 config `language` 를 따른다(템플릿).
# UI 언어(i18n.VALID: en|ko — 카탈로그 번역이 필요)와 달리, 출력 언어는 LLM 지시 한
# 줄이라 어떤 언어든 즉시 동작한다. 그래서 여기서는 i18n.language() 의 en 클램프를
# 일부러 안 탄다: 이름 맵에 없는 값(예: "vi")은 코드 그대로 템플릿에 넣는다 — LLM 이
# 이해한다. UI 는 그 값에서 여전히 en 으로 폴백하므로 충돌이 없다.
_LANG_NAMES = {
    "en": "English",
    "ko": "Korean (한국어)",
    "zh": "Chinese (中文)",
    "ja": "Japanese (日本語)",
}
_LANG_LINE_TMPL = ("Write every memory content and the brief in {name}. Keep code "
                   "identifiers, proper nouns and established technical terms as-is.")


def _system_for(config) -> str:
    """SYSTEM + 출력 언어 한 줄(config `language` 기반 템플릿, 기본 en)."""
    raw = str(config.get("language") or "en").strip() or "en"
    return SYSTEM + "\n" + _LANG_LINE_TMPL.format(name=_LANG_NAMES.get(raw, raw))

MIN_EXCERPT_CHARS = 2000  # 이보다 적으면 LLM 을 안 돌린다 — Draft 없이 발췌만 조금
                          # 있는 상태에서 매 consolidate 회차마다 헛돈다(스펙 §3).

_EMPTY_TOTALS = {"promoted": 0, "dropped": 0, "merged": 0, "brief_updated": False, "mined": 0}


def _parse_result(text: str) -> dict:
    cleaned = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text.strip())
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("JSON 객체가 아님")
    return data


def _build_prompt(project: str, drafts: list[dict], excerpts=(), active_summaries=()) -> str:
    parts = [f"Project: {project}", "Draft memories:"]
    for d in drafts:
        concepts = ", ".join(d.get("concepts") or [])
        parts.append(f"- mem_id={d.get('mem_id', '')} type={d.get('type', '')} "
                     f"concepts=[{concepts}]")
        # 6000 — Draft 는 저장된 Excerpt 창(excerpt_rt 의 3×2000 유닛 청크, ≈6000)에서
        # 읽힌다. 그보다 좁은 상한으로 잘라 프롬프트에 넣으면 consolidation 이 distill
        # 해야 할 내용을 그 전에 이미 좁혀버리는 꼴이 된다(I4) — 저장 창과 맞춘다.
        parts.append(f"  content: {(d.get('content') or '')[:6000]}")
    if active_summaries:
        # dedup 컨텍스트 — new 가 이미 Active 인 사실을 다시 만들지 않도록 참고만.
        parts.append("")
        parts.append("Existing Active memories (title · concepts) — do not emit a new item "
                     "for facts already covered here:")
        for a in active_summaries:
            concepts = ", ".join(a.get("concepts") or [])
            parts.append(f"- {a.get('title', '')} · [{concepts}]")
    if excerpts:
        parts.append("")
        parts.append("Session conversation excerpts:")
        for e in excerpts:
            parts.append(f"--- session {e.get('session_id', '')} "
                         f"({e.get('harness', '')}) ---")
            parts.append(e.get("text", ""))
    return "\n".join(parts)


def _clamp_strength(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 5
    return max(1, min(10, n))


_DEDUP_LIMIT = 100


def _dedup_context(project: str) -> list[dict]:
    """new-발굴 dedup 컨텍스트를 로컬 mem_index 에서만 뽑는다(I3, network 0).

    예전엔 `db.query_active_summaries` 로 프로젝트마다 Active 행 전량을 매 회차
    Notion 에서 페이지네이션해 왔다 — 무인 백그라운드 잡이 매 pass 마다 프로젝트당
    전체 DB 스캔을 하는 건 과하다. `remember()`의 write-through 와 매 consolidate
    성공 뒤의 `reindex.run()`이 로컬 색인을 계속 최신으로 맞추므로, "이미 아는 사실
    다시 만들지 말 것" 참고 목적엔 로컬 색인으로 충분하다. 색인이 없거나 손상됐으면
    `mem_index.load()`가 이미 {} 로 방어하므로 빈 리스트를 돌려주고 발굴 패스는 그냥
    dedup 컨텍스트 없이 계속 돈다(있으면 좋고 없어도 되는 정보)."""
    idx = mem_index.load()
    out: list[dict] = []
    for doc in mem_index.docs(idx).values():
        if doc.get("type") == "brief":
            continue  # 방어적 — build()/add_memory() 가 이미 브리프를 색인에서 제외한다
        if doc.get("status") != "Active":
            continue
        proj = doc.get("project", "")
        if project and proj != project:
            continue
        out.append({"title": doc.get("title", ""), "concepts": list(doc.get("concepts") or [])})
        if len(out) >= _DEDUP_LIMIT:
            break
    return out


def _ack_jobs(proj_jobs: list[dict], sessions: list[dict]) -> None:
    """이 프로젝트의 job(들)을 compare-and-delete 로 ack 한다(M1).

    `sessions`는 이 회차 시작 시점에 `proj_jobs`에서 읽은 스냅샷이다 — 그 session_id
    들만 "처리 완료"로 넘기고, 각 잡의 스냅샷 `ts`를 함께 넘겨 `ack_sessions`가
    ack 시점에 파일이 그 사이 바뀌었는지(=Stop 이 LLM 패스 도중 새 세션을 끼워
    넣었는지) 판정하게 한다. 바뀌었으면 새로 들어온 세션은 살아남는다."""
    mined_ids = {s.get("session_id") for s in sessions if s.get("session_id")}
    for j in proj_jobs:
        queue.ack_sessions(j["id"], mined_ids, j.get("ts", ""))


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


def _apply(store, ds: str, project: str, drafts: list[dict], result: dict, totals: dict,
          harness_by_default: str = "claude") -> None:
    """판정 결과를 Notion 에 반영한다.

    **재시도 안전성(진짜 트랜잭션은 불가능하므로)**: 이 함수는 원자적이지 않다 — 항목을
    순서대로 하나씩 쓰고, 중간에 Notion 쓰기가 실패하면 그 앞까지는 이미 반영된 채로
    예외가 올라간다(호출자 `run()`이 잡아 해당 프로젝트 잡을 ack 하지 않는다). 이건
    데이터 유실이 아니라 **품질 저하**로 받아들인다: 이미 Active/Forgotten/Superseded 로
    넘어간 페이지는 다음 회차의 `query_drafts`(Status=Draft)에 더는 잡히지 않으므로,
    재실행은 그 페이지를 건드리지 않고 나머지 Draft 만 다시 판정한다 — 같은 판정을
    다시 써도(Active→Active 등) `set_properties` 는 멱등이라 안전하다. `by_mem` 은 매
    호출마다 그 시점의 Draft 로만 새로 구성되므로, 이전 회차에 이미 승격/병합된
    mem_id 를 이번 회차 LLM 판정이 다시 언급해도(예: merge 가 참조) 그냥 무시된다.

    `action:"new"`(세션 발췌 발굴)는 Draft 를 안 거치고 `store.remember()` 로 곧장
    Active 메모리를 만든다(mem_id 발급·제목 파생·write-through 를 재사용) — 그래서
    이 함수가 이제 `db` 가 아니라 `store` 를 받는다."""
    db = store.db
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
        action = item.get("action")
        if action == "new":
            # 세션 발췌 발굴 — mem_id 가 없다(Draft 를 안 거쳤으니 by_mem 에 없는 게
            # 정상). content 없으면 무시(LLM 이 껍데기만 낸 경우 방어).
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            mem_type = item.get("type")
            if mem_type not in CAPTURE_TYPES:
                mem_type = "fact"
            raw_concepts = item.get("concepts")
            concepts = ([c for c in raw_concepts if isinstance(c, str) and c][:6]
                       if isinstance(raw_concepts, list) else [])
            store.remember(content.strip(), mem_type=mem_type, concepts=concepts,
                           project=project, source=harness_by_default, status="Active",
                           strength=_clamp_strength(item.get("strength")))
            totals["mined"] += 1
            continue
        mem_id = item.get("mem_id")
        if not isinstance(mem_id, str) or mem_id not in by_mem or mem_id in superseded:
            continue
        page_id = by_mem[mem_id]["page_id"]
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


def run(config: Config, log, project: str = "", auto: bool = False) -> dict:
    # 재귀 가드 — 스폰하는 쪽(훅)이 아니라 여기서 세팅한다: 사용자 터미널/cron 의
    # 수동 실행 경로도 이 env 를 거치지 않으므로, 훅 밖에서 세팅하면 그 경로는
    # 가드가 안 걸려 consolidate 도중의 Notion 쓰기·LLM 호출이 다시 Stop 훅을 태워
    # 자기 세션을 재큐잉하는 루프가 생긴다(Task 4 에서 훅들이 이 변수를 보고
    # no-op 하게 만든다).
    os.environ["NOTIONMEMORY_CONSOLIDATE"] = "1"
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
        if auto:
            # C1 — 무인 백그라운드 스폰(훅) 경로는 DB 를 만들면 안 된다. autorun.
            # maybe_spawn 이 이미 한 번 "memory bound?" 를 로컬로 확인하지만(1차
            # 방어선), 그 판정과 이 실행 사이에 무언가 달라질 수 있으므로(다른
            # 프로세스가 그 사이 언바인드했다거나) 여기서도 create=False 로 다시
            # 확인한다(2차 방어선, defense in depth) — `SecondBrainDB.ensure`
            # 자신의 계약(조회/훅 경로가 DB 를 만들면 안 됨)을 이 경로에도 그대로
            # 적용하는 것뿐이다. 수동 실행(`auto=False`, 사용자가 터미널에서 직접
            # 돌린 것)은 기존과 동일하게 필요하면 부트스트랩한다.
            ds = store._data_source(create=False)
            if not ds:
                log("memory 미바인딩 — 자동 consolidate 건너뜀, 큐 보존")
                return dict(_EMPTY_TOTALS)
        else:
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
            # M2 — 이 Notion 왕복(query_drafts)은 아래 min-material 게이트보다 먼저
            # 온다, 그리고 그건 불가피하다: 게이트가 "발췌만 있고 Draft 는 없을 때
            # MIN_EXCERPT_CHARS 미만이면 스킵"을 판정하려면 애초에 Draft 개수를 알아야
            # 한다(drafts 가 하나라도 있으면 발췌량과 무관하게 게이트를 우회한다 —
            # 아래 `if not drafts and excerpt_chars < MIN_EXCERPT_CHARS`). 세션이
            # 아예 없는 잡이라고 미리 건너뛸 수도 없다 — Draft 는 세션과 독립적으로
            # 존재할 수 있어(사용자가 `remember --auto` 로만 쌓은 경우) sessions 유무로
            # query_drafts 자체를 생략하면 안 된다. 그래서 auto 모드에서도 (C1 의
            # no-create 가드를 통과한 뒤엔) 이 조회 자체는 막지 않는다 — 막을 수 있는
            # 안전하고 정확한 재정렬을 찾지 못했다(정직하게 comment-only로 남긴다).
            drafts = db.query_drafts(ds, proj)
            sessions = [s for j in proj_jobs for s in (j.get("sessions") or [])]
            ledger = transcripts.load_ledger()
            excerpts, notes = transcripts.collect_excerpts(
                sessions, ledger, expect_project=proj)
            for note in notes:
                log(f"{proj}: {note}")
            if not drafts and not excerpts:
                _ack_jobs(proj_jobs, sessions)  # 이미 정리된/빈 프로젝트 — 고아 잡만 치운다
                continue
            excerpt_chars = sum(len(e["text"]) for e in excerpts)
            if not drafts and excerpt_chars < MIN_EXCERPT_CHARS:
                # 재료가 아직 얇다 — ack 하지 않는다: 다음 세션들이 큐에 계속 쌓여
                # 발췌가 누적되게 둔다(원장도 안 건드려 같은 바이트가 다시 잡힌다).
                log(f"{proj}: 발췌 {excerpt_chars}자 — 최소 {MIN_EXCERPT_CHARS}자 "
                    "미달, 누적 대기(큐 보존)")
                continue
            active_summaries = _dedup_context(proj)
            harness_by_default = excerpts[0]["harness"] if excerpts else "claude"
            prompt = _build_prompt(proj, drafts, excerpts=excerpts,
                                   active_summaries=active_summaries)
            result = _parse_result(runtime.generate(_system_for(config), prompt))
            _apply(store, ds, proj, drafts, result, totals,
                  harness_by_default=harness_by_default)
            if excerpts:
                # 성공한 뒤에만 원장을 갱신한다 — 게이트에 걸려 continue 한 경로는
                # 여기 안 오므로 같은 바이트가 다음 회차에 다시 발굴 후보가 된다.
                now_iso = datetime.now(timezone.utc).isoformat()
                for e in excerpts:
                    if e.get("truncated"):
                        # TOTAL_CAP 에 걸려 이 세션의 뒷부분을 LLM 이 못 봤다 —
                        # `consumed_bytes`(파일 오프셋)를 원장에 그대로 기록하면 못 본
                        # 뒷부분이 "이미 발굴됨"으로 표시돼 영원히 유실된다. 원장을
                        # 안 건드려 다음 회차에 같은 오프셋부터 재발굴한다(중복은
                        # 프롬프트의 기존 Active dedup 컨텍스트가 흡수).
                        continue
                    ledger[e["session_id"]] = {"bytes": e["consumed_bytes"], "ts": now_iso}
                try:
                    transcripts.save_ledger(ledger)
                except OSError as exc2:
                    # 디스크 풀/권한 등 — 원장 쓰기 실패가 이 프로젝트를(나아가 같은
                    # run() 안의 나머지 프로젝트까지) 죽이면 안 된다(per-project 격리
                    # 불변식, flusher.py 와 동일 규율). Notion 반영은 이미 끝났으니
                    # ack 은 그대로 진행한다 — 최악의 결과는 원장이 안 앞당겨져 다음
                    # 회차에 같은 발췌를 다시 읽는 것뿐이고(재발굴은 dedup 컨텍스트가
                    # 흡수), job 을 큐에 남기면(=ack 안 하면) 디스크가 고쳐지기 전까지
                    # 매 회차 이 프로젝트만 계속 실패해 더 나쁘다.
                    log(f"{proj}: mined ledger 저장 실패(무시, 다음 회차 재발굴) — {exc2}")
        except (AgentRuntimeError, ValueError, json.JSONDecodeError, RuntimeError,
                requests.RequestException) as exc:
            # 이 프로젝트만 격리해서 실패시킨다 — 네트워크 순간 장애 하나가 같은 run()
            # 안의 다른 프로젝트 처리까지 끌고 내려가면 안 된다(flusher.py 와 동일 규율).
            log(f"consolidation 실패({proj}) — Draft 보존, 다음 회차에 재시도: {exc}")
            errors.append(f"{proj}: {exc}")
            continue
        _ack_jobs(proj_jobs, sessions)
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
