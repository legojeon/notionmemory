"""Notion PAT 보관(keyring) + 실검증. NoteSync notion_oauth.py의 PAT 흐름 축소 이식.

토큰은 keyring(서비스 notionmemory.notion)에만 저장한다 — config.yaml에는 절대 기록 금지.
"""
from __future__ import annotations

import os

import requests
import yaml

SERVICE = "notionmemory.notion"
PAT_ACCOUNT = "personal-access-token"
NOTION_VERSION = "2026-03-11"
API_ME = "https://api.notion.com/v1/users/me"


def save_pat(token: str) -> None:
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PAT 저장에 `pip install keyring`이 필요합니다") from exc
    keyring.set_password(SERVICE, PAT_ACCOUNT, token)


def load_pat() -> str:
    try:
        import keyring
        return keyring.get_password(SERVICE, PAT_ACCOUNT) or ""
    except Exception:  # noqa: BLE001 — keyring 부재/백엔드 오류는 "미연결"로 취급
        return ""


def delete_pat() -> None:
    try:
        import keyring
        keyring.delete_password(SERVICE, PAT_ACCOUNT)
    except Exception:  # noqa: BLE001
        pass


def verify_token(token: str) -> dict:
    """Notion API로 토큰 실검증. 네트워크를 타는 유일한 함수."""
    try:
        r = requests.get(API_ME, headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
        }, timeout=10)
    except requests.RequestException as exc:
        return {"ok": False, "error": f"네트워크 오류: {exc}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"검증 실패(HTTP {r.status_code})"}
    body = r.json()
    name = body.get("name") or (body.get("bot") or {}).get("workspace_name") or ""
    return {"ok": True, "name": name}


def _load_raw(config_path: str) -> dict:
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _write_raw(config_path: str, raw: dict) -> None:
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)


def save_connection_meta(config_path: str, workspace_name: str) -> None:
    raw = _load_raw(config_path)
    integrations = raw.get("integrations") or {}
    notion = integrations.get("notion") or {}
    notion["auth_mode"] = "pat"
    notion["workspace_name"] = workspace_name
    notion["token"] = ""  # 토큰은 keyring에만 — config에 남은 값 제거
    integrations["notion"] = notion
    raw["integrations"] = integrations
    _write_raw(config_path, raw)


def clear_connection_meta(config_path: str) -> None:
    raw = _load_raw(config_path)
    integrations = raw.get("integrations") or {}
    notion = integrations.get("notion") or {}
    notion.pop("auth_mode", None)
    notion.pop("workspace_name", None)
    if "token" in notion:
        notion["token"] = ""
    integrations["notion"] = notion
    raw["integrations"] = integrations
    _write_raw(config_path, raw)
