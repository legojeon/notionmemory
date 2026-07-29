"""언어 해석 + 메시지 조회. config `language` 키가 단일 소스, 기본 en."""
from __future__ import annotations

VALID = ("en", "ko")
DEFAULT = "en"


def language(config) -> str:
    lang = config.get("language")
    return lang if lang in VALID else DEFAULT


def t(catalog: dict, key: str, lang: str, **fmt) -> str:
    table = catalog.get(lang) or {}
    msg = table.get(key)
    if msg is None:
        msg = (catalog.get(DEFAULT) or {}).get(key, key)
    return msg.format(**fmt) if fmt else msg


def tui(lang, key, en, **fmt):
    """대시보드 서버 문자열: ko 오버레이. lang=='ko' 이고 UI_KO 에 key 있으면 ko, 아니면 en(소스)."""
    from notionmemory.core.messages import UI_KO
    s = UI_KO.get(key) if lang == "ko" else None
    if s is None:
        s = en
    return s.format(**fmt) if fmt else s
