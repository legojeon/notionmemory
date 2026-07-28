"""markdown_to_blocks 스모크 테스트 (NoteSync tests/test_smoke.py 에서 이식, 임포트 경로만 변경)."""
from __future__ import annotations

from notionmemory.core.notion_markdown import markdown_to_blocks


def test_notion_h4_maps_to_h3():
    blocks = markdown_to_blocks("#### 소제목\n\n본문")
    assert blocks[0]["type"] == "heading_3"
    assert not any("####" in str(b) for b in blocks)


def test_markdown_to_notion_blocks():
    # 업로드 없음 → FIG는 callout
    blocks = markdown_to_blocks("# H\n\n- a\n\n> q\n\n```py\nx=1\n```\n\n{{FIG:fig_1}}\n",
                                fig_labels={"fig_1": "f.png"})
    types = {b["type"] for b in blocks}
    assert {"heading_1", "bulleted_list_item", "quote", "code", "callout"} <= types


def test_notion_rich_blocks():
    """표·링크·구분선·체크박스·취소선·중첩 리스트 변환."""
    md = (
        "| 모델 | 크기 |\n| --- | --- |\n| GPT | 큼 |\n| BERT | 중간 |\n\n"
        "참고 [논문](https://arxiv.org/abs/1)\n\n"
        "---\n\n"
        "- [ ] 할 일\n- [x] 끝난 일\n\n"
        "- 상위\n  - 하위1\n  - 하위2\n\n"
        "~~취소~~ 텍스트\n"
    )
    blocks = markdown_to_blocks(md)
    by = {}
    for b in blocks:
        by.setdefault(b["type"], []).append(b)
    # 표
    t = by["table"][0]["table"]
    assert t["table_width"] == 2 and len(t["children"]) == 3 and t["has_column_header"]
    # 구분선 / 체크박스
    assert "divider" in by
    todos = by["to_do"]
    assert any(x["to_do"]["checked"] for x in todos) and any(not x["to_do"]["checked"] for x in todos)
    # 링크 rich_text
    para_link = next(b for b in blocks if b["type"] == "paragraph"
                     and any(rt.get("text", {}).get("link") for rt in b["paragraph"]["rich_text"]))
    assert para_link
    # 중첩 리스트: '상위' 불릿이 children 보유
    parent = next(b for b in by["bulleted_list_item"]
                  if b["bulleted_list_item"].get("children"))
    assert len(parent["bulleted_list_item"]["children"]) == 2
    # 취소선
    assert any(rt.get("annotations", {}).get("strikethrough")
               for b in blocks if b["type"] == "paragraph"
               for rt in b["paragraph"]["rich_text"])


def test_notion_latex_and_inline_fig():
    """LaTeX → equation 블록/인라인 수식, 문장 중간 FIG → 이미지 블록(업로드 시)."""
    md = ("문장 시작 $E=mc^2$ 끝.\n\n"
          "$$\\int_0^1 x\\,dx = \\tfrac12$$\n\n"
          "그림 보면 {{FIG:fig_1}} 이렇다.\n")
    blocks = markdown_to_blocks(md, fig_uploads={"fig_1": "UPLOAD123"})
    # 블록 수식
    assert any(b["type"] == "equation" and "int" in b["equation"]["expression"] for b in blocks)
    # 인라인 수식이 paragraph rich_text 안에 equation 타입으로
    para = next(b for b in blocks if b["type"] == "paragraph")
    assert any(rt.get("type") == "equation" for rt in para["paragraph"]["rich_text"])
    # 문장 중간 FIG가 이미지 블록(file_upload)으로 분리됨 — 리터럴 토큰 잔재 없음
    img = next(b for b in blocks if b["type"] == "image")
    assert img["image"]["file_upload"]["id"] == "UPLOAD123"
    assert not any("{{FIG" in str(b) for b in blocks)
