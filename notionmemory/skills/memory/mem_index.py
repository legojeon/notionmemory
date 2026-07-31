"""memory 로컬 색인(v2) — Notion 없이 메시지당(per-message) 회수하기 위한 온디스크 인덱스.

library.index 와 같은 패턴(state_dir() 아래 index.json, load/save)이지만 내용은
memory 전용이다.

v2 포맷은 페이지 포인터가 아니라 전체 content(문서당 8000자 상한)와 필드 가중
BM25 통계(문서별 tf, 전역 df, avgdl)를 미리 계산해 저장한다 — 매 검색마다
lexical 스코어를 다시 훑던 v1 과 달리 `search`는 저장된 tf/df/avgdl 로 BM25 를
계산만 한다. 랭킹은 BM25 × Strength 부스트.

한글 토큰(조사·어미가 공백 없이 붙는 언어 특성)은 정확 tf 키 매칭이 실패할 수
있어 부분문자열 매칭 폴백(`_match_tf`)을 둔다 — ASCII 는 오탐(ray→array) 방지를
위해 폴백하지 않는다(단어경계 tokenize 로 이미 분리됨).

레거시 v1(평면 `{mem_id: entry}`) 색인도 `count`/`docs`/`search` 로 계속 동작한다
— `docs()`가 포맷을 감지해 그대로 반환하고, `search()`는 BM25 통계(meta)가 없으면
기존 `store.score_page` lexical 스코어로 즉석 폴백한다. 이행 유예: reindex 가 돌기
전까지 기존 색인이 깨지지 않는다.

Type=="brief" 는 build() 에서부터 걸러 색인에 절대 들어오지 않는다 — 브리프는
세션-시작 헤더 전용(project_brief)이고 메시지당 검색 결과로 새면 안 된다
(store.build_filter 의 Type != brief 규율과 동일).
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

from notionmemory.core import paths
from notionmemory.skills.memory.store import score_page, tokenize

_CONTENT_MAX = 8000        # 문서당 저장 상한(가드레일) — Excerpt 창(≈6000)보다 넉넉히
_TITLE_W, _CONCEPT_W = 3, 2
K1, B = 1.5, 0.75


def index_path() -> Path:
    return paths.state_dir() / "memory" / "index.json"


def _doc_tf(title: str, concepts: list, content: str) -> tuple[dict, int]:
    """필드 가중을 tf 에 접는다: 제목 ×3, concepts ×2, 본문 ×1. dl = 가중 토큰 수."""
    tf: dict = {}
    for text, w in ((title, _TITLE_W), (" ".join(concepts), _CONCEPT_W), (content, 1)):
        for t in tokenize(text):
            tf[t] = tf.get(t, 0) + w
    return tf, sum(tf.values())


def build(memories: list) -> dict:
    """메모리 목록 → v2 색인(전체 content + BM25 통계). Type=="brief" 는 제외."""
    docs: dict = {}
    df: dict = {}
    for m in memories:
        if m.get("type") == "brief" or not m.get("id"):
            continue
        content = (m.get("content") or "")[:_CONTENT_MAX]
        tf, dl = _doc_tf(m.get("title", ""), list(m.get("concepts") or []), content)
        docs[m["id"]] = {"title": m.get("title", ""),
                         "concepts": list(m.get("concepts") or []),
                         "content": content, "strength": m.get("strength", 0),
                         "type": m.get("type", ""), "project": m.get("project", ""),
                         "status": m.get("status", ""),
                         "last_edited": m.get("last_edited", ""),
                         "tf": tf, "dl": dl}
        for t in tf:
            df[t] = df.get(t, 0) + 1
    n = len(docs)
    avgdl = (sum(d["dl"] for d in docs.values()) / n) if n else 0.0
    return {"version": 2, "meta": {"n": n, "avgdl": avgdl, "df": df}, "docs": docs}


def docs(idx: dict) -> dict:
    if idx.get("version") == 2:
        return idx.get("docs") or {}
    if "version" in idx:
        return {}                        # 미래/알 수 없는 버전(예: 3) — v1 평면으로 오인해
                                          # meta/docs 같은 키를 mem_id 로 잘못 읽으면 안 된다
    return idx or {}                     # 레거시 v1(평면) — 항목 dict 그대로


def count(idx: dict) -> int:
    return len(docs(idx))


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
    # 원자 교체 — library index.save 와 같은 규율(잘린 JSON 은 조용히 빈 색인이 된다).
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _v1_entry_to_memory(mem_id: str, entry: dict) -> dict:
    """색인 엔트리 → build() 가 기대하는 메모리 dict. 레거시 v1 평면 엔트리(content
    대신 excerpt 필드)와 v2 doc(content 필드 — 중복-id 재빌드 경로가 넘긴다) 둘 다
    받는다: content 우선, 없으면 excerpt. last_edited 는 v1 에 없었으니 빈 문자열."""
    return {"id": mem_id, "title": entry.get("title", ""),
            "concepts": list(entry.get("concepts") or []),
            "content": entry.get("content") or entry.get("excerpt", ""),
            "strength": entry.get("strength", 0), "type": entry.get("type", ""),
            "project": entry.get("project", ""), "status": entry.get("status", ""),
            "last_edited": entry.get("last_edited", "")}


def add_memory(memory: dict) -> None:
    """remember() 직후 write-through — 다음 전체 reindex 를 기다리지 않고 방금 저장한
    메모리를 색인에 바로 반영한다(fix round C1: 그전까지는 remember 가 색인을 전혀
    건드리지 않아, 색인이 이기는 recall 의 로컬 랭킹 경로가 방금 저장한 메모리를 못 보고
    stale 한 답을 자신 있게(fallback=False) 돌려주는 사고가 있었다).

    v2 색인이면 tf/df/avgdl 을 증분 갱신한다(build() 을 통째로 다시 돌리지 않는다).

    **채워진** 레거시 v1(평면) 이면 통째로 버리고 이 메모리 하나만 담은 색인으로 바꿔치기
    하면 안 된다 — v1→v2 로 넘어가는 모든 기존 사용자가 업그레이드 후 첫 remember 에서
    겪는 경로라, 그 순간 로컬 커버리지가 이 메모리 하나로 뭉개져 다음 reindex 전까지
    나머지 기존 메모리가 로컬 경로에서 안 보이는 사고가 난다(fix round: C1 과 같은 부류의
    "조용한 stale" — 대상만 v1 색인 자체로 바뀌었을 뿐). 기존 v1 항목들을 변환해 새
    메모리와 함께 build() 로 한 번에 v2 로 다시 만든다 — meta 를 손으로 유지하는 것보다
    안전하다(build() 가 이미 전체 리스트에 대한 meta 를 정확히 계산한다).

    색인이 아직 없거나(첫 설치) 비어있는 v1, 또는 미래/알 수 없는 버전(예: version=3,
    안전하게 해석할 수 없다 — docs() 의 미지원 버전 규율과 동일)이면 이 메모리 하나만
    담은 새 v2 색인을 만든다.

    Type=="brief" 나 id 없는 메모리는 build() 과 같은 규율로 조용히 스킵한다(브리프는
    세션-시작 헤더 전용이라 색인에 절대 들어오면 안 된다)."""
    if memory.get("type") == "brief" or not memory.get("id"):
        return
    idx = load()
    if idx.get("version") == 2:
        if memory["id"] in (idx.get("docs") or {}):
            # 같은 mem_id 재-add 는 증분 경로에서 meta(n/df/avgdl)를 이중 계산한다
            # (재리뷰 N1 — 오늘의 유일한 호출자 remember() 는 항상 새 id 를 만들지만,
            # 미래의 제자리-갱신 호출자를 위한 지뢰 제거). 전체 재빌드로 정확히 처리.
            docs_now = docs(idx)
            docs_now.pop(memory["id"], None)
            converted = [_v1_entry_to_memory(mid, e) for mid, e in docs_now.items()]
            save(build(converted + [memory]))
            return
        title = memory.get("title", "")
        concepts = list(memory.get("concepts") or [])
        content = (memory.get("content") or "")[:_CONTENT_MAX]
        tf, dl = _doc_tf(title, concepts, content)
        idx.setdefault("docs", {})[memory["id"]] = {
            "title": title, "concepts": concepts, "content": content,
            "strength": memory.get("strength", 0), "type": memory.get("type", ""),
            "project": memory.get("project", ""), "status": memory.get("status", ""),
            "last_edited": memory.get("last_edited", ""), "tf": tf, "dl": dl}
        meta = idx.setdefault("meta", {"n": 0, "avgdl": 0.0, "df": {}})
        n = meta.get("n", 0) + 1
        meta["avgdl"] = ((meta.get("avgdl", 0.0) * (n - 1)) + dl) / n
        meta["n"] = n
        df = meta.setdefault("df", {})
        for t in tf:
            df[t] = df.get(t, 0) + 1
        save(idx)
        return
    if "version" not in idx and idx:                 # 채워진 레거시 v1 — 변환해서 합친다
        converted = [_v1_entry_to_memory(mid, e) for mid, e in idx.items()]
        save(build(converted + [memory]))
        return
    save(build([memory]))                             # 부재/빈/미지원 버전 — 새 메모리만


def _match_tf(token: str, tf: dict, df: dict) -> tuple[int, int]:
    """토큰의 (tf, df). 정확 키 우선; 비ASCII(한글) 토큰은 조사 흡수를 위해 키
    부분문자열 매칭 폴백 — df 는 매칭 키 중 최대(보수적으로 낮은 idf)를 쓴다."""
    if token in tf:
        return tf[token], df.get(token, 1)
    if not token.isascii():
        keys = [k for k in tf if token in k]
        if keys:
            return sum(tf[k] for k in keys), max(df.get(k, 1) for k in keys)
    return 0, 1


def search(idx: dict, query: str, *, project: str = "", mem_type: str = "", limit: int = 3,
           min_score: float = 1.0) -> list:
    """BM25(필드 가중 tf/df/avgdl 사전계산) × Strength 가중 → gate → top-N.

    v2 색인은 저장된 통계로 BM25 를 계산한다. meta 가 없는 레거시 v1 색인은
    `store.score_page` lexical 스코어로 즉석 폴백한다(느리지만 정확 — reindex
    전까지 검색이 깨지지 않는다).

    랭킹 키 = (score, strength) desc — score 가 1차(관련성), 동점일 때만 Strength 로
    깨진다. min_score 가 관련성 게이트: 이 아래는 아예 반환하지 않는다(메시지당
    주입이 조용해지는 핵심 장치 — 무관한 메모리가 새어들지 않게 한다)."""
    tokens = tokenize(query)
    d = docs(idx)
    meta = idx.get("meta") if idx.get("version") == 2 else None
    hits = []
    for mem_id, e in d.items():
        if e.get("type") == "brief" or e.get("status") not in ("Active", "Draft"):
            continue
        if project and e.get("project") not in ("", project):
            continue
        if mem_type and e.get("type") != mem_type:
            continue
        if meta:
            tf = e.get("tf") or {}
            n, avgdl = meta["n"], meta["avgdl"] or 1.0
            s = 0.0
            for t in tokens:
                f, dfr = _match_tf(t, tf, meta["df"])
                if not f:
                    continue
                idf = math.log(1 + (n - dfr + 0.5) / (dfr + 0.5))
                s += idf * f * (K1 + 1) / (f + K1 * (1 - B + B * e.get("dl", 0) / avgdl))
        else:
            # 레거시 v1 폴백 — 기존 lexical 스코어 그대로(느리지만 정확), reindex 유도는
            # 기존 빈-색인/reindex 넛지가 담당(새 문구 없음).
            s = float(score_page(tokens, title=e.get("title", ""),
                                 concepts=e.get("concepts") or [],
                                 excerpt=e.get("excerpt", e.get("content", ""))))
        s *= (1 + e.get("strength", 0) / 20)
        if s < min_score:
            continue
        hits.append((s, e.get("strength", 0), mem_id, e))
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    return [{"mem_id": mem_id, "title": e.get("title", ""),
             "strength": e.get("strength", 0), "concepts": e.get("concepts") or [],
             "excerpt": (e.get("content") or e.get("excerpt", ""))[:200],
             "type": e.get("type", ""), "project": e.get("project", ""),
             "status": e.get("status", ""), "score": s}
            for s, _, mem_id, e in hits[:limit]]
