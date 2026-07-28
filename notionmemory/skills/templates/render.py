"""조회 출력 — 평탄화. Notion 원본 JSON 을 그대로 내보내지 않는다.

한 행이 수십 줄로 부풀고 대부분이 잡음이다. 그리고 **row id 는 절대 생략하지 않는다** —
이어지는 update/archive 가 그것을 요구하므로, 빠지면 사용자에게 "다시 조회"를 시킨다.

`plain()` 은 Notion 의 23종 속성 타입 전부에 대해 total 이어야 한다 — 미지 타입(장래
Notion 이 추가할 타입 포함)도 반드시 문자열을 내고 JSON 조각이나 repr 을 흘리지 않는다.
각 타입의 값 모양은 Notion 공식 문서(property value object,
https://developers.notion.com/reference/property-value-object)를 근거로 한다 —
가정으로 채우면 형태가 틀려도 조용히 빈 칸이 나가 실제 데이터가 있어도 안 보이게 된다.
"""
from __future__ import annotations

import json
import unicodedata

_JOIN = ", "
_RESERVED_ROW_KEYS = ("id", "url")


def _names(items) -> str:
    # 실제 Notion 응답은 이 모양을 안 보내지만(항상 dict 원소), plain() 은 23종
    # 전부에 대해 total 이어야 한다 — dict 가 아닌 원소를 만나도 죽지 않고 건너뛴다.
    return _JOIN.join(
        str(i.get("name") or i.get("id") or "") for i in (items or []) if isinstance(i, dict)
    )


def _display_width(s: str) -> int:
    """터미널 표시 폭. 동아시아 폭 W/F 는 2 칸 — len() 은 코드포인트를 세므로
    한글/한자/가나 컬럼이 ljust 로는 좁게 잡혀 정렬이 깨진다."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _display_width(s))


def plain(prop: dict) -> str:
    """Notion 속성 값 → 한 줄 문자열. 모르는 타입도 JSON 을 토하지 않는다."""
    ptype = (prop or {}).get("type", "")
    value = (prop or {}).get(ptype)
    if value is None or value == [] or value == {}:
        return ""
    if ptype in ("title", "rich_text"):
        return "".join(i.get("plain_text", "") for i in value if isinstance(i, dict))
    if ptype in ("url", "email", "phone_number", "created_time", "last_edited_time",
                 "string"):
        # "string" 은 최상위 속성 타입이 아니라 formula 결과의 내부 종류다 — formula/
        # rollup 재귀 분기에서만 도달한다.
        return str(value)
    if ptype == "number":
        return str(int(value)) if float(value).is_integer() else str(value)
    if ptype in ("checkbox", "boolean"):
        # "boolean" 도 마찬가지로 formula 결과 내부 종류(checkbox 자체는 항상
        # "checkbox" 로 온다) — 없으면 formula 의 true/false 결과가 조용히 빈 칸이 된다.
        return "true" if value else "false"
    if ptype == "date":
        start, end = value.get("start") or "", value.get("end") or ""
        return f"{start}..{end}" if end else start
    if ptype in ("select", "status"):
        return str(value.get("name") or "")
    if ptype in ("multi_select", "people", "files"):
        return _names(value)
    if ptype == "relation":
        return _JOIN.join(i.get("id", "") for i in value if isinstance(i, dict))
    if ptype in ("created_by", "last_edited_by"):
        return str(value.get("name") or value.get("id") or "")
    if ptype == "array":
        # rollup 의 내부 종류 "array" — 각 원소가 이미 이 함수와 같은 모양의 속성 값
        # 객체다(예: [{"type": "number", "number": 5}, ...]). 재귀로 펼쳐서 이어붙인다 —
        # 안 하면 집계 목록이 통째로 빈 칸이 된다.
        return _JOIN.join(s for s in (plain(item) for item in value) if s)
    if ptype in ("formula", "rollup"):
        inner = value.get("type", "")
        return plain({"type": inner, inner: value.get(inner)}) if inner else ""
    if ptype == "unique_id":
        prefix, num = value.get("prefix") or "", value.get("number")
        if num is None:
            return ""
        return f"{prefix}-{num}" if prefix else str(num)
    if ptype == "verification":
        return str(value.get("state") or "")
    return ""       # button 및 미지 타입 — 표시할 것이 없다


def flatten(page: dict, names: list) -> dict:
    """Notion page → 평탄화된 한 행. `row["id"]`/`row["url"]` 은 항상 page 자신의
    값이다 — 절대 조건 없이. 대상 DB는 사용자가 임의로 만든 임의의 속성 스키마라
    "id"/"url" 이라는 이름의 사용자 컬럼(자기 트래킹 번호 등)이 얼마든지 있을 수
    있는데, 그걸 그대로 같은 키에 쓰면 real page id 가 조용히 사용자 값으로
    덮여써진다 — 이어지는 update/archive 가 근거 없는 id 를 조용히 때리는 사고로
    이어진다(이 모듈에서 유일하게 절대적인 규칙 위반). 그런 이름이 요청되면 값을
    버리지 않고 "<name> (property)" 키로 옮겨 보존한다 — 조용히 버리는 것도
    조용한 거짓말이다.
    """
    props = page.get("properties") or {}
    row = {}
    for name in names:
        key = f"{name} (property)" if name in _RESERVED_ROW_KEYS else name
        row[key] = plain(props.get(name) or {})
    row["id"] = page.get("id", "")
    row["url"] = page.get("url", "")
    return row


def render_rows(rows: list, fields: list) -> str:
    if not rows:
        return "(결과 없음)"
    cols = ["id"] + [f for f in fields if f != "id"]
    widths = {c: max(_display_width(c), *(_display_width(str(r.get(c, ""))) for r in rows))
              for c in cols}
    lines = ["  ".join(_pad(c, widths[c]) for c in cols)]
    for r in rows:
        lines.append("  ".join(_pad(str(r.get(c, "")), widths[c]) for c in cols))
    return "\n".join(lines)


def render_json(rows: list) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=2)


def truncation_note(*, capped: bool, cap: int, sorted_: bool, stalled: bool = False) -> str:
    """조용한 절단은 '그게 전부'라는 거짓말이 된다 — 잘렸으면 반드시 말한다.

    `capped`(안전 상한 도달)와 `stalled`(Notion 응답이 진행 불가여서 상한 이전에
    멈춤)는 다른 문제라 다른 말을 한다 — 둘 다 뭉뚱그려 "cap 에서 잘림, 조건을
    좁히세요"라고 하면, 정체 상황에도 사용자에게 존재하지도 않는 "조건" 탓을
    시키는 확신에 찬 거짓말이 된다(리뷰 지적). `stalled` 는 `capped` 보다 먼저
    검사한다 — 진짜 원인은 정체이지 상한이 아니기 때문이다.
    """
    if stalled:
        return ("(응답이 불완전합니다 — Notion 이 다음 페이지를 주지 못했습니다. "
                 "이 결과가 전체가 아닐 수 있습니다)")
    if not capped:
        return ""
    note = f"({cap}건에서 잘림 — 조건을 좁히세요"
    if not sorted_:
        note += ", 정렬 미지정이라 임의 순서"
    return note + ")"
