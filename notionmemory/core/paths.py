"""설치·설정 경로 해석 — 체크아웃 위치에 의존하지 않는다.

config 는 XDG(`~/.config/notionmemory/`), 상태·큐·영수증은 `~/.local/state/notionmemory/`.
레포 루트 config.yaml 은 마이그레이션 원본으로만 읽고 지우지 않는다.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

APP = "notionmemory"


def home() -> Path:
    """사용자 홈. 다른 모듈도 이걸 쓴다 — 상태/설정 경로에서 거꾸로 추론하지 말 것
    (그 경로가 XDG 변수를 존중하게 되는 순간 추론이 조용히 틀린다)."""
    return Path(os.environ.get("HOME") or Path.home())


def config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else home() / ".config"
    return base / APP


def config_path() -> Path:
    return config_dir() / "config.yaml"


def state_dir() -> Path:
    return home() / ".local" / "state" / APP


def receipt_path() -> Path:
    return state_dir() / "install-receipt.json"


def legacy_repo_config() -> Path:
    """이 패키지가 레포 체크아웃 안에 있을 때의 `<repo>/config.yaml`."""
    return Path(__file__).resolve().parents[2] / "config.yaml"


def migrate_config() -> str:
    """레포 config.yaml → XDG 1회 복사. 수행한 일을 1줄로 반환(없으면 "")."""
    target = config_path()
    if target.exists():
        return ""
    legacy = legacy_repo_config()
    if not legacy.is_file():
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, target)
    return f"config 이전: {legacy} → {target} (원본은 보존했습니다)"
