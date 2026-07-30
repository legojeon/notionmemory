"""등록된 템플릿에 대한 CRUD — 페이지네이션·health 전이 포함.

**삭제 정책의 안전장치가 여기 산다.** 페이지 단위 404 만 프로필을 지운다. 401/403 은
토큰 만료·integration 제거를 뜻하고 그때 등록 전체를 지우면 재앙이므로, 인증 실패는
평범한 RuntimeError 로 올린다(스펙 §8).
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from notionmemory.core.notion_markdown import markdown_to_blocks
from notionmemory.skills.templates import coerce, filters, profile, render

PAGE_SIZE = 100          # Notion 상한
DEFAULT_LIMIT = 25
ALL_CAP = 1000           # --all 안전 상한 — 닿으면 반드시 알린다


class ProfileGone(RuntimeError):
    """페이지 단위 404 로 프로필을 방금 삭제했다. 호출자는 재등록을 안내한다."""


class TemplateStore:
    def __init__(self, session, log=None):
        self.session = session
        self.log = log or (lambda *_: None)

    # --- HTTP ---

    @staticmethod
    def _auth_error(status: int) -> RuntimeError:
        """401/403 메시지의 유일한 출처. `_req`와 `health_check`의 per-database 루프가
        같은 문구를 각자 들고 있으면(리뷰 지적) 한쪽만 고치고 잊는 drift 가 난다."""
        return RuntimeError(
            f"Notion 인증 실패({status}) — 토큰이 만료됐거나 integration 이 "
            "제거됐습니다. 등록 정보는 그대로 두었습니다.")

    def _req(self, method: str, path: str, *, page_scope: str = "", **kwargs):
        resp = self.session.request(method, path, **kwargs)
        if resp.status_code < 300:
            return resp
        # 401 은 보통 NotionSession.request 가 NotionAuthError 로 먼저 잡는다(재연결
        # 안내가 더 명확해서) — 여기 401 을 남기는 건 방어다. 어느 경로로 401 이 오든
        # 프로필은 지우지 않는다(오직 404 만 지운다). 403(공유 해제)은 여기서만 잡힌다.
        if resp.status_code in (401, 403):
            raise self._auth_error(resp.status_code)
        if resp.status_code == 404 and page_scope:
            profile.delete(page_scope)
            raise ProfileGone(
                f"'{page_scope}' 템플릿 페이지에 접근할 수 없어(404) 등록을 해제했습니다 — "
                "삭제됐거나 integration 공유가 해제된 경우입니다. "
                "`notionmemory templates register <URL>` 로 다시 등록하세요.")
        raise RuntimeError(
            f"Notion {method} {path} 실패: {resp.status_code} {resp.text[:200]}")

    # --- 프로필 조회 헬퍼 ---

    @staticmethod
    def _live_db(p: profile.Profile, db_key: str) -> dict:
        db = profile.find_db(p, db_key)
        if db.get("missing"):
            raise ValueError(
                f"'{db_key}' 데이터베이스는 Notion 에서 사라졌습니다 — "
                f"`notionmemory templates refresh {p.slug}` 로 다시 확인하세요")
        return db

    @staticmethod
    def _prop_names(db: dict) -> list:
        return [prop.get("name", "") for prop in db.get("properties") or []]

    def relation_resolver(self, p: profile.Profile) -> Callable[[str, str], str]:
        """제목 → page_id. **쓰기와 조회가 같은 것을 쓴다** — 사용자는 어느 쪽이든
        회사 이름을 치지 page id 를 치지 않는다(스펙 §5·§6)."""
        def resolve(db_key: str, title: str) -> str:
            db = self._live_db(p, db_key)
            title_prop = db.get("title_property") or "Name"
            data = self._req("POST", f"/data_sources/{db['data_source_id']}/query",
                             json={"filter": {"property": title_prop,
                                              "title": {"equals": title}},
                                   "page_size": 10}).json()
            results = data.get("results") or []     # `_fetch` 처럼 `results: null` 도 total 하게
            if len(results) == 1:
                return results[0]["id"]
            if not results:
                raise ValueError(
                    f"'{db_key}'에서 '{title}'를 찾지 못했습니다 — 먼저 그 행을 만들거나 "
                    "정확한 제목을 확인하세요(자동 생성은 하지 않습니다)")
            names = ", ".join(
                render.plain((r.get("properties") or {}).get(title_prop) or {})
                for r in results)
            raise ValueError(f"'{db_key}'에서 '{title}'가 여러 건입니다: {names}")
        return resolve

    # --- 조회 ---

    # `_fetch` 가 멈춘 이유. cap 도달과 서버 정체는 서로 다른 문제라 다른 말을 듣는다 —
    # 하나로 뭉치면 "cap 에서 잘림, 조건을 좁히세요" 라는 확신에 찬 거짓말이 정체
    # 상황에도 그대로 나간다(리뷰 지적).
    CAPPED = "cap"      # 진짜로 cap 행을 채웠고, 서버는 더 줄 수 있었다
    STALLED = "stall"   # 서버가 진행을 못 시켜줘서 cap 이전에 멈췄다

    def _fetch(self, data_source_id: str, payload: dict, cap: int) -> tuple[list, str | None]:
        """cap 행에 도달하거나 서버가 더 못 준다고 할 때까지 순회한다.

        반환하는 두 번째 값은 멈춘 이유다: `None`(완료), `CAPPED`(cap 도달),
        `STALLED`(서버가 진행 불가). 둘 다 "절단"이지만 사용자에게 할 말이 다르다 —
        cap 이면 조건을 좁히라고 하면 되지만, 정체면 좁힐 조건이 없다(응답 자체가
        문제였다). 이 둘을 같은 bool 하나로 뭉쳐 반환하면 호출부가 실제로는 정체인
        상황에서도 "cap 에서 잘림" 이라고 확신에 차 거짓말한다(리뷰 지적).

        **진행이 없으면 반드시 멈춘다.** 실기 재현된 두 회귀:
        - `has_more: true` + 커서 없음(`next_cursor` 부재/null) — `if cursor:` 가 falsy라
          다음 요청이 커서 없이 나가고, 서버는 다시 첫 페이지를 준다. cap 까지 같은
          페이지를 반복 수집해 "1000건에서 잘림"이라는 확신에 찬 거짓말이 된다.
        - `has_more: true` + `results: []` — 빈 페이지는 `len(rows)` 를 전혀 늘리지
          않으므로 cap 도달 조건이 영원히 안 걸린다. 초당 수십만 요청으로 그냥 돈다.

        둘 다 "완료"가 아니라 "절단"(`STALLED`)으로 보고한다 — 조용한 절단 금지는
        cap 에 닿았을 때만이 아니라 서버가 진행을 못 시켜줄 때도 적용된다.

        **의도적으로 과잉 보고하는 경계 하나:** 커서가 유효한 채로 온 빈 중간 페이지
        (`results: []` 인데 `next_cursor` 는 있음)도 `not page_rows` 조건에 걸려
        여기서 멈춘다. 이건 진행 불가능이 아니라 커서로 계속 진행할 수 있는 정상적인
        빈 페이지일 수 있다 — Notion 이 실제로 가끔 이런 응답을 낸다. 그래도 멈추는
        쪽을 택했다: 무한 루프(위 두 회귀)와 정상적인 빈 중간 페이지를 이 함수 혼자서는
        구분할 수 없고, 절단을 항상 있는 그대로 보고하므로(조용히 삼키지 않으므로)
        과잉 보고의 대가가 작다. 놓친 게 아니라 고른 경계다.
        """
        rows, cursor = [], None
        while True:
            body = dict(payload)
            body["page_size"] = min(PAGE_SIZE, cap - len(rows))
            if cursor:
                body["start_cursor"] = cursor
            data = self._req("POST", f"/data_sources/{data_source_id}/query",
                             json=body).json()
            page_rows = data.get("results") or []      # `results: null` 도 total 하게
            rows += page_rows
            if len(rows) >= cap:
                reached_more = data.get("has_more", False) or len(rows) > cap
                return rows[:cap], (self.CAPPED if reached_more else None)
            if not data.get("has_more"):
                return rows, None
            cursor = data.get("next_cursor")
            if not cursor or not page_rows:
                # 커서가 없거나 이번 페이지가 비었는데 has_more 는 true — 서버가
                # 더는 전진시켜줄 수 없다. 계속 돌면 위 두 회귀 중 하나이므로 여기서
                # 멈추고 정체로 알린다(cap 이 아니다 — cap 근처에도 못 갔을 수 있다).
                return rows, self.STALLED

    def query(self, p: profile.Profile, db_key: str, *, wheres=(), search: str = "",
              sorts=(), limit: int = DEFAULT_LIMIT, fetch_all: bool = False,
              fields: list | None = None) -> dict:
        db = self._live_db(p, db_key)
        names = self._prop_names(db)
        if fields:
            # 검증 겸 캐노니컬화(오타면 제안 + refresh 안내) — 공백 무시 폴백으로
            # `마감일 `(끝공백) 이 매칭됐을 때 render.flatten 이 페이지 속성을 사용자가
            # 친 이름으로 찾으면 그 열만 조용히 빈 값이 된다.
            names = [profile.find_prop(db, name)["name"] for name in fields]
        payload = filters.compile_query(db, wheres=list(wheres), search=search,
                                        sorts=list(sorts),
                                        resolve_relation=self.relation_resolver(p))
        cap = ALL_CAP if fetch_all else max(1, limit)
        pages, reason = self._fetch(db["data_source_id"], payload, cap)
        return {"rows": [render.flatten(pg, names) for pg in pages], "fields": names,
                "capped": reason == self.CAPPED, "stalled": reason == self.STALLED,
                "cap": cap, "sorted": bool(sorts)}

    def count(self, p: profile.Profile, db_key: str, *, wheres=(), search: str = "") -> int:
        db = self._live_db(p, db_key)
        payload = filters.compile_query(db, wheres=list(wheres), search=search, sorts=[],
                                        resolve_relation=self.relation_resolver(p))
        pages, reason = self._fetch(db["data_source_id"], payload, ALL_CAP)
        # 반환 타입은 `-> int` 로 고정이다(CLI 계약) — 절단 신호를 실을 채널이 없으니
        # `log` 를 쓴다. cap 도달과 서버 정체는 다른 말을 듣는다(리뷰 지적) — 둘 다
        # "정확한 개수 아님" 이지만, 정체를 "1000건 이상"이라고 하면 실제로는 7건일
        # 수도 있는데 확신에 찬 하한을 지어내는 거짓말이 된다.
        if reason == self.CAPPED:
            self.log(f"'{db_key}' 개수가 {ALL_CAP}건에서 잘렸습니다 — 실제로는 "
                     f"{ALL_CAP}건 이상입니다(정확한 개수 아님)")
        elif reason == self.STALLED:
            self.log(f"'{db_key}' 개수 조회가 Notion 의 불완전한 응답으로 중단됐습니다 — "
                     f"확인된 건 {len(pages)}건뿐이고 정확한 전체 개수가 아닙니다")
        return len(pages)

    # --- 쓰기 ---

    def _properties(self, p, db, pairs, allow_new_option):
        return coerce.build_properties(db, list(pairs),
                                       resolve_relation=self.relation_resolver(p),
                                       allow_new_option=allow_new_option)

    def add(self, p: profile.Profile, db_key: str, pairs, *, notes: str = "",
            allow_new_option: bool = False) -> dict:
        db = self._live_db(p, db_key)
        props = self._properties(p, db, pairs, allow_new_option)   # 실패는 HTTP 이전에
        blocks = markdown_to_blocks(notes) if notes else []
        page = self._req("POST", "/pages", json={
            "parent": {"data_source_id": db["data_source_id"]},
            "properties": props, "children": blocks[:100]}).json()
        page_id = page.get("id", "")
        if not page_id:
            # 페이지는 이미 Notion 에 생성됐다 — 이 파일에서 유일하게 실제 작업 손실로
            # 이어지는 경로라 `page['id']` KeyError 로 죽이지 않는다(§5). id 없이는
            # 나머지 블록을 붙일 곳도, 이어지는 update/archive 가 때릴 곳도 없으니
            # 빈 id 로 조용히 `{'id': '', ...}` 를 돌려주지 않고 명확히 멈춘다.
            # 응답에 `url` 이 이미 들어 있으니(같은 페이로드) 흘리지 않고 넘긴다 —
            # 데이터 손실에 가까운 상황에서 "Notion 에서 직접 찾아보세요"보다
            # 손에 쥔 링크를 건네는 쪽이 훨씬 낫다(리뷰 지적).
            url = page.get("url") or "(url 도 응답에 없습니다)"
            lost = (f"{len(blocks) - 100}개 블록을 추가로 붙이지 못했습니다. "
                    if len(blocks) > 100 else "")
            raise RuntimeError(
                f"Notion 이 페이지 id 없이 응답했습니다 — 페이지는 생성됐습니다. {lost}"
                f"URL: {url}")
        for k in range(100, len(blocks), 100):
            self._req("PATCH", f"/blocks/{page_id}/children",
                      json={"children": blocks[k:k + 100]})
        return {"id": page_id, "url": page.get("url", "")}

    def update(self, p: profile.Profile, db_key: str, row_id: str, pairs, *,
               allow_new_option: bool = False) -> dict:
        db = self._live_db(p, db_key)
        if not list(pairs):
            raise ValueError("변경할 항목이 없습니다 — --set \"속성=값\" 을 하나 이상 지정하세요")
        props = self._properties(p, db, pairs, allow_new_option)
        self._req("PATCH", f"/pages/{row_id}", json={"properties": props})
        return {"id": row_id}

    def archive(self, p: profile.Profile, db_key: str, row_id: str) -> bool:
        self._live_db(p, db_key)
        # 하드 딜리트는 없다 — 에이전트가 남의 데이터를 지우는 것은 되돌릴 수 있어야 한다.
        # 행 404 는 page_scope 를 넘기지 않으므로 프로필 삭제를 유발하지 않는다.
        self._req("PATCH", f"/pages/{row_id}", json={"in_trash": True})
        return True

    # --- health ---

    # 점검 자체가 실패했을 때의 반환값. `Profile.health` 기본값이 "ok" 라, 한 번도
    # 점검한 적 없는 갓 등록된 프로필에서 전체 장애(503 등)를 만나면 `return p.health`
    # 는 "ok" 를 돌려준다 — "점검했고 건강하다"와 "점검을 못 했다"가 반환값에서
    # 구분이 안 된다(리뷰 지적). 디스크의 `p.health` 는 그대로 보존하되(§3), 이번
    # 호출의 반환값만은 확실히 "ok"/"degraded"/"trashed" 어느 것도 아니게 한다.
    UNKNOWN = "unknown"

    def health_check(self, p: profile.Profile) -> str:
        page = self._req("GET", f"/pages/{p.page_id}", page_scope=p.slug).json()
        if page.get("in_trash"):
            p.health = "trashed"
            p.health_checked_at = date.today().isoformat()
            profile.save(p)
            return p.health

        # 플래그는 로컬에 먼저 모으고 루프가 끝까지 성공했을 때만 `p`에 반영한다
        # (§4) — 중간에서 401/403 이 나면 이미 확인한 db 도 in-memory 프로필에
        # 반쯤 마크된 채 남으면 안 된다. 오늘은 아무도 그 상태를 저장하지 않아
        # 무해하지만, 훗날 refresh/list 가 이 객체를 그대로 저장하면 미완료 점검
        # 결과가 디스크로 샌다.
        # `db["key"]` 로 색인하지 않는다 — 이 모듈은 다른 곳에서는 `.get` 로 방어적
        # 이다(`profile.find_db` 등). key 가 없는 db dict 는 `db["key"]` 자체가
        # KeyError 로 죽고, 중복된 key 를 가진 두 db 는 서로의 상태를 덮어써 조용히
        # 하나로 뭉개진다(리뷰 지적) — 리스트 인덱스는 둘 다 겪지 않는다.
        missing: dict[int, bool] = {}
        for i, db in enumerate(p.databases):
            resp = self.session.request("GET", f"/data_sources/{db['data_source_id']}")
            # 401 은 대개 NotionSession 이 상류에서 NotionAuthError 로 잡는다 — 여기
            # 401 은 방어적 backstop(둘 다 프로필을 안 지운다). 403 은 여기서 처리.
            if resp.status_code in (401, 403):
                raise self._auth_error(resp.status_code)
            if resp.status_code not in (200, 404):
                # 200 도 404 도 아닌 상태(예: 503) — 서버 장애인지 실제 소실인지 이
                # 응답만으로는 알 수 없다. missing=False 로 단정해 "정상"이라 기록하면
                # 전체 장애가 클린 판정으로 남는다(§3, 조용한 절단 금지와 같은 원칙의
                # health 판이다). degraded 로 단정하지도 않는다 — 그건 이미 옳게
                # 선택된 안전한 방향이라 건드리지 않는다. 이 회차는 미완료로 남기고
                # 이전 health/health_checked_at 을 디스크·in-memory 모두 그대로
                # 보존한다. 다만 반환값은 `p.health` 를 그대로 돌려주지 않는다 —
                # 갓 등록된 프로필은 기본값이 "ok"라 전체 장애를 "정상"으로 보고하는
                # 셈이 된다. `log` 로 실패를 알리고 `UNKNOWN` 을 돌려줘 호출자가
                # "점검했고 건강함"과 "점검 못 함"을 구분할 채널을 갖게 한다.
                self.log(f"'{p.slug}' health 점검이 '{db.get('key', '?')}' 데이터베이스 "
                         f"확인 중 실패했습니다({resp.status_code}) — 이전 상태를 보존하고 "
                         "이번 점검은 미완료로 보고합니다")
                return self.UNKNOWN
            missing[i] = resp.status_code == 404

        for i, db in enumerate(p.databases):
            db["missing"] = missing[i]
        p.health = "degraded" if any(missing.values()) else "ok"
        p.health_checked_at = date.today().isoformat()
        profile.save(p)
        return p.health
