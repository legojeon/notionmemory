"""등록 파이프라인 — 페이지 → 하위 DB → 스키마 → 샘플 → 본문 → 프로필.

**신뢰 경계가 여기서 코드가 된다.** 4단계까지는 API 응답 원문 복사이고(추론 없음),
6단계의 에이전트 호출은 실패해도 프로필이 저장된다. LLM 에게 프로필 YAML 을 통째로
만들게 하면 `type: select`(실제는 status) 같은 오류가 등록 시점에 드러나지 않고 몇 주 뒤
쓰기 400 으로 나타난다 — 틀릴 수 없는 것을 틀릴 수 있는 방식으로 얻지 않는다(스펙 §1).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date

from notionmemory.skills.templates import profile, render, types

MAX_DEPTH = 5
MAX_NODES = 500     # 방문 노드 총량 상한 — 깊이 상한과 별개 축이다. 깊이는 얕아도
                    # 한 노드가 페이지네이션으로 여러 페이지(각 100블록)를 뱉으면
                    # 팬아웃이 커진다. 남의 템플릿은 우리가 만들지 않았다(마이너 리뷰 지적).
SAMPLE_ROWS = 3
_ID_ANCHORED_RE = re.compile(r"[0-9a-fA-F]{32}$")
_DASHED_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

_SYSTEM = (
    "너는 Notion 템플릿 분석기다. 주어진 스키마와 샘플 행을 보고 두 가지만 만든다.\n"
    "첫 줄은 정확히 `요약: <한 문장>` 형식으로 이 템플릿이 무엇에 쓰는 물건인지 쓴다.\n"
    "그 다음 빈 줄 뒤에 마크다운 본문을 쓴다: `## 무엇에 쓰는 템플릿인가`와 "
    "`## 흔한 요청 → 동작` 두 절만. 후자는 사용자의 자연어 요청을 어느 데이터베이스의 "
    "어떤 속성 값으로 옮길지 예시로 적는다.\n"
    "속성 이름·타입·선택지를 새로 만들거나 바꾸지 마라 — 주어진 것만 인용한다.\n"
    "코드펜스로 감싸지 말고 설명 문구도 붙이지 마라.")


class AmbiguousTarget(ValueError):
    """이름 검색 결과가 1건이 아니다. 후보를 실어 보내 CLI 가 exit 2 로 되묻게 한다."""

    def __init__(self, message: str, candidates: list):
        super().__init__(message)
        self.candidates = candidates


def slugify(title: str) -> str:
    # `_` 는 `\w` 에 포함돼 단어 문자로 보이지만 슬러그에서는 다른 구분자(공백·하이픈)
    # 와 동격이어야 한다 — 그래서 별도 대안(`|_`)으로 명시해 구분자 집합에 넣는다.
    # 예전엔 이걸 `[^0-9a-z가-힣]+` 로(ASCII+한글만 허용) 풀었는데, 그러면 `\w` 가
    # 커버하던 다른 문자 체계(악센트 라틴·일본어·키릴 등)가 통째로 걸러져
    # "Café Notes" → "caf-notes", "日本語ノート"/"Проекты" → "template" 이 되는
    # 회귀를 냈다(I8, 실기 재현). `\w` 를 그대로 쓰고 밑줄만 별도 구분자로 얹으면
    # 두 문제가 동시에 풀린다 — run(연속 구간) 단위로 한 번에 하이픈 하나로 뭉쳐진다.
    text = unicodedata.normalize("NFC", (title or "").strip().lower())
    text = re.sub(r"(?:[^\w가-힣]|_)+", "-", text)
    return text.strip("-") or "template"


def extract_page_id(target: str) -> str:
    """URL 이나 ID 면 32자리 hex, 이름이면 ""."""
    text = (target or "").strip()
    if _DASHED_RE.fullmatch(text):
        return text.replace("-", "")
    # 쿼리스트링(`?v=<view-id>`)까지 스캔하면 진짜 페이지 id 대신 뷰 id 를 집어버린다
    # — Notion 의 "Copy link" 는 데이터베이스 뷰가 있는 페이지에서 `?v=` 를 늘
    # 붙인다(I4, 실기 재현). 매칭 전에 쿼리를 잘라낸다. `?` 만 자르면 프래그먼트만
    # 있는 링크(`#<blockid>`, 쿼리스트링 없이 앵커만 붙은 "Copy link to block")를
    # 놓친다 — 블록 id 를 페이지 id 로 착각한다(마이너 리뷰 지적 5). `?`/`#` 둘 다에서
    # 자른다.
    path = re.split(r"[?#]", text, maxsplit=1)[0]
    # (CRITICAL, 확인 리뷰 실기 재현) 예전엔 여기서 전체 경로 문자열의 대시를 지우고
    # "어딘가에 있는 32-hex 윈도우"를 찾았다 — Notion URL 은 `<title-slug>-<id>` 를
    # 대시로 이어붙인 한 세그먼트라, 대시를 지우면 제목의 마지막 글자들이 id 앞에
    # 그대로 달라붙는다. 제목이 hex 문자(연도, `a`-`f`)로 끝나면 그 글자들이 id 의
    # 앞부분인 것처럼 뭉쳐, 32자 윈도우가 오른쪽으로 밀리며 진짜 id 의 마지막
    # 글자를 잘라먹는다("earliest window" 문제 — 어떤 hex 조합으로 끝나는 제목이든
    # 재현된다. 열거로는 못 막는다). id 는 항상 세그먼트의 **끝**에 붙는다는 사실만
    # 참이다 — 그래서 이 리포 선례(`memory/notion_db.py:page_id_from_url`)처럼
    # 마지막 경로 세그먼트만 떼어내 그 **끝에서부터** 32-hex 를 고정 매칭한다(`$`
    # 앵커). 제목이 무엇으로 끝나든 앞쪽에 뭐가 붙어 있든, 문자열 끝의 32글자만
    # 보므로 흔들리지 않는다.
    tail = path.rstrip("/").rsplit("/", 1)[-1]
    match = _ID_ANCHORED_RE.search(tail.replace("-", ""))
    return match.group(0) if match else ""


def _req(session, method: str, path: str, **kwargs):
    """>=300 은 전부 예외다 — 이 헬퍼를 쓰는 모든 호출(검색·페이지·블록 목록)에는
    "실패해도 정상"인 분기가 없다. `fetch_database` 만 예외다: 거기선 404 가
    child_database 블록이 실제 DB 가 아니라 linked view 를 가리켰다는, API 계약에
    내재된 정상 분기라 `_req` 대신 직접 스킵으로 해석한다 — 그 외 비-200
    (401/403/429/5xx)은 거기서도 이 함수와 동일하게 예외로 올라간다(I5). 이 둘의
    비대칭은 의도된 것이라 여기 문서화해 둔다(마이너 리뷰 지적)."""
    resp = session.request(method, path, **kwargs)
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Notion {method} {path} 실패: {resp.status_code} {resp.text[:200]}")
    return resp


def _is_missing(resp) -> bool:
    """"이 id 는 실존하는 DB 가 아니다"(linked view 일 수 있음)의 판정 기준.

    상태 코드 404 만 보면 좁다 — 이 리포의 선례(`notes/notion_exporter.py`의
    `_notion_error`)는 body 의 `object_not_found` 코드도 같은 조건으로 인정한다.
    Notion 이 같은 상황을 다른 status(예: 400)로 응답하면 상태만 보는 판정은
    linked view 하나가 낀 템플릿 전체를 등록 불가능하게 만든다(마이너 리뷰 지적 6).
    """
    if resp.status_code == 404:
        return True
    try:
        return resp.json().get("code") == "object_not_found"
    except Exception:
        return False


def _page_title(obj: dict) -> str:
    for value in (obj.get("properties") or {}).values():
        if value.get("type") == "title":
            return "".join(i.get("plain_text", "") for i in value.get("title") or [])
    return ""


def resolve_target(session, target: str) -> str:
    page_id = extract_page_id(target)
    if page_id:
        return page_id
    data = _req(session, "POST", "/search", json={
        "query": target, "filter": {"property": "object", "value": "page"},
        "page_size": 10}).json()
    hits = [r for r in data.get("results", []) if r.get("object") == "page"]
    candidates = [{"id": r["id"], "title": _page_title(r), "url": r.get("url", "")}
                  for r in hits]
    if len(candidates) == 1:
        return candidates[0]["id"]
    if not candidates:
        raise AmbiguousTarget(
            f"'{target}'와 일치하는 페이지를 찾지 못했습니다 — 그 페이지를 integration 에 "
            "공유하지 않으셨을 수 있습니다(Notion 검색은 공유된 페이지만 반환합니다).", [])
    raise AmbiguousTarget(
        f"'{target}'와 일치하는 페이지가 {len(candidates)}건입니다 — URL 로 지정하세요.",
        candidates)


def walk_structure(session, root_page_id: str, *, max_depth: int = MAX_DEPTH,
                   max_nodes: int = MAX_NODES, stats: dict | None = None) -> tuple[list, list]:
    """블록 트리를 훑어 (pages, db_ids) 를 만든다.

    `collect_database_ids` 의 일반화 — 같은 노드 예산·순환 방어·진행 불변식 가드를
    쓰되, 페이지별 헤딩 개요를 모으고 `child_page` 만 새 페이지 노드로 만든다. 구조
    (개요)는 등록 시 캐싱하고 본문 내용은 캐싱하지 않는다 — 편집은 라이브로 다시 읽는다.

    pages 원소의 `databases` 는 아직 db-key 가 아니라 child_database **블록 id** 다.
    `_build` 가 스키마를 뽑아 key 를 확정한 뒤 그 id 를 key 로 치환한다.

    컨테이너(토글·컬럼 등)는 같은 page node 안에서 **명시적 스택**으로 훑는다(재귀
    아님 — 깊은 중첩에서 RecursionError 방지). 헤딩도 `seen_blocks` 에 넣어 진행
    불변식 가드가 헤딩만 있는 페이지의 페이지네이션에서도 오작동하지 않게 한다.
    """
    pages: list = []
    db_ids: list = []
    seen_pages: set = set()
    seen_blocks: set = set()     # 방문 블록(순환·중복 방어) + 노드 예산 카운터
    page_queue = [(root_page_id, "", 0, None)]
    capped = False

    while page_queue:
        page_id, title, depth, parent = page_queue.pop(0)
        if page_id in seen_pages or depth > max_depth:
            continue
        seen_pages.add(page_id)
        node = {"page_id": page_id, "title": title, "depth": depth,
                "parent": parent, "headings": [], "databases": []}
        pages.append(node)
        if depth >= max_depth:
            continue
        # 이 페이지의 블록 서브트리를 명시적 스택으로 훑는다(재귀 아님).
        # child_page 는 page_queue 로(depth+1), 컨테이너는 이 스택으로(같은 node·같은 depth).
        stack = [page_id]
        while stack and not capped:
            container = stack.pop()
            cursor = None
            while True:
                if len(seen_blocks) >= max_nodes:
                    capped = True
                    break
                params = {"page_size": 100}
                if cursor:
                    params["start_cursor"] = cursor
                data = _req(session, "GET",
                            f"/blocks/{container}/children", params=params).json()
                page_blocks = data.get("results") or []
                before = len(seen_blocks)
                for block in page_blocks:
                    if len(seen_blocks) >= max_nodes:
                        capped = True
                        break
                    bid = block.get("id", "")
                    if bid in seen_blocks:
                        continue
                    seen_blocks.add(bid)     # 헤딩 포함 — 진행 불변식이 헤딩 페이지에서도 동작
                    btype = block.get("type", "")
                    if btype in ("heading_1", "heading_2", "heading_3"):
                        rich = (block.get(btype) or {}).get("rich_text") or []
                        node["headings"].append(
                            "".join(r.get("plain_text", "") for r in rich
                                    if isinstance(r, dict)))
                    elif btype == "child_database":
                        db_ids.append(bid)
                        node["databases"].append(bid)
                    elif btype == "child_page":
                        ptitle = (block.get("child_page") or {}).get("title", "")
                        page_queue.append((bid, ptitle, depth + 1, page_id))
                    elif block.get("has_children"):
                        stack.append(bid)
                if capped:
                    break
                # 진행 불변식(store._fetch·기존 collect_database_ids 와 같은 규율):
                # has_more 인데 이번 요청이 새 블록을 못 늘렸거나 커서가 없으면 멈춘다.
                if not data.get("has_more") or len(seen_blocks) == before:
                    break
                next_cursor = data.get("next_cursor")
                if not next_cursor or not page_blocks:
                    break
                cursor = next_cursor

    if capped and stats is not None:
        stats["capped"] = True
    return pages, db_ids


def fetch_database(session, database_id: str, *, log=lambda *_: None,
                    stats: dict | None = None) -> dict | None:
    """스키마 추출 — 두 홉이 필요하다(C3, 실기 재현).

    `GET /databases/{id}` 는 제목과 data source 목록만 준다. 속성(스키마)은 거기
    없다 — 2025-09 Notion API 부터 `properties` 는 `GET /data_sources/{id}` 응답에
    산다. 이 리포 안에서도 이미 그렇게 쓰고 있다: `notion_exporter.py`의
    `_data_source_title_property`(163-168행), `memory/notion_db.py:98`의
    data source PATCH. 한 홉으로 읽으면 `properties: []` 가 조용히 나오고(예외가
    아니라 빈 값이라) `_build` 가 못 걸러내 등록이 "성공"한 것처럼 보인다 —
    그 뒤 모든 `--set` 이 "그런 속성이 없습니다"로 실패하는 지연 폭탄이 된다.

    404(또는 200 인데 data source 가 없음)만 "linked view 일 수 있음"으로 스킵한다
    — 401/403/429/5xx 처럼 진짜 실패인 응답을 같은 취급으로 삼키면(I5), 등록
    시점에만 검증할 수 있는 스키마가 불완전한 채로 영구 저장된다. 등록은 스키마를
    확정하는 유일한 순간이라 일시 장애를 추측으로 덮지 않는다 — 그런 실패는 그대로
    위로 던진다.

    `stats` 는 선택 — 건너뛴 이유를 종류별로 센다("view" | "empty_schema"). 최종
    "데이터베이스가 없습니다" 메시지가 실제로 무엇 때문에 다 걸러졌는지 말하게
    하려는 것이다(마이너 리뷰 지적 7) — 없으면 그냥 로그만 남긴다."""
    def _skip(kind: str, msg: str) -> None:
        log(msg)
        if stats is not None:
            stats[kind] = stats.get(kind, 0) + 1

    resp = session.request("GET", f"/databases/{database_id}")
    if _is_missing(resp):
        _skip("view", f"  ! 데이터베이스 조회 실패로 건너뜀: {database_id} "
              "(linked database view 일 수 있습니다)")
        return None
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Notion GET /databases/{database_id} 실패: {resp.status_code} "
            f"{resp.text[:200]}")
    body = resp.json()
    sources = body.get("data_sources") or []
    if not sources:
        _skip("view", f"  ! 데이터베이스 조회 실패로 건너뜀: {database_id} "
              "(linked database view 일 수 있습니다)")
        return None
    if len(sources) > 1:
        # 프로필 형식은 DB 당 `data_source_id` 하나만 담는다 — 첫 번째를 그대로
        # 쓰되(스펙 변경 아님), 여러 개였다는 사실은 조용히 삼키지 않는다(C3).
        log(f"  ! {database_id} 에 data source 가 {len(sources)}개입니다 — "
            "첫 번째만 사용합니다")
    ds_id = sources[0].get("id", "")
    ds_resp = session.request("GET", f"/data_sources/{ds_id}")
    if _is_missing(ds_resp):
        _skip("view", f"  ! 데이터베이스 조회 실패로 건너뜀: {database_id} "
              "(linked database view 일 수 있습니다)")
        return None
    if ds_resp.status_code >= 300:
        raise RuntimeError(
            f"Notion GET /data_sources/{ds_id} 실패: {ds_resp.status_code} "
            f"{ds_resp.text[:200]}")
    raw_props = ds_resp.json().get("properties") or {}
    title = "".join(i.get("plain_text", "") for i in body.get("title") or [])
    props = []
    title_property = ""
    for name, raw in raw_props.items():
        ptype = raw.get("type", "")
        flags = types.flags(ptype)
        prop = {"name": name, "type": ptype,
                "writable": flags.writable, "filterable": flags.filterable}
        if ptype in ("select", "multi_select", "status"):
            # Notion 은 이 목록을 `options` 라고 부른다 — `coerce.py`/`filters.py` 는
            # 오직 `choices` 만 읽는다(트립와이어가 걸려 있다). 여기서 정규화하지
            # 않으면 모든 select 가 검증 없이 통과해 오타가 Notion 에 새 옵션으로
            # 조용히 200 OK 쓰기된다 — 이 패키지가 막으려는 바로 그 사고다.
            options = (raw.get(ptype) or {}).get("options") or []
            prop["choices"] = [o.get("name", "") for o in options]
        if ptype == "relation":
            # 상대 DB id 를 그대로 담아둔다 — 프로필 조립 단계에서 key 로 치환한다.
            # C3 이후 이 값도 `GET /data_sources/{id}` 응답에서 온다 — 그쪽은 data
            # source 지향이라 `database_id` 대신 `data_source_id` 만 줄 가능성을
            # 이 환경에서는 실측하지 못했다(마이너 리뷰 지적 4). 그러면
            # `database_id` 를 그냥 읽는 코드는 빈 문자열을 얻어 모든 관계가
            # "템플릿 밖"으로 조용히 강등된다 — 등록 시점엔 정상으로 보이고 모든
            # 관계 쓰기가 나중에야 거부된다. 방어적으로 두 필드 다 인정한다.
            relation_cfg = raw.get("relation") or {}
            prop["_relation_db"] = (relation_cfg.get("database_id")
                                     or relation_cfg.get("data_source_id") or "")
        if ptype == "title":
            title_property = name
        props.append(prop)
    if not props:
        # 스키마 없는 응답은 절대 "동작하는 DB 항목"으로 저장되면 안 된다(C3) —
        # 그러면 이 DB 를 겨냥한 모든 쓰기/필터가 등록 시점이 아니라 사용 시점에야
        # "그런 속성이 없습니다"로 실패한다. 경고만 남기고 건너뛴다.
        _skip("empty_schema",
              f"  ! {database_id} 스키마가 비어 있어 건너뜁니다 (data_source={ds_id})")
        return None
    return {"key": slugify(title), "title": title, "database_id": body.get("id", ""),
            "data_source_id": ds_id,
            "title_property": title_property, "missing": False, "properties": props}


def _dedupe_keys(databases: list) -> None:
    """`key = slugify(title)` 만으로는 두 DB 제목이 같은 슬러그로 뭉칠 수 있다
    ("Notes 2024"/"Notes-2024") — `profile.find_db` 는 첫 번째만 돌려주고, 관계
    쓰기는 조용히 엉뚱한 DB 를 겨냥하며, `samples = {db['key']: ...}` 는 한쪽
    행을 조용히 지운다(I7).

    **불변식(확인 리뷰 3번째 재발 — 이전 두 문서화는 둘 다 틀렸다): 같은 슬러그를
    공유하는 그룹의 구성원은 전원 접미사를 받는다, 첫 번째도 예외 없다. 그리고
    어떤 DB 가 어떤 키를 받는지는 오직 그 DB 자신의 `database_id`에만 좌우되고,
    형제가 몇 개 있었는지·등록 순서가 무엇이었는지에는 좌우되지 않는다.**

    예전 버전은 "첫 등장은 그대로 두고 이후 등장에만 접미사를 붙인다"고 주장했다
    — 이건 위치 의존성을 옮겨 숨긴 것일 뿐이었다: DB 하나가 빠지거나 등록 순서가
    바뀌면 "몇 번째 등장인가"가 바뀌어 어느 DB 가 맨살 키를 갖는지도 바뀐다.
    거기에 더해 그 "첫 등장" 분기는 `used`를 전혀 확인하지 않고 맨살 키를
    그대로 가져갔다 — 그래서 이미 다른 그룹이 접미사로 만들어 놓은 키와 그대로
    충돌할 수 있었다(실기 재현: `Notes`, `Notes`, `Notes 402434` — 세 번째의
    자연 슬러그가 두 번째 "Notes"의 해시 접미사와 우연히 같아,
    `['notes', 'notes-402434', 'notes-402434']` 가 나오고 `relates_to:
    notes-402434`인 관계가 세 번째가 아니라 두 번째로 라우팅됐다 — 이 함수가
    막으려던 바로 그 사고가 이 함수 자신의 예외 처리 때문에 재발했다).

    지금은 그룹 소속 여부(슬러그가 몇 번 등장했는가)를 등록 순서와 무관하게
    먼저 통째로 계산한다. 슬러그가 한 번뿐인 DB 는 그 키를 그대로 예약해
    `used`에 넣는다. 슬러그가 두 번 이상인 그룹은 구성원 **전원**이(첫 번째
    포함) 자기 `database_id` 해시로 접미사를 받으며, 그 후보도 똑같이 `used`를
    거쳐 유일성을 확인한다 — 그래서 위 재현 사례의 세 번째 키도 이미 예약된
    "notes-402434"와 부딪히면 자기 접미사 길이를 늘린다.

    접미사 길이는 실제로 겹칠 때만(해시 충돌 — 사실상 발생하지 않는다) 늘리고,
    digest(40 hex, sha1)가 다 소진되도록 늘려도 후보가 안 바뀌면(마이너 리뷰
    지적 4 — `database_id` 가 비어(응답이 `id` 를 빠뜨린 폴백) 여러 DB 가 같은
    digest 를 공유할 때 실제로 벌어진다, 실기 재현: 동일 `database_id` 20개
    공유 시 `while` 무한루프) 유한한 카운터로 갈아타 반드시 끝낸다."""
    base_counts: dict[str, int] = {}
    for db in databases:
        base_counts[db["key"]] = base_counts.get(db["key"], 0) + 1

    used: set[str] = set()
    for db in databases:
        if base_counts[db["key"]] == 1:
            used.add(db["key"])

    def _claim(base: str, database_id: str) -> str:
        digest = hashlib.sha1((database_id or "").encode()).hexdigest()
        length = 6
        candidate = f"{base}-{digest[:length]}"
        while candidate in used:
            length += 2
            if length <= len(digest):
                candidate = f"{base}-{digest[:length]}"
                continue
            # digest 포화 — `digest[:length]`는 `length > len(digest)`부터 digest
            # 전체로 고정돼 더 늘려도 후보가 안 바뀐다. 유한한 카운터로 갈아탄다:
            # `used`는 유한하므로 반드시 빈 자리를 찾는다.
            n = 0
            candidate = f"{base}-{digest}-{n}"
            while candidate in used:
                n += 1
                candidate = f"{base}-{digest}-{n}"
            break
        return candidate

    for db in databases:
        base = db["key"]
        if base_counts[base] == 1:
            continue
        candidate = _claim(base, db.get("database_id", ""))
        db["key"] = candidate
        used.add(candidate)


def _link_relations(databases: list) -> None:
    """relation 의 상대 DB id → 같은 프로필 안의 key. 밖을 가리키면 쓰기 불가로 강등.

    `by_db_id` 는 `database_id` 뿐 아니라 `data_source_id` 로도 찾을 수 있게 둘 다
    키로 넣는다 — `_relation_db` 가 (C3 이후의 data-source 지향 응답 모양에서)
    `data_source_id` 로 채워졌을 수 있어서다(마이너 리뷰 지적 4)."""
    by_db_id: dict[str, str] = {}
    for db in databases:
        if db.get("database_id"):
            by_db_id[db["database_id"]] = db["key"]
        if db.get("data_source_id"):
            by_db_id[db["data_source_id"]] = db["key"]
    for db in databases:
        for prop in db["properties"]:
            if prop.get("type") != "relation":
                continue
            key = by_db_id.get(prop.pop("_relation_db", ""))
            prop["relates_to"] = key
            if key is None:
                prop["writable"] = False


def sample_rows(session, data_source_id: str, names: list, n: int = SAMPLE_ROWS) -> list:
    """속성 이름만으로는 `Notes` 에 뭘 적는 칸인지 알 수 없다 — 실제 값을 보여준다."""
    resp = session.request("POST", f"/data_sources/{data_source_id}/query",
                           json={"page_size": n})
    if resp.status_code != 200:
        return []
    return [render.flatten(pg, names) for pg in resp.json().get("results", [])[:n]]


def _generate_body(runtime, p: profile.Profile, samples: dict,
                    log) -> tuple[str, str] | None:
    """(summary, body) — 성공(agent 가 실제로 응답)했을 때만. 실패하면 `None`.

    "실패해서 아무것도 못 만들었다"와 "성공했지만 (공백만 있는 등) 실질 내용이
    없었다"를 같은 `("", "")` 로 뭉치면 호출자는 둘을 구분할 수 없다(재리뷰
    Important 2, 실기 재현) — `register()`/`refresh()` 는 재등록/재조회 시 기존에
    학습된 프로즈를 갖고 있을 수 있는데, "실패"일 때는 그걸 보존해야 하고
    "성공했지만 빈 응답"일 때는 (agent 가 실제로 판단해서 낸 결과이므로) 빈
    값으로 덮어써야 한다. 예전엔 둘 다 `("", "")` 라 호출자가 구분할 방법이
    없었고, `runtime is not None` 분기는 무조건 이 반환값을 그대로 대입해
    "설치는 됐지만 죽어있는 런타임"으로 재등록하면 학습한 노트가 영구 삭제됐다
    — agent 가 아예 없는 경우(그건 별도로 이미 처리돼 있었다)보다 흔한 실패
    모드다."""
    if runtime is None:
        log("  ! agent 런타임이 없어 사용 노트 없이 저장합니다 (CRUD 는 전부 동작합니다)")
        return "", ""
    schema = "\n".join(
        f"- {db['title']} (key={db['key']}): " + ", ".join(
            f"{prop['name']}:{prop['type']}"
            + (f"[{'/'.join(prop['choices'])}]" if prop.get("choices") else "")
            for prop in db["properties"])
        for db in p.databases)
    rows = "\n".join(f"- {db_key}: {row}" for db_key, rows_ in samples.items()
                     for row in rows_)
    try:
        raw = runtime.generate(_SYSTEM, f"템플릿 이름: {p.name}\n\n"
                                        f"데이터베이스와 속성:\n{schema}\n\n"
                                        f"샘플 행:\n{rows or '(없음)'}")
    except Exception as exc:                       # 타임아웃·미연결·비정상 종료 전부
        log(f"  ! 사용 노트 생성 실패 — 기존 프로필을 보존합니다: {exc}")
        return None
    # `runtime` 은 덕타이핑으로 주입된다 — 실제 `AgentRuntime` 은 늘 str 을 주지만
    # 테스트 더블/미래 구현은 아닐 수 있다. (마이너 리뷰 지적 5, 확인 리뷰 3번째
    # 재발) 예전엔 str 이 아닌 응답을 `""`(=빈 응답)로 강제해 아래로 흘려보냈는데,
    # 그러면 호출자(`register`/`refresh`) 입장에서 "agent 가 실제로 판단해서 빈
    # 결과를 냈다"와 구분이 안 된다 — `("", "")`는 "빈 값으로 덮어써도 된다"는
    # 신호라서, `--slug` 재등록 시 학습된 프로즈가 지워졌다(마이너 리뷰 지적 8
    # 이 고치려던 사고가 그 고침 자체를 통해 재발— dict 를 프로즈로 저장하던
    # 문제는 없어졌지만, dict/None 을 "성공"으로 오분류하는 새 문제가 생겼다).
    # str 이 아니면 예외 경로와 똑같이 다룬다: `None` 을 돌려줘 "실패, 기존 프로필
    # 보존"을 호출자에게 알린다.
    if not isinstance(raw, str):
        log(f"  ! 사용 노트 생성이 문자열이 아닌 응답을 반환했습니다({type(raw).__name__}) "
            "— 기존 프로필을 보존합니다")
        return None
    lines = raw.strip().splitlines()
    summary = ""
    if lines and lines[0].startswith("요약:"):
        summary = lines[0].split(":", 1)[1].strip()
        lines = lines[1:]
    body = "\n".join(lines).strip()
    # 공백만 있는 본문을 `"\n"` 으로 저장하면 "본문 없음"과 "빈 줄만 있는 본문"이
    # 다운스트림에서 구분되지 않는다(마이너 리뷰 지적) — 빈 문자열로 정규화한다.
    return summary, f"{body}\n" if body else ""


def _build(session, page_id: str, log) -> tuple[dict, list, list]:
    resp = session.request("GET", f"/pages/{page_id}")
    if resp.status_code == 404:
        raise RuntimeError(
            f"페이지에 접근할 수 없습니다({page_id}) — 이 페이지를 integration 에 "
            "공유했나요? Notion 페이지 우상단 ••• → 연결 → notionmemory 를 추가하세요.")
    if resp.status_code >= 300:
        raise RuntimeError(f"Notion GET /pages/{page_id} 실패: {resp.status_code}")
    page = resp.json()
    node_stats: dict = {}
    pages, db_ids = walk_structure(session, page_id, max_nodes=MAX_NODES, stats=node_stats)
    if node_stats.get("capped"):
        # 마이너 리뷰 지적 6 — 예산에 걸리면 조용히 잘린 목록을 그대로 반환한다.
        # 프로필은 곧 `health: ok` 로 저장되니, 여기서 말하지 않으면 데이터베이스
        # 몇 개가 트리에서 빠졌는지 알 길이 아예 없어진다.
        log(f"  ! 블록 트리가 노드 예산({MAX_NODES}개)에 도달해 일부만 확인했습니다 — "
            "이 페이지 하위에 데이터베이스·하위 페이지가 더 있을 수 있습니다")
    stats: dict[str, int] = {}
    databases = []
    for db_id in db_ids:
        # `fetch_database` 가 왜 건너뛰는지 이미 알고 로그를 남긴다(view/스키마
        # 없음/data source 소실) — 여기서 다시 일반화된 이유를 덧붙이지 않는다.
        # 예전엔 여기서 "linked database view 일 수 있습니다"를 매번 덧씌워서,
        # 진짜 원인이 401/빈 스키마여도 사용자에게는 늘 같은(때로는 틀린) 원인이
        # 찍혔다(I5). `stats` 는 최종 실패 메시지가 실제 원인을 말하게 하려는
        # 별도의 집계다(마이너 리뷰 지적 7 — 아래 참고).
        db = fetch_database(session, db_id, log=log, stats=stats)
        if db is None:
            continue
        databases.append(db)
    _dedupe_keys(databases)
    _link_relations(databases)
    # 페이지의 임시 child_database 블록 id 를 확정된 db-key 로 치환.
    # child_database 블록 id 는 곧 database id 이므로 database_id 로 매핑한다.
    id_to_key = {db["database_id"]: db["key"] for db in databases}
    for node in pages:
        node["databases"] = [id_to_key[b] for b in node["databases"] if b in id_to_key]
    # 거부는 "블록도 DB도 하위 페이지도 하나도 없는 진짜 빈 페이지"일 때만.
    has_content = any(node["headings"] for node in pages)
    has_subpages = len(pages) > 1
    if not databases and not has_content and not has_subpages:
        raise RuntimeError(
            "빈 페이지입니다 — 블록도 데이터베이스도 하위 페이지도 없어 등록할 것이 "
            "없습니다. 내용이 있는 페이지를 지정하세요.")
    return page, databases, pages


def register(session, target: str, *, slug: str = "", runtime=None, log=print) -> profile.Profile:
    # `resolve_target` 이 URL/이름을 페이지 id 로 확정한다(C1, 실기 재현) — 이걸
    # 건너뛰면 이름으로 등록("Job Tracker")이 그대로 `GET /pages/Job Tracker` 로
    # 나가 400 을 받고, 404 분기는 "공유 안 됨"이라는 틀린 원인을 사용자에게
    # 알려준다(이름이 애초에 검색되지 않았을 뿐인데). 이름 검색 결과가 1건이
    # 아니면 `AmbiguousTarget`(`ValueError` 서브클래스)이 여기서 그대로 위로
    # 던져진다 — CLI 가 `register()` 를 호출하는 지점에서 이걸 잡아 exit 2 로
    # 후보를 보여주며 되묻는다. 그 되묻기는 이 함수 안이 아니라 호출자(CLI)의
    # 책임이다: `AmbiguousTarget.candidates` 는 애초에 CLI 가 소비하라고 있는
    # 필드다.
    page_id = resolve_target(session, target)
    page, databases, pages = _build(session, page_id, log)
    name = _page_title(page) or "Template"
    chosen = slug or slugify(name)
    if not slug and profile.exists(chosen):
        raise ValueError(
            f"이미 '{chosen}' 이름으로 등록돼 있습니다 — 덮어쓰려면 --slug {chosen} 을 "
            "명시하세요(재등록으로 간주합니다)")
    # `--slug` 재등록은 "템플릿을 다시 복제해 page_id 가 바뀌었다"는 뜻이지 "익힌
    # 것을 버려라"는 뜻이 아니다(스펙 §8, I6). 기존 프로필이 있으면 그걸 먼저
    # 불러 `enabled`/`summary`/`body` 를 이어받는다 — `runtime` 이 없는 흔한
    # 경우(claude/codex 미설치)에 재등록이 학습된 노트를 지우고 비활성화까지
    # 초기화하던 회귀였다. `refresh()` 가 이미 같은 패턴을 쓴다.
    existing = profile.load(chosen) if slug and profile.exists(chosen) else None
    today = date.today().isoformat()
    caps = types.derive_capabilities(databases)
    if any(node["headings"] for node in pages):
        caps.append("document")
    p = profile.Profile(
        slug=chosen, name=name, page_id=page.get("id", page_id),
        page_url=page.get("url", ""), enabled=True, health="ok",
        health_checked_at=today, schema_fetched_at=today,
        capabilities=caps, databases=databases, pages=pages)
    if existing is not None:
        p.enabled = existing.enabled
        p.prompt = existing.prompt      # 전환(청사진→인스턴스) 시 프롬프트 보존
    if runtime is not None:
        samples = {db["key"]: sample_rows(session, db["data_source_id"],
                                          [prop["name"] for prop in db["properties"]])
                   for db in databases}
        generated = _generate_body(runtime, p, samples, log)
        # `_generate_body` 는 실패(agent 가 죽음)와 성공(빈 응답 포함)을 구분해
        # 돌려준다(재리뷰 Important 2, 실기 재현) — 실패면 기존 프로필의 프로즈를
        # 그대로 지킨다. 예전엔 `runtime is not None` 이면 무조건 반환값을
        # 대입했는데, 실패해도 `("", "")` 가 왔으므로 "설치는 됐지만 죽어있는
        # 런타임"으로 재등록하면 학습한 노트가 영구 삭제됐다 — agent 가 아예
        # 없는 경우(바로 아래 `elif`)는 이미 올바르게 다루고 있었는데, 그 자매
        # 경로(있지만 고장난 경우)만 놓치고 있었다.
        if generated is not None:
            p.summary, p.body = generated
        elif existing is not None:
            p.summary, p.body = existing.summary, existing.body
        else:
            p.summary, p.body = "", ""
    elif existing is not None:
        p.summary, p.body = existing.summary, existing.body
    else:
        p.summary, p.body = _generate_body(None, p, {}, log)
    profile.save(p)
    log(f"  · {chosen} 등록됨 — DB {len(databases)}개, "
        f"속성 {sum(len(db['properties']) for db in databases)}개")
    return p


def refresh(session, slug: str, *, runtime=None, log=print) -> profile.Profile:
    """스키마만 다시 읽는다. 본문은 `runtime` 을 준 경우에만 재생성한다."""
    old = profile.load(slug)
    _page, databases, pages = _build(session, old.page_id, log)
    old.databases = databases
    old.pages = pages
    caps = types.derive_capabilities(databases)
    if any(node["headings"] for node in pages):
        caps.append("document")
    old.capabilities = caps
    old.schema_fetched_at = date.today().isoformat()
    old.health = "ok"
    if runtime is not None:
        samples = {db["key"]: sample_rows(session, db["data_source_id"],
                                          [prop["name"] for prop in db["properties"]])
                   for db in databases}
        generated = _generate_body(runtime, old, samples, log)
        # 실패(`None`)면 `old.summary`/`old.body` 는 이미 파일에서 읽어온 그대로다
        # — 손대지 않는다(재리뷰 Important 2와 동일한 모양). `runtime is None`
        # 분기(위 docstring)와 마찬가지로 여기서도 "본문은 재생성을 요청했을
        # 때만 바뀐다"는 규율을 지킨다 — 요청했는데 agent 가 죽었다고 지워지면
        # 안 된다.
        if generated is not None:
            old.summary, old.body = generated
    profile.save(old)
    return old
