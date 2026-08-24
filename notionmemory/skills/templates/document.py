"""문서 편집 — Notion 페이지 본문을 마크다운으로 읽고, 마크다운으로 쓰기.

Notion Markdown Content API(`GET/PATCH /pages/:id/markdown`)를 그대로 감싼다:
`read`/`current_markdown` 은 페이지 전체를 마크다운 한 덩어리로 받고,
`append`/`replace`/`edit`/`delete` 는 find/replace 또는 전체 재작성으로 쓴다.
블록-id 를 다루지 않으므로 렌더러도, 살아있는 block-id 도 필요 없다 — API 가
본문을 통째로 마크다운 문자열로 주고받는다.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

TRUNCATION_MARKER = (
    "[본문이 잘렸습니다 — 페이지가 커서 전체를 읽지 못했습니다. "
    "replace(전체 재작성)는 거부됩니다. edit/append 로 부분 수정하세요.]"
)


class PageNotFound(RuntimeError):
    """대상 페이지/블록이 404 — 삭제됐거나 통합에 공유되지 않음. 일반 실패와 구분해
    호출부(library read)가 색인 지연삭제로 자가치유할 수 있게 한다. RuntimeError
    하위라 이를 따로 잡지 않는 호출부(templates)는 기존처럼 메시지를 출력한다."""


class MarkdownEditError(RuntimeError):
    """Markdown API 편집이 대상 텍스트를 못 찾음(0건) 또는 모호함(다중). API 400
    메시지를 그대로 담아 CLI 가 exit 2 + 사람이 읽는 안내로 변환한다."""


class DocumentStore:
    """등록된 페이지의 본문 I/O(Markdown Content API). 게이트(미리보기·확인)는 CLI
    책임 — 여기선 원시 동작만. `delete` 도 하드 딜리트가 아니라 `edit` 로 대상 텍스트를
    빈 문자열로 바꾸는 것(update_content) — DB 쪽이 하드 딜리트를 안 쓰는 것과 같은 규율.
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

    def _get_markdown(self, page_id: str) -> tuple[str, bool]:
        data = self._req("GET", f"/pages/{page_id}/markdown").json()
        return data.get("markdown", ""), bool(data.get("truncated"))

    def read(self, page_id: str) -> str:
        md, truncated = self._get_markdown(page_id)
        if truncated:
            md = (md + "\n\n" + TRUNCATION_MARKER) if md else TRUNCATION_MARKER
        return md

    def current_markdown(self, page_id: str) -> str:
        """미리보기용 — truncation 마커 없이 현재 본문만."""
        return self._get_markdown(page_id)[0]

    def add_page(self, parent_page_id: str, title: str, markdown: str = "") -> dict:
        body = {"parent": {"page_id": parent_page_id},
                "properties": {"title": {"title": [{"text": {"content": title}}]}},
                "markdown": markdown}
        data = self._req("POST", "/pages", json=body).json()
        return {"id": data.get("id", ""), "url": data.get("url", "")}

    def _markdown_patch(self, page_id: str, body: dict) -> None:
        resp = self.session.request("PATCH", f"/pages/{page_id}/markdown", json=body)
        if resp.status_code == 404:
            raise PageNotFound(
                f"Notion PATCH /pages/{page_id}/markdown 실패: 404 (페이지 없음/공유 안 됨)")
        if resp.status_code == 400:
            try:
                msg = resp.json().get("message", "") or resp.text[:200]
            except Exception:
                msg = resp.text[:200]
            if "match" in msg.lower():
                raise MarkdownEditError(msg)
            raise RuntimeError(f"Notion PATCH 실패: 400 {msg}")
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Notion PATCH /pages/{page_id}/markdown 실패: {resp.status_code} {resp.text[:200]}")

    def append(self, page_id: str, markdown: str) -> None:
        self._markdown_patch(page_id, {
            "type": "insert_content",
            "insert_content": {"content": markdown, "position": {"type": "end"}}})

    def replace(self, page_id: str, markdown: str) -> None:
        _, truncated = self._get_markdown(page_id)
        if truncated:
            raise RuntimeError(
                "이 페이지는 read 가 잘립니다(본문이 큼) — 전체 재작성(replace)은 잘린 "
                "꼬리를 잃을 위험이라 거부합니다. edit/append 로 부분 수정하세요.")
        self._markdown_patch(page_id, {
            "type": "replace_content", "replace_content": {"new_str": markdown}})

    def edit(self, page_id: str, find: str, replace: str, all_matches: bool = False) -> None:
        upd: dict = {"old_str": find, "new_str": replace}
        if all_matches:
            upd["replaceAllMatches"] = True
        self._markdown_patch(page_id, {
            "type": "update_content", "update_content": {"content_updates": [upd]}})

    def delete(self, page_id: str, find: str, all_matches: bool = False) -> None:
        self.edit(page_id, find, "", all_matches=all_matches)

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
