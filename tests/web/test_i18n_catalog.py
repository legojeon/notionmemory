import json
from pathlib import Path

CAT = Path(__file__).resolve().parents[2] / "notionmemory" / "web" / "assets" / "i18n.json"


def test_en_ko_keysets_identical_and_nonempty():
    data = json.loads(CAT.read_text(encoding="utf-8"))
    assert set(data) == {"en", "ko"}
    assert set(data["en"]) == set(data["ko"]), "en/ko 키셋 불일치 — 번역 누락"
    assert data["en"] and all(v.strip() for v in data["en"].values())
    assert all(v.strip() for v in data["ko"].values())
