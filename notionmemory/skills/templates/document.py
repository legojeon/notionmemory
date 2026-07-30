"""문서 편집 — Notion 블록 트리를 마크다운으로 읽고, 마크다운으로 쓰기.

`read` 출력은 각 블록을 `[<block-id>] <마크다운>` 으로 주석 달아 에이전트가 어느
블록을 고칠지 정확히 지목하게 한다 — 본문은 API 로 검색이 안 되고, 편집엔 살아있는
block-id 가 필요하기 때문이다.

렌더러는 **총체적**이다: 모르는 블록 타입도 `[type: xxx]` 라벨로 내보내고 절대
크래시하거나 JSON 구조를 누출하지 않는다(`render.plain` 과 같은 규율). Notion 이 새
블록 타입을 추가해도, 우리가 못 그리는 블록이 빈 칸이나 traceback 이 아니라 눈에
보이는 라벨로 남는다.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from notionmemory.core.notion_markdown import markdown_to_blocks

# 마크다운 접두사가 있는 콘텐츠 블록 타입 → 접두사
_PREFIX = {
    "heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
    "bulleted_list_item": "- ", "numbered_list_item": "1. ",
    "quote": "> ", "callout": "> ",
    "paragraph": "", "toggle": "",
}


def _plain(rich) -> str:
    """rich_text 배열 → 평문. 비-dict 원소는 건너뛴다(총체적)."""
    return "".join(r.get("plain_text", "") for r in (rich or []) if isinstance(r, dict))


def block_markdown(block: dict) -> str:
    """콘텐츠 블록 하나 → 마크다운 한 줄(들). id 는 붙이지 않는다.

    모르는 타입은 `[type: <t>]` 라벨. 절대 크래시·구조 누출 없음.
    """
    btype = (block or {}).get("type", "")
    body = (block or {}).get(btype) or {}
    rich = body.get("rich_text") if isinstance(body, dict) else None
    text = _plain(rich)

    if btype == "to_do":
        mark = "x" if body.get("checked") else " "
        return f"- [{mark}] {text}"
    if btype == "code":
        lang = body.get("language", "") or "plain text"
        return f"```{lang}\n{text}\n```"
    if btype == "divider":
        return "---"
    if btype in _PREFIX:
        return _PREFIX[btype] + text
    # 콘텐츠로 그릴 수 없는(또는 모르는) 타입 — 눈에 보이는 라벨로만 남긴다
    return f"[type: {btype}]"


def render_blocks(blocks: list) -> str:
    """블록 리스트 → `[<id>] <md>` 주석 다중 줄.

    `child_database`/`child_page` 는 참조 줄(에이전트가 query/read 로 따로 다뤄라),
    하위 블록이 있는 블록은 그 id 로 read 하라고 안내한다.
    """
    if not blocks:
        return "(빈 페이지)"
    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):  # 비-dict 원소는 건너뛴다(총체적)
            continue
        bid = block.get("id", "")
        btype = block.get("type", "")
        if btype == "child_database":
            title = (block.get("child_database") or {}).get("title", "")
            lines.append(f"[db: {bid}] {title}")
            continue
        if btype == "child_page":
            title = (block.get("child_page") or {}).get("title", "")
            lines.append(f"[page: {bid}] {title}")
            continue
        line = f"[{bid}] {block_markdown(block)}"
        if block.get("has_children"):
            line += f"  (하위 블록 있음 — read {bid} 로 열람)"
        lines.append(line)
    return "\n".join(lines)


DOC_PAGE_SIZE = 100
DOC_NODE_CAP = 500     # read 한 번이 읽는 블록 총량 상한 — 거대한 페이지 방어


class PageNotFound(RuntimeError):
    """대상 페이지/블록이 404 — 삭제됐거나 통합에 공유되지 않음. 일반 실패와 구분해
    호출부(library read)가 색인 지연삭제로 자가치유할 수 있게 한다. RuntimeError
    하위라 이를 따로 잡지 않는 호출부(templates)는 기존처럼 메시지를 출력한다."""


class DocumentStore:
    """등록된 페이지의 본문 블록 I/O. 게이트(미리보기·확인)는 CLI 책임 — 여기선 원시 동작만.

    삭제는 하드 딜리트가 아니라 archive 다(`DELETE /blocks/{id}` 는 Notion 에서
    휴지통 이동이며 히스토리로 복원된다) — DB 쪽이 하드 딜리트를 안 쓰는 것과 같은 규율.
    """

    def __init__(self, session, log=None):
        self.session = session
        self.log = log or (lambda *_: None)

    def _req(self, method: str, path: str, **kwargs):
        resp = self.session.request(method, path, **kwargs)
        if resp.status_code == 404:
            raise PageNotFound(f"Notion {method} {path} 실패: 404 (페이지가 없거나 공유 안 됨)")
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Notion {method} {path} 실패: {resp.status_code} {resp.text[:200]}")
        return resp

    def read(self, page_id: str) -> str:
        """그 id 의 직속 children 을 라이브 조회 → 마크다운+block-id.

        페이지네이션 진행 불변식 가드: `has_more` 인데 이번 요청이 새 블록을 못
        늘렸거나 커서가 없으면 멈춘다(store._fetch·walk_structure 와 같은 규율 —
        서버가 진행을 못 시켜주는 모양에서 무한 루프하지 않는다).

        캡 도달 판정은 `>=`(엄격한 `>` 아님) — DOC_PAGE_SIZE(100) 가 DOC_NODE_CAP(500)
        을 나누어떨어지므로, 500 블록을 넘는 문서는 흔히 정확히 500 에서 착지하고
        `has_more` 만 true 로 남는다. 그 모양에서도 잘렸다는 사실을 경고해야 한다 —
        캡에 도달했지만 서버에 더 없다면(has_more=false) 경고하지 않는다(오탐 금지).
        """
        blocks: list = []
        seen: set = set()
        cursor = None
        while len(blocks) < DOC_NODE_CAP:
            params = {"page_size": DOC_PAGE_SIZE}
            if cursor:
                params["start_cursor"] = cursor
            data = self._req("GET", f"/blocks/{page_id}/children", params=params).json()
            page_blocks = data.get("results") or []
            before = len(seen)
            for b in page_blocks:
                bid = b.get("id", "")
                if bid and bid not in seen:
                    seen.add(bid)
                    blocks.append(b)
            has_more = bool(data.get("has_more"))
            if len(blocks) >= DOC_NODE_CAP:
                # 하드 캡 도달. 이번 페이지가 상한을 넘겼거나(overshoot), 정확히 캡에
                # 맞아떨어졌는데도 서버에 더 남아있으면(has_more) 진짜로 잘린 것이다 —
                # 조용히 자르지 않고 눈에 보이게 경고한다. 캡=문서 끝(has_more=false)이면
                # 잘린 게 아니므로 경고하지 않는다.
                overshoot = len(blocks) > DOC_NODE_CAP
                blocks = blocks[:DOC_NODE_CAP]
                if overshoot or has_more:
                    self.log(
                        f"문서 본문이 {DOC_NODE_CAP}블록을 넘습니다 — read 는 처음 {DOC_NODE_CAP}개만"
                        " 보여줍니다(전체가 아님).")
                break
            if not has_more or len(seen) == before:
                break
            cursor = data.get("next_cursor")
            if not cursor or not page_blocks:
                break
        return render_blocks(blocks)

    def get_block(self, block_id: str) -> dict:
        return self._req("GET", f"/blocks/{block_id}").json()

    def add_blocks(self, page_id: str, markdown: str, after: str | None = None) -> list:
        body: dict = {"children": markdown_to_blocks(markdown)}
        if after:
            body["after"] = after
        data = self._req("PATCH", f"/blocks/{page_id}/children", json=body).json()
        return [b.get("id", "") for b in data.get("results", [])]

    def set_block(self, block_id: str, markdown: str) -> None:
        """블록 내용 교체. Notion 은 블록 타입 제자리 변경을 지원하지 않으므로,
        그 블록의 현재 타입 아래 rich_text 만 새 내용으로 바꾼다(마크다운의 첫
        블록에서 rich_text 를 취한다 — 타입까지 바꾸려면 remove + add)."""
        cur = self.get_block(block_id)
        btype = cur.get("type", "paragraph")
        new_blocks = markdown_to_blocks(markdown) or [
            {"type": "paragraph", "paragraph": {"rich_text": []}}]
        if len(new_blocks) > 1:
            # 침묵 데이터 손실 금지 — 첫 블록만 반영되고 나머지는 버려짐을 알린다.
            self.log(
                f"set 은 블록 하나의 내용만 바꿉니다 — 마크다운이 {len(new_blocks)}개 블록으로"
                " 변환돼 첫 블록만 반영되고 나머지는 버려집니다. 여러 블록을 바꾸려면"
                " remove + add 를 쓰세요.")
        first = new_blocks[0]
        new_rich = (first.get(first.get("type", ""), {}) or {}).get("rich_text", [])
        self._req("PATCH", f"/blocks/{block_id}",
                  json={btype: {"rich_text": new_rich}})

    def remove_block(self, block_id: str) -> None:
        self._req("DELETE", f"/blocks/{block_id}")     # archive(휴지통), 하드 딜리트 아님

    def add_page(self, parent_page_id: str, title: str, markdown: str = "") -> dict:
        body = {"parent": {"page_id": parent_page_id},
                "properties": {"title": {"title": [{"text": {"content": title}}]}},
                "children": markdown_to_blocks(markdown) if markdown else []}
        data = self._req("POST", "/pages", json=body).json()
        return {"id": data.get("id", ""), "url": data.get("url", "")}

    def upload_image(self, path) -> str | None:
        """Notion Direct Upload: (1) file_upload 생성 → (2) 바이트 전송. 성공 시 id.

        notes 에서 salvage — 이미지 삽입은 notes 전용이 아니라 어떤 저작에도 필요한
        공통 원시다(스펙 §4). 실패는 로그로 노출(조용한 실패 방지). 파일 크롭·생성은
        에이전트 몫이고 여기선 '받은 파일을 Notion 에 올리는' 것만 한다."""
        path = Path(path)
        if not path.exists():
            self.log(f"  ! 이미지 파일 없음: {path.name}")
            return None
        size = path.stat().st_size
        if size == 0:
            self.log(f"  ! 이미지 파일이 비어있음: {path.name}")
            return None
        if size > 20 * 1024 * 1024:
            self.log(f"  ! 이미지 20MB 초과(노션 단일 업로드 한도): {path.name}")
            return None
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        r1 = self.session.request("POST", "/file_uploads",
                                  json={"filename": path.name, "content_type": mime})
        if r1.status_code >= 300:
            self.log(f"  ! 업로드 생성 실패({r1.status_code}) {path.name}: {r1.text[:160]}")
            return None
        up = r1.json()
        up_id = up["id"]
        up_url = up.get("upload_url") or f"/file_uploads/{up_id}/send"
        # 파일 핸들이 아니라 bytes 로 넘긴다: 위 20MB 가드로 크기가 제한돼 안전하고,
        # 재시도(429/5xx)가 같은 kwargs 로 requests 를 재호출할 때 EOF 소진된 핸들이
        # 빈 파트를 보내는 문제를 피한다(§3 리팩터 byte-send 교훈).
        r2 = self.session.request("POST", up_url,
                                  files={"file": (path.name, path.read_bytes(), mime)},
                                  timeout=120)
        if r2.status_code >= 300:
            self.log(f"  ! 업로드 전송 실패({r2.status_code}) {path.name}: {r2.text[:160]}")
            return None
        try:
            status = r2.json().get("status", "")
        except Exception:      # noqa: BLE001
            status = ""
        if status and status != "uploaded":
            self.log(f"  ! 업로드 상태가 'uploaded' 아님({status}) {path.name}")
            return None
        return up_id

    def add_image(self, page_id: str, image_path, *, after: str | None = None,
                  caption: str = "") -> dict | None:
        """이미지를 업로드해 그 페이지에 image 블록으로 append. 업로드 실패 시 None
        (빈/깨진 image 블록을 남기지 않는다)."""
        up_id = self.upload_image(image_path)
        if not up_id:
            return None
        image = {"type": "file_upload", "file_upload": {"id": up_id}}
        if caption:
            image["caption"] = [{"type": "text", "text": {"content": caption}}]
        block = {"object": "block", "type": "image", "image": image}
        body = {"children": [block]}
        if after:
            body["after"] = after
        resp = self._req("PATCH", f"/blocks/{page_id}/children", json=body)
        results = resp.json().get("results") or []
        # PATCH 가 2xx 로 성공했으면 블록은 만들어진 것 — results 가 비어도(드묾) None 을
        # 돌려주면 CLI 가 '삽입 실패'로 오보한다. 업로드 실패(위 None)와 구분되게 {} 반환.
        return results[0] if results else {}
