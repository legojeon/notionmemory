"""쓰기 라우팅 — 어디에 쓸지 **고른다**. 쓰지는 않는다.

조회는 여러 소스를 합칠 수 있지만(스펙 §7) 쓰기는 두 군데 다 쓸 수 없으므로 하나를
골라야 한다. 그래서 조회 규칙과 별개의 규칙이 필요하다.

**이 모듈은 표지판이지 어댑터가 아니다.** `write_target` 이 템플릿을 가리키면 calendar
스킬은 거부하고 `templates add` 명령 문자열을 돌려줄 뿐, 남의 DB 에 쓰지도 속성을
매핑하지도 않는다. 매핑을 들이는 순간 스펙 §12 가 배제한 `backend: {template, db, map}`
어댑터가 된다 — `map` 이 그 경계의 결정적 표지다.
"""
from __future__ import annotations

BUILTIN = "calendar"
PREFIX = "template:"
OPTION = "write_target"
# 캘린더성 쓰기와 겹치는지의 기계 1차 필터. 의미 매칭(summary)은 에이전트 몫이다(스펙 §3).
CAPABILITY = "date"


class WriteBlocked(RuntimeError):
    """대상이 템플릿이다. calendar 는 쓰지 않고 갈 곳만 알려준다."""

    def __init__(self, message: str, command: str):
        super().__init__(message)
        self.command = command


class AmbiguousWrite(RuntimeError):
    """어디에 쓸지 정해지지 않았고 겹치는 템플릿이 있다. 에이전트가 사용자에게 되묻는다."""

    def __init__(self, message: str, candidates: list):
        super().__init__(message)
        self.candidates = candidates


def parse_target(value: str) -> tuple | None:
    """`template:<slug>/<db-key>` → `(slug, db_key)`. 내장·미결정이면 None."""
    text = (value or "").strip()
    if not text.startswith(PREFIX):
        return None
    body = text[len(PREFIX):]
    slug, _, db_key = body.partition("/")
    return (slug.strip(), db_key.strip()) if slug.strip() and db_key.strip() else ("", "")


def validate_target(value: str) -> str:
    """저장 전 검증. 존재만 본다 — 속성은 보지 않는다(그건 어댑터의 일이다)."""
    from notionmemory.skills.templates import profile
    text = (value or "").strip()
    if text in ("", BUILTIN):
        return text
    if not text.startswith(PREFIX):
        raise ValueError(
            f"쓰기 대상 형식이 아닙니다: {value!r} — "
            f"빈 값(미결정) / `{BUILTIN}`(내장) / `template:<slug>/<db-key>` 중 하나")
    parsed = parse_target(text)
    if parsed == ("", ""):
        raise ValueError(
            f"템플릿 대상은 데이터베이스까지 지정해야 합니다: {value!r} — "
            "`template:<slug>/<db-key>` 형식으로 쓰세요 "
            "(한 템플릿에 날짜 DB 가 둘일 수 있어 slug 만으로는 정할 수 없습니다)")
    slug, db_key = parsed
    p = profile.load(slug)                      # 없으면 등록 목록과 함께 ValueError
    profile.find_db(p, db_key)                  # 없으면 사용 가능한 key 와 함께 ValueError
    return f"{PREFIX}{slug}/{db_key}"


def overlapping(profiles: list, capability: str = CAPABILITY) -> list:
    """캘린더성 쓰기와 겹칠 수 있는 등록 템플릿."""
    from notionmemory.skills.templates.profile import VISIBLE_HEALTH
    return [p for p in profiles
            if p.enabled and p.health in VISIBLE_HEALTH and capability in (p.capabilities or [])]


def blocked(slug: str, db_key: str, title: str, start: str) -> WriteBlocked:
    """거부 + 갈 곳. 우리 속성 이름(Title/Date)을 남의 DB 에 들이밀지 않는다 —
    실제 속성 이름은 `templates show` 가 알려주고 그것을 읽는 것은 에이전트의 몫이다."""
    command = (f"notionmemory templates add {slug} {db_key} "
               f"--set \"<제목속성>={title}\" --set \"<날짜속성>={start}\"")
    return WriteBlocked(
        f"calendar 의 쓰기 대상이 '{PREFIX}{slug}/{db_key}' 로 지정돼 있습니다. "
        f"calendar 는 다른 템플릿의 데이터베이스에 쓰지 않습니다 — "
        f"`notionmemory templates show {slug}` 로 속성 이름을 확인한 뒤 아래를 실행하세요:\n"
        f"  {command}\n"
        f"(내장 Calendar DB 로 되돌리려면 `notionmemory calendar target calendar`)",
        command)


def ambiguous(candidates: list) -> AmbiguousWrite:
    lines = "\n".join(
        f"  {i}. {p.slug} — {p.summary or p.name}" for i, p in enumerate(candidates, 2))
    return AmbiguousWrite(
        "어디에 추가할지 정해지지 않았습니다. 사용자에게 물어보세요:\n"
        "  1. Calendar DB (내장)\n" + lines + "\n"
        "→ 이번만: 1번이면 `--here` 를 붙여 다시 실행, 템플릿이면 "
        "`notionmemory templates add <slug> <db-key> --set ...`\n"
        "→ 앞으로 계속: `notionmemory calendar target calendar` 또는 "
        "`notionmemory calendar target template:<slug>/<db-key>`",
        [{"slug": p.slug, "summary": p.summary or p.name,
          "databases": [db["key"] for db in p.databases]} for p in candidates])
