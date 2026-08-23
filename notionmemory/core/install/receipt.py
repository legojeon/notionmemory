"""설치 영수증 — 무엇을 실제로 심었는지의 기록. teardown 1층이 이걸 읽는다."""
from __future__ import annotations

import json

from notionmemory.core import paths, version
from notionmemory.core.install.spec import ArtifactSpec

VERSION = 1


def _raw() -> dict:
    try:
        return json.loads(paths.receipt_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read() -> list[dict]:
    return list(_raw().get("artifacts") or [])


def package_version() -> str | None:
    """마지막 `notionmemory install` 이 각인한 패키지 버전. 구 receipt(필드 없음)나
    receipt 부재면 None — 드리프트 판정이 "알 수 없음 → 침묵"으로 안전하게 떨어진다."""
    return _raw().get("package_version") or None


def write(specs: list[ArtifactSpec]) -> None:
    """설치 성공분만 기록. 같은 id 는 마지막 것으로 덮어써 중복을 만들지 않는다."""
    merged = {e["id"]: e for e in read()}
    for s in specs:
        merged[s.id] = {"id": s.id, "owner": s.owner, "handler": s.handler,
                        "target": s.target, "path": str(s.path),
                        "markers": list(s.markers)}
    path = paths.receipt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": VERSION,
                                "package_version": version.package_version(),
                                "artifacts": sorted(merged.values(), key=lambda e: e["id"])},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
