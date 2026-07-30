"""library 색인 — 공유된 Notion 페이지의 얇은 파생 힌트.

페이지당 **제목 + 헤딩만** 담는다. 본문 내용은 캐싱하지 않는다 — 색인은 "어디를 볼지"
가리키는 순수 포인터이고, 실제 내용은 항상 라이브로 읽는다(스펙 §3). 그래서 낡은 색인은
틀린 답이 아니라 최근-회수 누락만 낳는다.

`state_dir()` 아래라 teardown 이 통째로 지운다(위치 제약이 곧 설치물 계약).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from notionmemory.core import paths


def index_path() -> Path:
    return paths.state_dir() / "library" / "index.json"


def load() -> dict:
    p = index_path()
    if not p.is_file():
        return {"last_refreshed": "", "last_run": "", "last_full_run": "",
                "dirty_since_full": False, "pages": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {"last_refreshed": "", "last_run": "", "last_full_run": "",
                "dirty_since_full": False, "pages": {}}
    data.setdefault("last_refreshed", "")
    data.setdefault("last_run", "")
    data.setdefault("last_full_run", "")     # 벽시계: 마지막 `--full`(prune) 시각
    data.setdefault("dirty_since_full", False)  # 라이브 404 지연삭제가 관측한 드리프트
    data.setdefault("pages", {})
    return data


def save(idx: dict) -> None:
    p = index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # 원자 교체 — 도중 끊기면 load() 가 파싱 실패를 삼켜 빈 색인으로 시작하고,
    # 사용자는 통째로 재스캔해야 한다(재구축 가능하지만 110초짜리 낭비).
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def upsert(idx: dict, page_id: str, *, title: str, headings: list,
           url: str, last_edited_time: str) -> None:
    idx["pages"][page_id] = {"title": title, "headings": list(headings),
                             "url": url, "last_edited_time": last_edited_time}


def remove(idx: dict, page_id: str) -> bool:
    return idx["pages"].pop(page_id, None) is not None


def mark_dirty(idx: dict) -> None:
    """라이브 404 지연삭제가 죽은 항목을 걷었을 때 부른다 — '마지막 full 이후 드리프트를
    관측함' 플래그. SessionStart 가 이걸 보고 floor 를 넘겼으면 `--full` 을 넛지한다.
    `--full` 이 돌면 crawl.refresh 가 도로 False 로 리셋한다."""
    idx["dirty_since_full"] = True


def tokenize(text: str) -> list[str]:
    # memory.tokenize 와 같은 규칙(대소문자·한글·숫자) — 스코어링 일관성. 한 줄이라
    # cross-skill import 대신 로컬 정의(프로젝트의 사소한 헬퍼 중복 규율).
    return [t for t in re.split(r"[^0-9a-z가-힣]+", (text or "").lower()) if t]


def _matches(token: str, text: str) -> bool:
    """ASCII 토큰은 단어 경계로, 한글 등 비ASCII 토큰은 부분 매칭으로 판정한다.

    ASCII 에 부분 매칭을 쓰면 짧은 토큰이 긴 단어 안에 걸려 오탐이 난다(실측:
    'ray'→'array', 'dark'→'darkfw'). 반대로 한글은 조사·어미가 공백 없이 붙어
    '쿠버네티스의' 안의 '쿠버네티스'를 잡아야 하므로 경계 매칭을 쓰면 회수가 깎인다.
    그래서 문자 체계에 따라 규칙을 가른다."""
    if token.isascii():
        return re.search(rf"\b{re.escape(token)}\b", text) is not None
    return token in text


def _score(tokens: list, title: str, headings: list) -> int:
    title_l = title.lower()
    head_l = " ".join(headings).lower()
    score = 0
    for t in tokens:
        if _matches(t, title_l):
            score += 3          # 제목 매칭이 헤딩보다 무겁다
        if _matches(t, head_l):
            score += 1
    return score


def search(idx: dict, query: str, *, limit: int = 25) -> list[dict]:
    """제목·헤딩 어휘 스코어링 → 랭킹된 포인터. 무매칭=무결과(fallback 없음 —
    content 검색은 '없으면 없는' 것이다; 최근 폴백은 memory 의 몫)."""
    tokens = tokenize(query)
    hits = []
    for page_id, e in idx.get("pages", {}).items():
        s = _score(tokens, e.get("title", ""), e.get("headings") or [])
        if s > 0:
            hits.append({"page_id": page_id, "title": e.get("title", ""),
                         "headings": e.get("headings") or [], "url": e.get("url", ""),
                         "score": s})
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:limit]


def count(idx: dict) -> int:
    return len(idx.get("pages", {}))


def watermark(idx: dict) -> str:
    return idx.get("last_refreshed", "")


def was_refreshed(idx: dict) -> bool:
    """한 번이라도 refresh 가 완료된 적 있는가.

    `count==0` 만으로는 '아직 한 번도 색인 안 함'과 '색인했는데 공유 페이지가 진짜 0개'를
    구분할 수 없다(watermark 는 페이지 최신 편집시각이라 빈 워크스페이스에선 ""). 그래서
    refresh 완료 때마다 찍는 벽시계 마커(`last_run`)로 판정한다 — 빈 워크스페이스 사용자가
    매 세션 'refresh 필요' 넛지를 영원히 받는 것을 막는다. 페이지가 있으면 두말할 것 없이
    한 번은 돌았으므로(구버전 색인엔 last_run 이 없을 수 있어 하위호환도 겸함) 그것도 인정한다."""
    return bool(idx.get("last_run") or idx.get("pages"))
