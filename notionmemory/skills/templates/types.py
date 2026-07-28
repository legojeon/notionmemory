"""Notion 속성 타입 23종 — 닫힌 집합.

Notion 에는 사용자 정의 속성 타입이 없다. 템플릿 제작자도 UI 가 주는 것만 고를 수
있으므로 어떤 템플릿이든 이 표를 벗어나지 않는다 — 이 스킬이 성립하는 유일한 근거다.

`writable` 과 `filterable` 은 별개 축이다. formula/rollup/created_time 은 쓰기 불가지만
필터 가능하고, 그것들이야말로 사용자가 가장 자주 묻는 대상이다("30일 넘게 열린 것").
한 필드로 접으면 그 질문이 통째로 막힌다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PropType:
    writable: bool
    filterable: bool
    capability: str = ""      # "date" | "text" | "people" | "link" | ""


def _w(capability: str = "") -> PropType:
    return PropType(True, True, capability)


def _ro(capability: str = "", *, filterable: bool = True) -> PropType:
    return PropType(False, filterable, capability)


PROP_TYPES: dict[str, PropType] = {
    # 쓰기 가능 14
    "title": _w("text"),
    "rich_text": _w("text"),
    "number": _w(),
    "checkbox": _w(),
    "url": _w("link"),
    "email": _w(),
    "phone_number": _w(),
    "date": _w("date"),
    "select": _w(),
    "multi_select": _w(),
    "status": _w(),
    "people": _w("people"),
    "files": _w("link"),
    "relation": _w(),
    # 읽기 전용 9
    "formula": _ro(),
    "rollup": _ro(),
    "created_time": _ro("date"),
    "created_by": _ro("people"),
    "last_edited_time": _ro("date"),
    "last_edited_by": _ro("people"),
    "unique_id": _ro(),
    # button 은 필터 조건 자체가 없고, verification 은 위키 전용이라 일반 템플릿에서
    # 안전히 다룰 수 없다 — 보수적으로 둘 다 불가로 둔다. 거부는 명확한 메시지를 낳지만
    # 잘못 통과시키면 400 이 조회 경로에서 튄다.
    "button": _ro(filterable=False),
    "verification": _ro(filterable=False),
}

UNKNOWN = PropType(False, False, "")

WRITABLE = frozenset(k for k, v in PROP_TYPES.items() if v.writable)
FILTERABLE = frozenset(k for k, v in PROP_TYPES.items() if v.filterable)


def flags(notion_type: str) -> PropType:
    """미지 타입은 읽기 전용 + 필터 불가로 강등한다 — Notion 이 새 타입을 추가해도
    쓰거나 필터하다 깨지는 대신 명확히 거부된다."""
    return PROP_TYPES.get(notion_type or "", UNKNOWN)


def derive_capabilities(databases: list[dict]) -> list[str]:
    """하위 DB 전체 속성 타입의 합집합 → 라우팅용 capability 목록(정렬).

    `summary` 가 의미 매칭을 맡는다면 이쪽은 기계적 1차 필터다 — 날짜 질문에 `date`
    가 없는 템플릿은 후보에서 아예 빠진다(스펙 §3).
    """
    found = set()
    for db in databases or []:
        for prop in db.get("properties") or []:
            cap = flags(prop.get("type", "")).capability
            if cap:
                found.add(cap)
    return sorted(found)
