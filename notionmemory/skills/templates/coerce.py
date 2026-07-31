"""값 강제 레이어 — `--set "P=V"` 하나가 Notion API JSON 이 되기까지의 관문.

**로컬 검증은 친절함이 아니라 방어선이다.** select/multi_select 는 목록에 없는 값을 쓰면
Notion 이 400 이 아니라 200 을 주면서 새 옵션을 만든다 — 아무도 에러를 못 보고 사용자
보드 뷰만 조용히 쪼개진다. status 는 반대로 400 으로 튕긴다. 같은 개념인데 동작이
정반대라 우리 쪽 허용 목록이 유일한 일관된 기준이다(스펙 §5).

거부는 전부 쓰기 **전에** 일어나고 메시지가 그대로 에이전트에게 돌아간다 — 허용 목록을
본 에이전트가 스스로 고쳐 재시도하므로 실패가 곧 스키마 학습이 된다.
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime
from typing import Callable

from notionmemory.skills.templates import types
from notionmemory.skills.templates.profile import find_prop
from notionmemory.core.notion_text import utf16_cap

MAX_RICH_TEXT = 2000
_TRUE = {"1", "true", "on", "yes", "y"}
_FALSE = {"0", "false", "off", "no", "n", ""}
# 하이픈은 전부 있거나 전부 없거나 — 부분 하이픈(카피 실수로 흔함)은 로컬에서 막지
# 않으면 그대로 Notion 에 던져져 400 이 된다.
_UUID_RE = re.compile(
    r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|[0-9a-fA-F]{32})$")
# 스칼라 텍스트 타입 — 빈 값이 "지우기"로 해석되는 것들
_SCALAR = {"url", "email", "phone_number"}


def rt(text: str) -> list[dict]:
    """rich_text 값 — Notion 항목당 2000자 한계 방어.

    calendar 에도 같은 두 줄이 있지만 import 하지 않는다. 스킬 간 결합을 늘리지 않는
    것이 이 설계의 전제이고(스펙 §0), 두 줄을 공유하려고 의존을 만들 이유가 없다.
    """
    return [{"text": {"content": utf16_cap(text or "", MAX_RICH_TEXT)}}]


def parse_set(raw: str) -> tuple[str, str]:
    """`"Status=Interview"` → `("Status", "Interview")`. 첫 `=` 에서만 자른다 —
    값에 `=` 가 들어가는 경우(URL 쿼리 등)가 흔하다."""
    if "=" not in (raw or ""):
        raise ValueError(f"--set 형식이 아닙니다: {raw!r} (P=V 형태로 지정하세요)")
    name, value = raw.split("=", 1)
    return name.strip(), value


# 입력 끝의 타임존 표기 — Notion 이 조회 응답에 이 형태로 값을 되돌려준다. 우리는
# 항상 타임존 없이 emit 하므로(아래) 받을 때만 벗겨내고 벽시계 값은 그대로 쓴다.
_TZ_SUFFIX_RE = re.compile(r"(Z|[+-]\d{2}:\d{2})$")


def parse_date(raw: str) -> dict:
    """`YYYY-MM-DD` / `YYYY-MM-DD HH:MM` / `A..B` → Notion date 값.

    상대 표현("다음 주")은 해석하지 않는다 — 에이전트가 절대 날짜를 계산해 넘기는 것이
    이 프로젝트의 규약이고, Notion 의 this_week 류 sugar 도 같은 이유로 배제했다(스펙 §6).

    출력은 항상 `%Y-%m-%dT%H:%M:%S`(초 포함, 타임존 없음)로 고정하지만, 입력은 그보다
    넓게 받는다 — 초 포함 형식과, Notion 이 조회 응답에 실어 보내는 `Z`/`+09:00` 타임존
    접미사까지 인정한다. 그래야 "조회 → 그대로 재기록" 흐름이 자기 출력에 막히지 않는다.
    """
    def one(part: str) -> str:
        s = _TZ_SUFFIX_RE.sub("", part.strip().replace("T", " "))
        for fmt, has_time in (("%Y-%m-%d", False),
                              ("%Y-%m-%d %H:%M:%S", True),
                              ("%Y-%m-%d %H:%M", True)):
            try:
                dt = datetime.strptime(s, fmt)
            except ValueError:
                continue
            # strptime 은 월/일에 zero-padding 을 강제하지 않는다("2026-7-2"도 통과) —
            # 그걸 그대로 돌려주면 로컬 검증은 통과하고 Notion 만 나중에 400 을 낸다.
            # strftime 으로 다시 밀어 넣어 항상 정규화된 값을 emit 한다.
            return dt.strftime("%Y-%m-%dT%H:%M:%S") if has_time else dt.strftime("%Y-%m-%d")
        raise ValueError(f"날짜 형식이 올바르지 않습니다: {part!r} "
                         "(YYYY-MM-DD 또는 YYYY-MM-DD HH:MM)")
    if ".." in raw:
        start, end = raw.split("..", 1)
        return {"start": one(start), "end": one(end)}
    return {"start": one(raw)}


def parse_bool(name: str, value: str) -> bool:
    """checkbox 값 해석의 유일한 출처 — read(`filters._scalar`)·write(`_value_json`) 양쪽이
    반드시 이걸 통해야 한다. 따로 두면 두 경로의 TRUE/FALSE 어휘가 조용히 벌어지고,
    한쪽만 `Remote=maybe` 를 막고 다른 쪽은 그걸 False 로 삼켜버리는 사고가 난다.
    """
    if not isinstance(value, str):
        # 추출 전 인라인 버전은 `value.strip()` 을 직접 호출해 None 이 AttributeError 로
        # 터졌다 — `(value or "")` 로 바꾸며 조용히 False 로 삼키게 된 것은 리팩터가
        # behaviour-preserving 이어야 한다는 전제를 어긴 회귀다. 이 함수의 존재 이유가
        # "모호한 참/거짓을 조용히 False 로 만들지 않는 것"이므로, 잘못된 타입도 같은
        # ValueError 로 걸어야 한다.
        raise ValueError(f"`{name}`은 참/거짓이어야 합니다: {value!r} (true/false)")
    low = value.strip().lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    raise ValueError(f"`{name}`은 참/거짓이어야 합니다: {value!r} (true/false)")


_READ_HINT = ("철자를 확인하거나, Notion 에서 스키마가 바뀌었다면 "
             "`notionmemory templates refresh <slug>` 를 실행하세요")


def validate_choice(prop: dict, value: str) -> str:
    """읽기 경로(`filters.py`)에서 select/status/multi_select 값을 허용 목록과 대조하는
    공개 진입점. `_choice` 를 얇게 감싸 `allow_new=False` 로 고정한다 — 필터는 새 옵션을
    만들 이유가 없고(조회일 뿐), 오타를 걸러내는 허용 목록·메시지를 쓰기 경로와 그대로
    공유해야 `--set` 과 `--where` 가 서로 다른 기준으로 갈라지지 않는다.

    hint 는 쓰기 경로와 다른 것을 넘긴다 — `--allow-new-option` 은 `--set` 에만 있는
    플래그다. 조회에는 없고, 새 옵션을 만든다고 필터가 뭔가에 매치하게 되는 것도
    아니다(존재하지 않는 값을 찾는 것뿐이다). 그 플래그를 조회 실패 메시지에 그대로
    노출하면 에이전트가 존재하지도 않는 옵션을 실행해 똑같은 실패를 반복한다 — 이건
    `_choice` 가 이미 status 에 대해 쓰는 것과 같은 종류의 실수를 새 표면에서 반복하는
    것이다. 검증 로직(허용 목록 대조) 자체는 그대로 재사용하고 tail 만 갈아 끼운다.
    """
    return _choice(prop, value, allow_new=False, hint=_READ_HINT)


def _choice(prop: dict, value: str, *, allow_new: bool, hint: str | None = None) -> str:
    # 이음매(seam): 이 레이어는 `choices` 라는 키만 읽는다. Notion API 자신은 이 목록을
    # `select.options` 라고 부른다 — 스키마 페처(후속 태스크)가 그 원래 이름을 그대로
    # 써서 프로필에 `options` 만 채우고 `choices` 로 정규화하지 않으면, 아래에서 즉시
    # ValueError 로 걸린다(무검증 통과로 조용히 새는 것을 막는 트립와이어).
    if "choices" not in prop and "options" in prop:
        raise ValueError(
            f"`{prop['name']}` 프로필이 정규화되지 않았습니다 — Notion 의 `options` 를 "
            "`choices` 로 매핑해야 값을 검증할 수 있습니다")
    # Notion 원본 옵션 배열을 그대로 복사해오면 문자열이 아니라 {"name": ...} dict 가
    # 섞여 들어온다 — 둘 다 받아 TypeError 대신 정상적인 ValueError 로 이어지게 한다.
    choices = [c["name"] if isinstance(c, dict) else c for c in (prop.get("choices") or [])]
    if value in choices:
        return value
    # 공백 무시 폴백 — 속성 이름(find_prop)과 같은 부류인데 여기가 더 위험하다: 옵션
    # 이름에 끝공백이 있으면(`완료 `) 사용자의 `완료` 는 select 에서 400 이 아니라
    # **조용히 새 옵션을 만들어** 보드를 쪼갠다(이 모듈 docstring 의 그 사고). 조회
    # (validate_choice) 쪽은 equals 가 아무것도 못 찾아 조용히 0건이 된다. strip 비교로
    # **유일**할 때만 캐노니컬 옵션명으로 치환한다 — allow_new 보다 먼저 시도해야
    # `--allow-new-option` 이 기존 옵션 매칭을 건너뛰고 중복 옵션을 만들지 않는다.
    def _norm(s: str) -> str:       # NFC 도 접는다 — find_prop 폴백과 같은 규율(NFD 입력)
        return unicodedata.normalize("NFC", (s or "").strip())
    stripped = [c for c in choices if _norm(c) == _norm(value)]
    if len(stripped) == 1:
        return stripped[0]
    if allow_new and choices:
        return value
    if not choices:
        # 등록 시 choices 를 못 읽은 DB — 막을 근거가 없으니 통과시키되 판단은 Notion 에.
        return value
    if prop.get("type") == "status":
        # status 는 --allow-new-option 을 걸어도 API 가 옵션 생성을 거부한다 — 그 플래그를
        # 광고하면 에이전트가 똑같은 실패를 한 번 더 반복하며 라운드트립만 태운다. 호출부가
        # 넘긴 hint 보다 이 사실이 우선한다 — 조회든 쓰기든 status 에는 이 말만 맞다.
        final_hint = "Notion API 는 status 옵션 생성을 허용하지 않습니다 — Notion 에서 먼저 옵션을 추가하세요"
    else:
        final_hint = hint if hint is not None else "의도적으로 새 옵션을 만들려면 --allow-new-option"
    raise ValueError(
        f"`{prop['name']}` 값이 허용 목록에 없습니다: {value!r} "
        f"(허용: {', '.join(choices)}) — {final_hint}")


def _value_json(prop: dict, value: str, *, resolve_relation: Callable[[str, str], str],
                allow_new_option: bool) -> dict:
    name, ptype = prop["name"], prop["type"]
    if ptype == "title":
        return {"title": rt(value)}
    if ptype == "rich_text":
        return {"rich_text": rt(value)}
    if ptype == "number":
        if not value.strip():
            # 빈 값(또는 공백만) = 지우기 (url/email/date 와 동일 규약) — 정확히 ""만
            # 검사하면 `--set "Salary= "` 가 "숫자여야 합니다"라는, 지우려는 의도와
            # 무관한 오류를 낸다.
            return {"number": None}
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"`{name}`은 숫자여야 합니다: {value!r}")
        if not math.isfinite(num):
            # nan/inf 도 float() 은 받아주지만 json.dumps 가 NaN/Infinity 로 뱉어 Notion
            # 에서 파싱 불가한 400 이 된다 — 여기서 막아야 메시지가 의미 있다.
            raise ValueError(f"`{name}`은 숫자여야 합니다: {value!r}")
        return {"number": num}
    if ptype == "checkbox":
        # checkbox 는 Notion 에서 nullable 이 아니다 — 다른 타입처럼 빈 값이 None 으로
        # 지워지는 게 아니라 False 가 "지워진" 상태 그 자체다("" 가 이미 _FALSE 에 포함).
        return {"checkbox": parse_bool(name, value)}
    if ptype in _SCALAR:
        return {ptype: value if value.strip() else None}      # 빈 값(공백 포함) = 지우기
    if ptype == "date":
        return {"date": parse_date(value) if value.strip() else None}
    if ptype in ("select", "status"):
        # status 에는 allow_new_option 을 적용하지 않는다 — API 가 옵션 생성을 거부해
        # 어차피 400 이다. 로컬에서 막는 편이 메시지가 명확하다.
        v = value.strip()   # 선택지는 이산 토큰 — multi_select 등 다른 갈래와 동일하게 정리
        if v == "":
            return {ptype: None}    # 빈 값 = 지우기
        allow = allow_new_option and ptype == "select"
        return {ptype: {"name": _choice(prop, v, allow_new=allow)}}
    if ptype == "multi_select":
        items = [v.strip() for v in value.split(",") if v.strip()]
        return {"multi_select": [{"name": _choice(prop, v, allow_new=allow_new_option)}
                                 for v in items]}
    if ptype == "people":
        ids = [v.strip() for v in value.split(",") if v.strip()]
        for uid in ids:
            if not _UUID_RE.match(uid):
                raise ValueError(
                    f"`{name}`에는 Notion 사용자 ID 가 필요합니다: {uid!r} — 이름으로는 "
                    "지정할 수 없습니다(사용자 검색은 비범위)")
        return {"people": [{"id": uid} for uid in ids]}
    if ptype == "files":
        urls = [v.strip() for v in value.split(",") if v.strip()]
        return {"files": [{"name": u.rsplit("/", 1)[-1] or u, "external": {"url": u}}
                          for u in urls]}
    if ptype == "relation":
        target = prop.get("relates_to")
        if not target:
            raise ValueError(
                f"`{name}`은 이 템플릿 밖의 데이터베이스를 가리켜 쓸 수 없습니다 "
                "(relates_to 대상이 등록되지 않음)")
        titles = [v.strip() for v in value.split(",") if v.strip()]
        return {"relation": [{"id": resolve_relation(target, t)} for t in titles]}
    raise ValueError(f"`{name}`의 타입 {ptype!r}은 쓰기를 지원하지 않습니다")


def build_properties(db: dict, pairs: list[tuple[str, str]], *,
                     resolve_relation: Callable[[str, str], str],
                     allow_new_option: bool = False) -> dict:
    """검증된 Notion `properties` 페이로드. 실패는 전부 쓰기 전에 ValueError."""
    out: dict = {}
    for name, value in pairs:
        prop = find_prop(db, name)          # 오타면 유사 이름 제안 + refresh 안내
        # 페이로드 키는 캐노니컬 이름 — find_prop 의 공백 무시 폴백으로 `마감일 `(끝공백)
        # 이 매칭됐을 때 사용자가 친 `마감일` 을 키로 쓰면 로컬 검증만 통과하고 Notion
        # 이 "없는 속성" 400 을 낸다. 중복 검사도 캐노니컬 기준이어야 `마감일`+`마감일 `
        # 이중 지정이 걸린다.
        canonical = prop["name"]
        if canonical in out:
            raise ValueError(f"같은 속성을 두 번 지정했습니다: {canonical}")
        if not types.flags(prop.get("type", "")).writable or not prop.get("writable"):
            raise ValueError(
                f"`{name}`은 {prop.get('type')} 이라 쓸 수 없습니다 (읽기 전용 속성)")
        out[canonical] = _value_json(prop, value, resolve_relation=resolve_relation,
                                     allow_new_option=allow_new_option)
    return out
