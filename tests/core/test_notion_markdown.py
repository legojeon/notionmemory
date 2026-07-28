"""공유 마크다운→Notion 블록 변환기(구 notes/markdown_notion, core로 이전)."""
from notionmemory.core.notion_markdown import markdown_to_blocks


def test_heading_and_paragraph():
    blocks = markdown_to_blocks("# 제목\n\n본문 문단")
    types = [b["type"] for b in blocks]
    assert "heading_1" in types and "paragraph" in types


def test_module_location_is_core_not_notes():
    import notionmemory.core.notion_markdown as m
    assert m.__name__ == "notionmemory.core.notion_markdown"
