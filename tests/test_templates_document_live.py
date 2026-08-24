import os

import pytest

from notionmemory.core.notion_client import NotionSession
from notionmemory.skills.templates.document import DocumentStore, MarkdownEditError

pytestmark = [
    pytest.mark.live_notion,
    pytest.mark.skipif(
        os.getenv("NOTIONMEMORY_LIVE") != "1",
        reason="live Notion smoke; set NOTIONMEMORY_LIVE=1 to run",
    ),
]


def test_markdown_roundtrip_against_real_notion():
    """create → append → edit → delete → replace → read → archive. 스크래치 페이지 자기정리."""
    sess = NotionSession()
    parent = sess.request(
        "POST",
        "/search",
        json={"filter": {"value": "page", "property": "object"}, "page_size": 1},
    ).json()["results"][0]["id"]
    store = DocumentStore(sess, log=lambda *_: None)
    page = store.add_page(parent, "live-smoke", "## H\n\nunique line\n")
    pid = page["id"]
    try:
        store.append(pid, "\n\nappended tail\n")
        assert "appended tail" in store.read(pid)
        store.edit(pid, "unique line", "EDITED line")
        assert "EDITED line" in store.read(pid)
        with pytest.raises(MarkdownEditError):
            store.edit(pid, "does-not-exist", "x")
        store.delete(pid, "appended tail")
        assert "appended tail" not in store.read(pid)
        store.replace(pid, "# Fresh\n\nrewritten\n")
        assert "rewritten" in store.read(pid)
    finally:
        sess.request("DELETE", f"/blocks/{pid}")  # archive (in_trash)
