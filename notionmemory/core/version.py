"""패키지 버전 단일 소스 — pyproject 의 version 이 유일한 진실, 런타임은 설치
메타데이터에서 읽는다(`__version__` 중복을 만들지 않는다).

`--version`, 설치 receipt 각인, SessionStart 드리프트 넛지가 전부 이 하나를 공유한다.
설치 메타데이터가 없으면(예: 소스 트리 직접 실행) 조용히 폴백한다 — 넛지/CLI 가
터지지 않게 하기 위해서다.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    try:
        return version("notionmemory")
    except PackageNotFoundError:
        return "0+unknown"
