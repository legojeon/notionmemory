"""가벼운 Markdown -> Notion 블록 변환기.

지원:
  헤딩(1~3), 문단, 불릿/번호 리스트(+2단계 중첩), 체크박스(to_do), 인용, 구분선,
  코드펜스(긴 코드 분할), 표(table), LaTeX 수식(인라인 `$...$` / 블록 `$$...$$`),
  굵게/이탤릭/취소선/인라인코드/링크, 그리고 {{FIG:id}} -> 업로드 이미지 블록(또는 callout).
"""
from __future__ import annotations

import re

FIG_RE = re.compile(r"\{\{FIG:([A-Za-z0-9_]+)\}\}")
# 링크 / 굵게 / 인라인코드 / 취소선 / 이탤릭 / 인라인수식
_INLINE = re.compile(
    r"(\[[^\]]+\]\([^)]+\)|\*\*.+?\*\*|`[^`]+`|~~.+?~~|\*[^*]+\*|\$[^$\n]+\$)"
)
_LINK_RE = re.compile(r"^\[([^\]]+)\]\(([^)]+)\)$")
_DIVIDER_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_TODO_RE = re.compile(r"^(\s*)[-*+]\s+\[([ xX])\]\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUM_RE = re.compile(r"^(\s*)\d+\.\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _rich(text: str) -> list[dict]:
    """인라인 마크다운 -> rich_text 배열. (남은 FIG 토큰은 제거)"""
    if not text:
        return []
    text = FIG_RE.sub("", text)
    out: list[dict] = []
    for tok in _INLINE.split(text):
        if not tok:
            continue
        # 링크
        lm = _LINK_RE.match(tok)
        if lm:
            out.append({"type": "text",
                        "text": {"content": lm.group(1)[:1900], "link": {"url": lm.group(2)}}})
            continue
        # 인라인 수식
        if len(tok) >= 2 and tok.startswith("$") and tok.endswith("$") and not tok.startswith("$$"):
            expr = tok[1:-1].strip()
            if expr:
                out.append({"type": "equation", "equation": {"expression": expr[:1000]}})
            continue
        ann: dict = {}
        content = tok
        if tok.startswith("**") and tok.endswith("**"):
            ann, content = {"bold": True}, tok[2:-2]
        elif tok.startswith("~~") and tok.endswith("~~"):
            ann, content = {"strikethrough": True}, tok[2:-2]
        elif tok.startswith("`") and tok.endswith("`"):
            ann, content = {"code": True}, tok[1:-1]
        elif tok.startswith("*") and tok.endswith("*"):
            ann, content = {"italic": True}, tok[1:-1]
        for i in range(0, len(content), 1900):
            rt = {"type": "text", "text": {"content": content[i:i + 1900]}}
            if ann:
                rt["annotations"] = ann
            out.append(rt)
    return out


def _para(rich):
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": rich or [{"type": "text", "text": {"content": ""}}]}}


def _image_or_callout(fid: str, fig_uploads: dict, fig_labels: dict) -> dict:
    up_id = (fig_uploads or {}).get(fid)
    if up_id:
        return {"object": "block", "type": "image",
                "image": {"type": "file_upload", "file_upload": {"id": up_id}}}
    label = (fig_labels or {}).get(fid, fid)
    return {"object": "block", "type": "callout",
            "callout": {"rich_text": [{"type": "text", "text": {"content": f"[그림] {label}"}}],
                        "icon": {"emoji": "🖼️"}}}


# ---- 리스트(중첩) ----
def _list_marker(line: str):
    for kind, rx in (("todo", _TODO_RE), ("bullet", _BULLET_RE), ("number", _NUM_RE)):
        m = rx.match(line)
        if m:
            indent = len(m.group(1))
            if kind == "todo":
                return indent, kind, m.group(2).lower() == "x", m.group(3)
            return indent, kind, False, m.group(2)
    return None


def _list_block(kind: str, checked: bool, content: str) -> dict:
    rich = _rich(content.strip())
    if kind == "todo":
        return {"object": "block", "type": "to_do", "to_do": {"rich_text": rich, "checked": checked}}
    if kind == "number":
        return {"object": "block", "type": "numbered_list_item", "numbered_list_item": {"rich_text": rich}}
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich}}


def _consume_list(lines: list[str], i: int) -> tuple[list[dict], int]:
    items: list[tuple[int, dict]] = []
    while i < len(lines):
        mk = _list_marker(lines[i])
        if mk is None:
            if lines[i].strip() == "" and i + 1 < len(lines) and _list_marker(lines[i + 1]):
                i += 1
                continue
            break
        indent, kind, checked, content = mk
        # 중첩은 1단계까지만(노션 create children 중첩 한도·전체 실패 방지)
        items.append((min(indent // 2, 1), _list_block(kind, checked, content)))
        i += 1

    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for level, block in items:
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            parent = stack[-1][1]
            parent[parent["type"]].setdefault("children", []).append(block)
        else:
            roots.append(block)
        stack.append((level, block))
    return roots, i


# ---- 표 ----
def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _consume_table(lines: list[str], i: int) -> tuple[dict | None, int]:
    header = _split_row(lines[i])
    width = len(header)
    rows = [header]
    i += 2  # 헤더 + 구분선
    while i < len(lines) and "|" in lines[i] and lines[i].strip():
        cells = _split_row(lines[i])
        cells = (cells + [""] * width)[:width]
        rows.append(cells)
        i += 1
    children = [{"object": "block", "type": "table_row",
                 "table_row": {"cells": [_rich(c) for c in row]}} for row in rows]
    table = {"object": "block", "type": "table",
             "table": {"table_width": width, "has_column_header": True,
                       "has_row_header": False, "children": children}}
    return table, i


def markdown_to_blocks(md: str, fig_uploads: dict[str, str] | None = None,
                       fig_labels: dict[str, str] | None = None) -> list[dict]:
    fig_uploads = fig_uploads or {}
    fig_labels = fig_labels or {}
    md = FIG_RE.sub(lambda m: "\n\n" + m.group(0) + "\n\n", md)

    blocks: list[dict] = []
    lines = md.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 코드펜스
        if line.lstrip().startswith("```"):
            lang = line.lstrip()[3:].strip() or "plain text"
            code_lines = []
            i += 1
            while i < n and not lines[i].lstrip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            code = "\n".join(code_lines)
            rich = [{"type": "text", "text": {"content": code[j:j + 1900]}}
                    for j in range(0, max(len(code), 1), 1900)]
            blocks.append({"object": "block", "type": "code",
                           "code": {"rich_text": rich, "language": _notion_lang(lang)}})
            continue

        if not stripped:
            i += 1
            continue

        # 표 (헤더 다음 줄이 구분선)
        if "|" in stripped and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
            table, i = _consume_table(lines, i)
            if table:
                blocks.append(table)
            continue

        # 구분선
        if _DIVIDER_RE.match(stripped):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # 블록 수식 $$ ... $$
        if stripped.startswith("$$"):
            buf = [stripped]
            closed = stripped.endswith("$$") and len(stripped) > 3
            i += 1
            while not closed and i < n:
                buf.append(lines[i])
                if lines[i].strip().endswith("$$"):
                    i += 1
                    break
                i += 1
            expr = "\n".join(buf).strip().strip("$").strip()
            if expr:
                blocks.append({"object": "block", "type": "equation",
                               "equation": {"expression": expr[:1000]}})
            continue

        # 그림 자리표시자(독립 줄)
        m = FIG_RE.search(stripped)
        if m and FIG_RE.sub("", stripped).strip() == "":
            blocks.append(_image_or_callout(m.group(1), fig_uploads, fig_labels))
            i += 1
            continue

        # 헤딩 (노션은 H3까지 → H4~H6은 H3로 매핑, '####' 텍스트 노출 방지)
        h = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if h:
            key = f"heading_{min(len(h.group(1)), 3)}"
            blocks.append({"object": "block", "type": key, key: {"rich_text": _rich(h.group(2))}})
            i += 1
            continue

        # 인용
        if stripped.startswith(">"):
            blocks.append({"object": "block", "type": "quote",
                           "quote": {"rich_text": _rich(stripped.lstrip("> ").rstrip())}})
            i += 1
            continue

        # 리스트(불릿/번호/체크박스, 중첩 포함)
        if _list_marker(line):
            sub, i = _consume_list(lines, i)
            blocks.extend(sub)
            continue

        blocks.append(_para(_rich(stripped)))
        i += 1

    return blocks


_LANG_MAP = {
    "py": "python", "python": "python", "js": "javascript", "ts": "typescript",
    "cpp": "c++", "c": "c", "java": "java", "sql": "sql", "r": "r",
    "bash": "bash", "sh": "shell", "json": "json", "yaml": "yaml",
    "mermaid": "mermaid",
}


def _notion_lang(lang: str) -> str:
    return _LANG_MAP.get(lang.lower(), "plain text")
