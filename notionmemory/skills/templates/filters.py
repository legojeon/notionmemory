"""조회 표면 — `--where`/`--search`/`--sort` → Notion query 페이로드.

동등 비교만으로는 범용 조회가 되지 않는다. 판정은 `filterable` 로 한다 — formula/rollup 은
쓰기 불가지만 필터 가능하고 그것들이 가장 자주 묻는 대상이다(스펙 §3).

Notion 의 상대 날짜 sugar(this_week/past_month)는 **의도적으로 쓰지 않는다.** 주 시작
요일과 UTC 기준이 로컬 타임존과 어긋난다 — 이 리포는 calendar 에서 그 함정을 밟고
고쳤다(c346fa8). 에이전트가 절대 날짜를 계산해 >=/<= 로 넘긴다.

연산자×타입 표는 Notion 공식 문서(data source query filter object,
https://developers.notion.com/reference/post-database-query-filter)를 근거로 한다 —
타입별 근거는 각 타입 그룹 주석에 남긴다.
"""
from __future__ import annotations

import re
from typing import Callable

from notionmemory.skills.templates import coerce, types
from notionmemory.skills.templates.profile import find_prop

OPERATORS = ("=", "!=", ">", "<", ">=", "<=", "contains", "!contains",
             "starts", "ends", "in", "empty", "!empty")
NO_VALUE_OPS = ("empty", "!empty")
TEXT_TYPES = ("title", "rich_text", "url", "email", "phone_number")
# select/status/multi_select 만 `in` 을 받는다 — OR 의 유일한 표면이고, 자유 입력
# 타입에 열어주면 임의 boolean 표현식으로 미끄러진다(스펙 §6 비범위).
IN_TYPES = ("select", "status", "multi_select")
# contains/does_not_contain 을 받는 타입 — people 계열(사람 자체는 people, created_by/
# last_edited_by 는 그 파생)과 multi_select/relation, 그리고 텍스트 계열.
CONTAINS_TYPES = TEXT_TYPES + ("multi_select", "relation", "people",
                               "created_by", "last_edited_by")
ORDERED_TYPES = ("number", "date", "formula", "rollup", "created_time",
                 "last_edited_time", "unique_id")
# date 와 그 타임스탬프 파생(created_time/last_edited_time) — 셋 다 Notion 문서에서
# "A date filter condition" 하나를 공유한다(동일 조건 집합, equals 는 있고
# does_not_equal 은 없음).
DATE_TYPES = ("date", "created_time", "last_edited_time")
# 이 타입들은 Notion 에 bare `equals`/`does_not_equal` 조건이 아예 없다 — 전부 "포함/
# 존재" 계열 조건(contains/is_empty 등)만 받는다. relation·multi_select·people·files·
# created_by·last_edited_by. (rollup 은 여기 없다 — number 로 감싸면 equals 를
# 구성할 수 있다, `_wrap` 참고.)
NO_EQUALS_TYPES = ("relation", "multi_select", "people", "files",
                   "created_by", "last_edited_by")
# is_empty/is_not_empty 가 없는 타입. checkbox 는 non-nullable 이라 "비었다"는 개념이
# 없고, unique_id 는 Notion 문서에 empty 조건이 없다(equals/does_not_equal/부등호뿐).
NO_EMPTY_TYPES = ("checkbox", "unique_id")

_WORD_OPS = "|".join(re.escape(o) for o in
                     ("!contains", "contains", "starts", "ends", "!empty", "empty", "in"))
_WORD_RE = re.compile(rf"^(?P<p>.+?)\s+(?P<op>{_WORD_OPS})(?:\s+(?P<v>.*))?$")
_SYM_RE = re.compile(r"^(?P<p>.+?)\s*(?P<op>>=|<=|!=|=|>|<)\s*(?P<v>.*)$")

_ORDER_NUM = {">": "greater_than", "<": "less_than",
              ">=": "greater_than_or_equal_to", "<=": "less_than_or_equal_to"}
_ORDER_DATE = {">": "after", "<": "before", ">=": "on_or_after", "<=": "on_or_before"}


def parse_where(raw: str) -> tuple[str, str, str]:
    """`"Days Open>30"` → `("Days Open", ">", "30")`.

    단어 연산자를 먼저 본다 — 공백으로 구분된 토큰만 연산자로 인정하므로
    `Contains Notes contains x` 같은 이름도 갈라지지 않는다.
    """
    text = (raw or "").strip()
    m = _WORD_RE.match(text)
    if m:
        op, value = m.group("op"), (m.group("v") or "").strip()
        if op in NO_VALUE_OPS and value:
            raise ValueError(f"`{op}`는 값을 받지 않습니다: {raw!r}")
        return m.group("p").strip(), op, value
    m = _SYM_RE.match(text)
    if m:
        return m.group("p").strip(), m.group("op"), m.group("v").strip()
    raise ValueError(
        f"--where 에 연산자가 없습니다: {raw!r} (사용 가능: {', '.join(OPERATORS)})")


def parse_sort(raw: str) -> dict:
    """`"Applied On desc"` → `{"property": "Applied On", "direction": "descending"}`.

    방향 없이 속성 이름만 와도 된다("Applied On" 처럼 이름 자체에 공백이 흔하다) — 그래서
    끝 토큰이 asc/desc 가 아니라고 곧장 에러로 보지 않는다. 다만 토큰이 3개 이상인데
    끝 토큰이 방향이 아니면("Applied On sideways") 방향을 쓰려다 오타 낸 것으로 보고
    에러로 처리한다. 정확히 2 토큰(예: 이름 자체가 두 단어)까지는 그대로 이름으로 받는다 —
    이 스킬은 속성 목록을 모르는 순수 파서이므로(db 미주입) 실제 속성 존재 여부는
    이후 `_checked` 에서 가려낸다.
    """
    text = (raw or "").strip()
    words = text.split()
    if not words:
        raise ValueError(f"--sort 형식이 아닙니다: {raw!r} (\"속성 asc|desc\")")
    if len(words) >= 2 and words[-1].lower() in ("asc", "desc"):
        name, direction = " ".join(words[:-1]), words[-1].lower()
    elif len(words) <= 2:
        name, direction = text, "asc"
    else:
        # "Date of Application" 처럼 세 단어 이상인 속성 이름 자체는 정당하다 — 그러니
        # 단순히 "asc/desc 가 아니다"라고만 하면 사용자가 뭘 고쳐야 할지 모른다. 세 단어
        # 이상일 때는 방향을 반드시 끝에 명시해야 한다는 규칙 자체를 말해준다.
        raise ValueError(
            f"--sort 속성 이름이 세 단어 이상이면 방향(asc/desc)을 끝에 명시해야 합니다: "
            f"{raw!r} (예: \"{text} desc\")")
    if not name:
        raise ValueError(f"--sort 형식이 아닙니다: {raw!r} (\"속성 asc|desc\")")
    return {"property": name,
            "direction": "ascending" if direction == "asc" else "descending"}


def _checked(db: dict, name: str) -> dict:
    prop = find_prop(db, name)
    ptype = prop.get("type", "")
    if not types.flags(ptype).filterable or not prop.get("filterable", True):
        raise ValueError(f"`{name}`은 {ptype} 이라 조회 조건으로 쓸 수 없습니다")
    return prop


def _valid_ops(ptype: str) -> tuple[str, ...]:
    """이 타입에 실제로 쓸 수 있는 연산자 — 거부 메시지가 다음 시도를 알려주게 한다.

    호출부마다 서로 다른 '허용 타입' 목록을 손으로 들고 있으면(예: relation 거부에
    하드코딩된 튜플) 로직이 바뀔 때 메시지만 낡는다. 한 곳에서 실제 분기와 같은 기준으로
    계산해 항상 최신 상태를 보장한다. `_clause` 의 분기와 이 함수가 어긋나지 않는지는
    `test_valid_ops_matches_clause_dispatch_for_every_type` 이 타입×연산자 전수로 잠근다.
    """
    ops: list[str] = []
    if ptype not in NO_EQUALS_TYPES:
        ops.append("=")
        if ptype not in DATE_TYPES:
            ops.append("!=")
    if ptype in ORDERED_TYPES:
        ops += [">", "<", ">=", "<="]
    if ptype in CONTAINS_TYPES:
        ops += ["contains", "!contains"]
    if ptype in TEXT_TYPES:
        ops += ["starts", "ends"]
    if ptype in IN_TYPES:
        ops += ["in"]
    if ptype not in NO_EMPTY_TYPES:
        ops += list(NO_VALUE_OPS)
    return tuple(ops)


def _reject(name: str, ptype: str, op: str) -> None:
    raise ValueError(f"`{name}`({ptype})에는 `{op}`를 쓸 수 없습니다 — "
                     f"사용 가능한 연산자: {', '.join(_valid_ops(ptype))}")


def _need_value(name: str, op: str, value: str) -> None:
    if not value:
        raise ValueError(f"`{name} {op}` 에 값이 없습니다 — 비교할 값을 지정하세요")


def _scalar(name: str, ptype: str, value: str):
    if ptype == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"`{name}`은 숫자가 아닙니다: {value!r}")
    if ptype == "unique_id":
        # Notion 은 unique_id 비교에 정수를 요구한다 — 문자열/실수를 보내면 400.
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"`{name}`은 정수가 아닙니다: {value!r}")
    if ptype == "checkbox":
        return coerce.parse_bool(name, value)
    return value


def _date_value(name: str, value: str) -> str:
    """비교 연산자의 날짜 피연산자를 `coerce.parse_date` 로 검증·정규화한다.

    이걸 거치지 않으면 형식 오류가 로컬이 아니라 Notion 400 으로 터지고(에이전트가
    자가 수정할 수 없는 실패), 쓰기 경로(`--set`)와 다른 포맷(초 없는 bare date)이
    나가 조회·기록 두 경로가 서로 다른 표현을 쓰게 된다. `..` 범위는 비교 연산자
    (>,<,>=,<=,=)의 피연산자가 될 수 없다 — Notion 비교 조건은 스칼라 하나만 받는다.
    """
    if ".." in value:
        raise ValueError(
            f"`{name}` 비교에는 날짜 범위(A..B)를 쓸 수 없습니다 — "
            "--where 를 두 개로 나눠 쓰세요 (예: 시작 이후는 '>=', 끝 이전은 '<=')")
    return coerce.parse_date(value)["start"]


def _wrap(prop: dict, condition: dict) -> dict:
    """formula/rollup 은 조건을 한 겹 더 감싼다 — Notion 이 내부 결과 타입을 요구한다.

    formula 는 결과 타입을 프로필에 담지 않으므로 비교 연산자는 number, 그 외는 string 로
    추측한다. 틀리면 Notion 이 400 으로 알려주며, 추측을 프로필에 굳히지 않는 편이
    낫다(§1) — 이건 프로필로도 알 수 없는 정보라 남겨둔다.

    rollup 은 다르다: Notion 문서상 rollup 의 내부 키는 `any`/`every`/`none`/`date`/
    `number` 뿐이고 `string` 은 애초에 존재하지 않는다 — formula 처럼 "모르면 string"
    폴백을 할 수가 없다. 그래서 rollup 은 항상 number 로만 구성하고(집계 타입을 모르니
    number 라고 추측하는 것은 formula 와 같은 성격의 타협이다), `_valid_ops`/`_clause`
    가 애초에 number 로 구성 가능한 연산(동등·부등호 비교, 존재 여부)만 통과시킨다 —
    string 이 필요한 contains/starts/ends 는 CONTAINS_TYPES/TEXT_TYPES 에 rollup 을
    넣지 않는 것으로 이미 막혀 있다.
    """
    ptype = prop["type"]
    if ptype not in ("formula", "rollup"):
        return {"property": prop["name"], ptype: condition}
    if ptype == "rollup":
        inner = "number"
    else:
        inner = "number" if any(k in condition for k in _ORDER_NUM.values()) else "string"
    return {"property": prop["name"], ptype: {inner: condition}}


def _clause(db: dict, name: str, op: str, value: str, *,
            resolve_relation: Callable[[str, str], str]) -> dict:
    prop = _checked(db, name)
    ptype = prop["type"]

    if op in NO_VALUE_OPS:
        if ptype in NO_EMPTY_TYPES:
            _reject(name, ptype, op)
        return _wrap(prop, {"is_empty" if op == "empty" else "is_not_empty": True})

    if op == "in":
        if ptype not in IN_TYPES:
            _reject(name, ptype, op)
        items = [v.strip() for v in value.split(",") if v.strip()]
        if not items:
            raise ValueError(f"`{name} in` 에 값이 없습니다")
        # select/status/multi_select 는 허용 목록이 있다 — 오타 하나가 "0건" 을 조용히
        # 만드는 걸 막는다(coerce.py 의 쓰기 경로와 같은 검증·같은 메시지 재사용).
        items = [coerce.validate_choice(prop, v) for v in items]
        key = "contains" if ptype == "multi_select" else "equals"
        return {"or": [{"property": name, ptype: {key: item}} for item in items]}

    # 타입×연산자 유효성을 값 유무보다 먼저 가린다(리뷰 지적) — `Salary starts` 처럼 값도
    # 없고 연산자도 안 맞는 입력에서 "값이 없습니다" 먼저 던지면, 에이전트가 값을 채워
    # 다시 보내고서야 "그 타입엔 그 연산자를 못 쓴다"는 진짜 원인을 듣는다. 한 라운드
    # 트립으로 끝날 일이 둘이 된다. 이 아래 각 분기는 `_reject` 로 타입을 먼저 확정한
    # 뒤에만 `_need_value` 를 부른다.

    if op in ("contains", "!contains"):
        if ptype not in CONTAINS_TYPES:
            _reject(name, ptype, op)
        _need_value(name, op, value)
        needle = value
        if ptype == "relation":
            needle = resolve_relation(prop.get("relates_to") or "", value)
        elif ptype == "multi_select":
            needle = coerce.validate_choice(prop, value)
        key = "contains" if op == "contains" else "does_not_contain"
        return {"property": name, ptype: {key: needle}}

    if op in ("starts", "ends"):
        if ptype not in TEXT_TYPES:
            _reject(name, ptype, op)
        _need_value(name, op, value)
        key = "starts_with" if op == "starts" else "ends_with"
        return {"property": name, ptype: {key: value}}

    if op in _ORDER_NUM:
        if ptype not in ORDERED_TYPES:
            _reject(name, ptype, op)
        _need_value(name, op, value)
        if ptype in DATE_TYPES:
            return _wrap(prop, {_ORDER_DATE[op]: _date_value(name, value)})
        eff_type = "unique_id" if ptype == "unique_id" else "number"
        return _wrap(prop, {_ORDER_NUM[op]: _scalar(name, eff_type, value)})

    # `=` / `!=`
    key = "equals" if op == "=" else "does_not_equal"
    if ptype in NO_EQUALS_TYPES:
        _reject(name, ptype, op)
    if ptype in DATE_TYPES and op == "!=":
        # Notion date 필터에는 does_not_equal 이 없다(equals 는 있다) — 이 비대칭은
        # 실제 스키마 제약이지 우리 쪽 누락이 아니다. 값 유무를 따지기 전에 걸러야
        # `Applied On != ` 같은 입력에서 엉뚱한 "값이 없습니다"가 먼저 나가지 않는다.
        _reject(name, ptype, op)
    _need_value(name, op, value)
    if ptype in DATE_TYPES:
        return _wrap(prop, {key: _date_value(name, value)})
    if ptype in ("select", "status"):
        return _wrap(prop, {key: coerce.validate_choice(prop, value)})
    eff_type = "number" if ptype == "rollup" else ptype
    return _wrap(prop, {key: _scalar(name, eff_type, value)})


def build_where(db: dict, clauses, *,
                resolve_relation: Callable[[str, str], str]) -> dict | None:
    built = [_clause(db, n, o, v, resolve_relation=resolve_relation) for n, o, v in clauses]
    if not built:
        return None
    return built[0] if len(built) == 1 else {"and": built}


def build_search(db: dict, text: str, fields: list | None = None) -> dict | None:
    """토큰 AND × 텍스트 속성 OR.

    Notion 컴파운드는 2단계 중첩까지 허용하므로 `and[or[...]]` 가 정확히 한계선이다 —
    더 복잡한 구조는 애초에 불가능하다(스펙 §6).
    """
    tokens = [t for t in (text or "").split() if t]
    if not tokens:
        return None
    if fields:
        # 명시적으로 지정된 필드는 `find_prop` 을 거친다 — 그래야 오타에 "혹시 `Position`
        # 인가요?" 힌트가 붙고, "그 속성은 텍스트가 아니다"와 "텍스트 속성이 하나도
        # 없다"를 구분해서 말해줄 수 있다(둘 다 예전엔 같은 메시지로 뭉개졌다).
        targets = []
        for name in fields:
            prop = find_prop(db, name)
            # 두 실패는 서로 다른 처방을 요구하므로 갈라 던진다 — "텍스트 타입이 아니다"는
            # 다른 속성을 고르라는 뜻이고, "filterable=False"는 타입은 맞지만 이 속성
            # 자체가 조회에서 빠져 있다는 뜻이다. 하나로 합치면(리뷰 지적) rich_text 인
            # 속성에 대해 "텍스트 속성이 아니다 — rich_text 중에서 고르세요"라는, 재시도해도
            # 똑같이 실패할 자기모순 메시지가 나간다.
            if prop.get("type") not in TEXT_TYPES:
                raise ValueError(
                    f"`{name}`({prop.get('type')})은 텍스트 속성이 아니라 검색 대상으로 "
                    "쓸 수 없습니다 — title/rich_text/url/email/phone_number 중에서 고르세요")
            if not prop.get("filterable", True):
                raise ValueError(
                    f"`{name}`은 조회에서 제외된 속성입니다(filterable=false) — "
                    "다른 속성을 지정하거나 스키마가 바뀌었다면 "
                    "`notionmemory templates refresh <slug>` 를 실행하세요")
            targets.append(prop)
    else:
        targets = [p for p in db.get("properties") or []
                   if p.get("type") in TEXT_TYPES and p.get("filterable", True)]
        if not targets:
            raise ValueError(
                f"'{db.get('key')}'에 검색할 텍스트 속성이 없습니다 — Notion API 는 페이지 "
                "본문을 검색하지 못합니다. 찾아야 하는 내용은 속성에 넣으세요")
    return {"and": [{"or": [{"property": p["name"], p["type"]: {"contains": tok}}
                            for p in targets]} for tok in tokens]}


def compile_query(db: dict, *, wheres, search: str, sorts,
                  resolve_relation: Callable[[str, str], str]) -> dict:
    """`--where`/`--search`/`--sort` 를 하나의 Notion query 페이로드로 합친다.

    `build_where`/`build_search` 는 각자 이미 최대 2단계(`and`/`or`)로 끝난다. 둘 다
    있을 때 그냥 `{"and": [where, search]}` 로 다시 감싸면 이미 `and` 인 부분(다중
    where, 또는 search 의 토큰-AND) 이 한 겹 더 들어가 `and → and → or` 3단계가 되고,
    Notion 은 2단계까지만 허용하므로 이런 쿼리는 전부 400 이 된다. 그래서 부분이 이미
    `and` 모양이면 감싸지 않고 그 팔(arm)들을 바깥 리스트로 그대로 풀어 넣는다(splice) —
    합쳐도 항상 2단계를 넘지 않는다.
    """
    parts = [f for f in (build_where(db, wheres, resolve_relation=resolve_relation),
                         build_search(db, search)) if f]
    out: dict = {}
    if len(parts) == 1:
        out["filter"] = parts[0]
    elif parts:
        flat: list[dict] = []
        for p in parts:
            if list(p) == ["and"]:
                flat.extend(p["and"])
            else:
                flat.append(p)
        out["filter"] = {"and": flat}
    if sorts:
        for s in sorts:
            _checked(db, s["property"])
        out["sorts"] = list(sorts)
    return out
