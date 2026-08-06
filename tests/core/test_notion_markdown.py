"""공유 마크다운→Notion 블록 변환기(구 notes/markdown_notion, core로 이전)."""
from notionmemory.core.notion_markdown import markdown_to_blocks


def test_heading_and_paragraph():
    blocks = markdown_to_blocks("# 제목\n\n본문 문단")
    types = [b["type"] for b in blocks]
    assert "heading_1" in types and "paragraph" in types


def test_module_location_is_core_not_notes():
    import notionmemory.core.notion_markdown as m
    assert m.__name__ == "notionmemory.core.notion_markdown"


def test_mermaid_fence_renders_as_diagram():
    # ```mermaid 은 plain text 로 떨어지면 Notion 이 다이어그램으로 그리지 않는다 —
    # 언어가 그대로 'mermaid' 로 실려야 코드블록이 다이어그램으로 렌더된다.
    blocks = markdown_to_blocks("```mermaid\nflowchart LR\n  A --> B\n```")
    code = [b for b in blocks if b["type"] == "code"]
    assert len(code) == 1
    assert code[0]["code"]["language"] == "mermaid"
