"""훅 두 개가 공유하는 설정 판정."""
from __future__ import annotations

from notionmemory.core import paths


def capture_mode() -> str:
    """`skills.memory.capture_mode`. 읽지 못하면 기본값 auto.

    manual 이면 `remember --auto` 가 거부되므로(cli.py 의 fail-closed 정책) 저장을
    권하는 문구 자체를 내지 않는다 — 실행할 수 없는 일을 시키는 안내는 소음이다.
    """
    try:
        import yaml
        raw = yaml.safe_load(paths.config_path().read_text(encoding="utf-8")) or {}
        return str(((raw.get("skills") or {}).get("memory") or {})
                   .get("capture_mode") or "auto")
    except Exception:
        return "auto"
