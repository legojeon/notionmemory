"""Notion rich_text 길이 방어 — **한도는 UTF-16 코드유닛 기준이다.**

Notion 의 "2000자" 한계는 파이썬 len()(코드포인트)이 아니라 UTF-16 코드유닛으로
센다: 이모지 등 astral 문자(U+10000 이상)는 2로 계산된다. `text[:2000]` 슬라이스는
이모지가 섞이면 2000을 넘겨 400 을 낸다(LongMemEval 벤치마크 실측: 2000 코드포인트
슬라이스가 "instead was 2003"). 각 스킬의 rt 헬퍼가 이 계산을 제각각 들고 있으면
반드시 어긋나므로, UTF-16 인지 캡은 여기 한 곳에만 둔다.
"""
from __future__ import annotations

NOTION_RICH_TEXT_LIMIT = 2000


def utf16_len(text: str) -> int:
    return sum(2 if ord(ch) > 0xFFFF else 1 for ch in text or "")


def utf16_cap(text: str, limit: int = NOTION_RICH_TEXT_LIMIT) -> str:
    """UTF-16 코드유닛 기준 limit 이하가 되도록 뒤를 자른다(서로게이트 쌍 절단 없음)."""
    t = text or ""
    units = 0
    for i, ch in enumerate(t):
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > limit:
            return t[:i]
    return t


def utf16_chunks(text: str, limit: int = NOTION_RICH_TEXT_LIMIT) -> list[str]:
    """limit 유닛 이하 조각들로 분할 — 긴 단일 행을 블록 여러 개로 나눌 때."""
    t = text or ""
    out: list[str] = []
    while t:
        head = utf16_cap(t, limit)
        if not head:            # limit < 2 에서 astral 문자 하나도 못 담는 극단 방어
            break
        out.append(head)
        t = t[len(head):]
    return out
