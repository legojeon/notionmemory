"""UTF-16 캡 — Notion 의 2000자 한도는 코드유닛 기준(이모지=2). 벤치마크가 잡은
실 400("should be ≤ 2000, instead was 2003")의 회귀 가드."""
from notionmemory.core.notion_text import utf16_cap, utf16_chunks, utf16_len


def test_utf16_len_counts_astral_as_two():
    assert utf16_len("abc") == 3
    assert utf16_len("😀") == 2
    assert utf16_len("a😀b") == 4
    assert utf16_len("") == 0


def test_python_slice_overflows_but_cap_does_not():
    # 벤치마크 재현: 1997자 + 이모지 3개 = 파이썬 len 2000, UTF-16 2003
    text = "a" * 1997 + "😀😀😀"
    assert len(text[:2000]) == 2000 and utf16_len(text[:2000]) == 2003   # 옛 버그
    capped = utf16_cap(text)
    assert utf16_len(capped) <= 2000


def test_cap_never_splits_surrogate_pair():
    text = "a" * 1999 + "😀"           # 이모지가 경계에 걸림 — 통째로 빠져야 함
    capped = utf16_cap(text)
    assert capped == "a" * 1999
    assert utf16_len(capped) == 1999


def test_cap_passthrough_when_short():
    assert utf16_cap("짧은 글") == "짧은 글"
    assert utf16_cap("") == ""


def test_chunks_cover_everything_within_limit():
    text = ("한글과 emoji 😀 섞인 줄 " * 500)
    chunks = utf16_chunks(text, 1800)
    assert "".join(chunks) == text
    assert all(utf16_len(c) <= 1800 for c in chunks)


def test_memory_props_excerpt_fits_notion_limit_with_emoji():
    from notionmemory.skills.memory.notion_db import SecondBrainDB
    db = SecondBrainDB.__new__(SecondBrainDB)
    props = db._props({"id": "mem_x", "content": "a" * 1997 + "😀😀😀",
                       "type": "fact"})
    excerpt = props["Excerpt"]["rich_text"][0]["text"]["content"]
    assert utf16_len(excerpt) <= 2000
