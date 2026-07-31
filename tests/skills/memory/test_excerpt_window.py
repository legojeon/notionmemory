"""Excerpt 창 확대 — rich_text 3항목(≈6000 UTF-16 유닛). 항목당 2000유닛 한도는
UTF-16 기준(core.notion_text)이며, 읽기(_plain)는 배열을 이어붙이므로 왕복 무손실."""
from notionmemory.core.notion_text import utf16_len
from notionmemory.skills.memory.notion_db import SecondBrainDB, excerpt_rt, _plain


def test_excerpt_rt_three_chunks_cover_6000_units():
    text = "가" * 5500
    items = excerpt_rt(text)
    assert 1 <= len(items) <= 3
    assert all(utf16_len(i["text"]["content"]) <= 2000 for i in items)
    assert _plain([{"plain_text": i["text"]["content"]} for i in items]) == text[:6000]


def test_excerpt_rt_truncates_beyond_window_and_handles_emoji():
    text = "a" * 7000 + "😀"
    items = excerpt_rt(text)
    assert len(items) == 3
    joined = "".join(i["text"]["content"] for i in items)
    assert joined == text[:6000]          # 창 밖은 잘림(의도된 경계)
    emoji_tail = "b" * 1999 + "😀" + "c" * 4000
    for i in excerpt_rt(emoji_tail):
        assert utf16_len(i["text"]["content"]) <= 2000


def test_excerpt_rt_empty_and_short():
    assert excerpt_rt("") == []
    items = excerpt_rt("짧은 글")
    assert len(items) == 1 and items[0]["text"]["content"] == "짧은 글"


def test_props_excerpt_uses_wide_window():
    db = SecondBrainDB.__new__(SecondBrainDB)
    props = db._props({"id": "mem_x", "type": "fact", "content": "가" * 5000})
    rich = props["Excerpt"]["rich_text"]
    assert len(rich) == 3
    assert "".join(i["text"]["content"] for i in rich) == "가" * 5000
