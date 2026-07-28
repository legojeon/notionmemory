"""설치 영수증 — 무엇을 실제로 심었는지의 기록. teardown 1층이 이걸 읽는다."""
from __future__ import annotations

import json

from notionmemory.core import paths
from notionmemory.core.install.spec import ArtifactSpec

VERSION = 1


def read() -> list[dict]:
    try:
        raw = json.loads(paths.receipt_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list(raw.get("artifacts") or [])


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
                                "artifacts": sorted(merged.values(), key=lambda e: e["id"])},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
