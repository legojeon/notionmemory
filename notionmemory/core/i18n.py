"""언어 해석 + 메시지 조회. config `language` 키가 단일 소스, 기본 en."""
from __future__ import annotations

VALID = ("en", "ko")
DEFAULT = "en"
# 선택 UI(온보딩·CLI·대시보드)가 제시하는 저장 언어 목록. `language` 는 "메모리가
# 어떤 언어로 적히는가"(consolidate 가 원시값을 템플릿에 통과)이고, UI 문구는 카탈로그가
# 있는 VALID 로만 클램프된다 — zh/ja 를 고르면 메모리는 그 언어, UI 는 영어 폴백.
OUTPUT_LANGS = ("en", "ko", "zh", "ja")


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
