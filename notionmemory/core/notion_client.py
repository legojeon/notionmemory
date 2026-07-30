"""공용 Notion HTTP 게이트웨이 — 429/5xx 지수 백오프 단일 관문.

memory(notion_db)와 notes(notion_exporter) 양쪽이 모든 Notion HTTP 호출에 사용한다
(설계 §3.2 core/notion_client). files= 전달 시 multipart용으로 Content-Type을 자동 제거한다.
"""
from __future__ import annotations

import time as _time

import requests

from notionmemory.core import notion_auth
from notionmemory.core.notion_auth import NOTION_VERSION as VERSION

API = "https://api.notion.com/v1"
MAX_RETRIES = 5


class NotionAuthError(RuntimeError):
    """Notion 이 401 로 토큰을 거부 — 만료·회전·폐기. 일반 API 실패와 달리 명확한
    재연결 안내를 담는다. RuntimeError 하위라 CLI 의 기존 except 블록들이 그대로
    잡아 메시지를 출력한다(detect-on-use)."""


def _auth_error_message() -> str:
    """config 언어에 맞춘 재연결 안내. 실패해도(파손 config 등) 영어 폴백."""
    try:
        from notionmemory.core import i18n, messages, paths
        from notionmemory.core.config import Config
        lang = i18n.language(Config.load(str(paths.config_path())))
        return i18n.t(messages.CATALOG, "notion.auth_invalid", lang)
    except Exception:
        return ("Notion rejected the token (HTTP 401) — reconnect in the settings "
                "dashboard, then re-check with `notionmemory status`.")


class NotionSession:
    def __init__(self, token: str = "", log=None):
        self.token = token or notion_auth.load_pat()
        if not self.token:
            raise RuntimeError("Notion 토큰이 없습니다. 대시보드에서 Notion을 연결하세요.")
        self.log = log or (lambda *_: None)
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": VERSION,
            "Content-Type": "application/json",
        }

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = path if path.startswith("http") else f"{API}{path}"
        timeout = kwargs.pop("timeout", 60)
        headers = self._headers
        if "files" in kwargs:
            # multipart boundary는 requests가 정해야 하므로 JSON Content-Type을 뺀다
            headers = {k: v for k, v in headers.items() if k != "Content-Type"}
        for attempt in range(MAX_RETRIES):
            resp = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == MAX_RETRIES - 1:
                    break
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else min(2 ** attempt, 30)
                except (ValueError, TypeError):
                    delay = min(2 ** attempt, 30)
                _time.sleep(delay)
                continue
            break
        if resp.status_code == 401:
            raise NotionAuthError(_auth_error_message())
        return resp
