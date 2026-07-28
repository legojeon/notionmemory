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
