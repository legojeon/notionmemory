"""문서 편집 — blocks→markdown 렌더러. 총체적, 크래시·구조 누출 0(render.plain 규율)."""
import pytest

from notionmemory.skills.templates import document as D
from tests.skills.test_templates_store import FakeResp, FakeSession


def _rt(text):
    return [{"type": "text", "plain_text": text}]


def _block(bid, btype, **body):
    return {"id": bid, "type": btype, btype: body, "has_children": False}


def _para(bid, text):
    return _block(bid, "paragraph", rich_text=_rt(text))


# --- block_markdown: 타입별 마크다운 ---

def test_headings():
    assert D.block_markdown(_block("b", "heading_1", rich_text=_rt("제목"))) == "# 제목"
    assert D.block_markdown(_block("b", "heading_2", rich_text=_rt("소제목"))) == "## 소제목"
    assert D.block_markdown(_block("b", "heading_3", rich_text=_rt("소소제목"))) == "### 소소제목"


def test_paragraph_and_multiple_rich_text_runs():
    b = {"id": "b", "type": "paragraph",
         "paragraph": {"rich_text": [{"plain_text": "좋은 "}, {"plain_text": "자리"}]}}
    assert D.block_markdown(b) == "좋은 자리"


def test_list_items():
    assert D.block_markdown(_block("b", "bulleted_list_item", rich_text=_rt("항목"))) == "- 항목"
    assert D.block_markdown(_block("b", "numbered_list_item", rich_text=_rt("항목"))) == "1. 항목"


def test_to_do_reflects_checked():
    assert D.block_markdown(_block("b", "to_do", rich_text=_rt("할일"), checked=False)) == "- [ ] 할일"
    assert D.block_markdown(_block("b", "to_do", rich_text=_rt("끝"), checked=True)) == "- [x] 끝"


def test_quote_and_callout():
    assert D.block_markdown(_block("b", "quote", rich_text=_rt("인용"))) == "> 인용"
    assert D.block_markdown(_block("b", "callout", rich_text=_rt("노트"))) == "> 노트"


def test_code_is_fenced_with_language():
    b = {"id": "b", "type": "code",
         "code": {"rich_text": _rt("print(1)"), "language": "python"}}
    assert D.block_markdown(b) == "```python\nprint(1)\n```"


def test_divider():
    assert D.block_markdown(_block("b", "divider")) == "---"


def test_toggle_shows_its_own_text():
    assert D.block_markdown(_block("b", "toggle", rich_text=_rt("접기제목"))) == "접기제목"


def test_empty_rich_text_is_empty_string_not_crash():
    assert D.block_markdown(_block("b", "paragraph", rich_text=[])) == ""


def test_unknown_type_is_labeled_never_leaks_structure():
    out = D.block_markdown({"id": "b", "type": "quantum_flux",
                            "quantum_flux": {"nested": {"a": [1, 2]}}, "has_children": False})
    assert out == "[type: quantum_flux]"
    assert "{" not in out and "[1" not in out


def test_block_with_no_type_key_does_not_crash():
    assert D.block_markdown({"id": "b"}) == "[type: ]"


# --- render_blocks: 주석 붙은 다중 줄 ---

def test_render_annotates_each_content_block_with_its_id():
    out = D.render_blocks([_block("b_h", "heading_2", rich_text=_rt("요약")),
                           _para("b_p", "이 논문은 …")])
    lines = out.splitlines()
    assert lines[0] == "[b_h] ## 요약"
    assert lines[1] == "[b_p] 이 논문은 …"


def test_render_shows_child_database_as_reference():
    blocks = [{"id": "db1", "type": "child_database",
               "child_database": {"title": "Papers"}, "has_children": False}]
    assert D.render_blocks(blocks) == "[db: db1] Papers"


def test_render_shows_child_page_as_reference():
    blocks = [{"id": "pg1", "type": "child_page",
               "child_page": {"title": "방법론 노트"}, "has_children": False}]
    assert D.render_blocks(blocks) == "[page: pg1] 방법론 노트"


def test_render_flags_a_block_that_has_children_so_the_agent_can_drill_in():
    b = _block("t1", "toggle", rich_text=_rt("접기"))
    b["has_children"] = True
    out = D.render_blocks([b])
    assert out.startswith("[t1] 접기")
    assert "read t1" in out          # 하위 블록을 열람하려면 그 id 로 read


def test_render_empty_list():
    assert D.render_blocks([]) == "(빈 페이지)"


def test_render_skips_non_dict_elements_without_crashing():
    """비-dict 원소는 건너뛴다(총체적). 크래시·구조 누출 없음."""
    out = D.render_blocks([_para("b1", "정상"), None, "invalid", _para("b2", "정상2")])
    assert isinstance(out, str)
    assert "{" not in out and "[" not in out.split("\n")[0] or "b1" in out
    # 정상인 블록 2개는 출력되고, 비-dict 원소는 건너뛴다
    assert "[b1]" in out
    assert "[b2]" in out


# --- DocumentStore: 라이브 블록 I/O ---

def _para_block(bid, text):
    return {"id": bid, "type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": text}]}, "has_children": False}


def test_add_blocks_converts_markdown_and_appends_returning_ids():
    sess = FakeSession({("PATCH", "/blocks/pg/children"):
                        FakeResp(200, {"results": [{"id": "new1"}, {"id": "new2"}]})})
    ids = D.DocumentStore(sess).add_blocks("pg", "## 요약\n내용")
    body = sess.calls[0][2]
    assert body["children"]           # markdown_to_blocks 로 변환된 블록
    assert ids == ["new1", "new2"]


def test_add_blocks_passes_after_when_given():
    sess = FakeSession({("PATCH", "/blocks/pg/children"): FakeResp(200, {"results": []})})
    D.DocumentStore(sess).add_blocks("pg", "텍스트", after="b_anchor")
    assert sess.calls[0][2]["after"] == "b_anchor"


def test_set_block_patches_the_block_content():
    sess = FakeSession({("GET", "/blocks/b1"):
                        FakeResp(200, {"id": "b1", "type": "paragraph",
                                       "paragraph": {"rich_text": []}}),
                        ("PATCH", "/blocks/b1"): FakeResp(200, {"id": "b1"})})
    D.DocumentStore(sess).set_block("b1", "새 내용")
    patch = [c for c in sess.calls if c[0] == "PATCH"][0][2]
    assert "paragraph" in patch        # 그 블록 타입의 rich_text 를 교체
    # 스텁이 아니라 실제 변환 내용이 PATCH 바디까지 도달했는지 확인
    texts = [rt.get("text", {}).get("content", "") for rt in patch["paragraph"]["rich_text"]]
    assert "".join(texts) == "새 내용"


def test_set_block_multi_block_markdown_warns_and_keeps_only_first_block():
    """리뷰 finding 2 — set 은 첫 블록만 반영하고 나머지는 버린다. 침묵 금지: log 로 경고."""
    sess = FakeSession({("GET", "/blocks/b1"):
                        FakeResp(200, {"id": "b1", "type": "heading_2",
                                       "heading_2": {"rich_text": []}}),
                        ("PATCH", "/blocks/b1"): FakeResp(200, {"id": "b1"})})
    logs = []
    D.DocumentStore(sess, log=logs.append).set_block("b1", "## 제목\n본문")
    patch = [c for c in sess.calls if c[0] == "PATCH"][0][2]
    texts = [rt.get("text", {}).get("content", "") for rt in patch["heading_2"]["rich_text"]]
    assert "".join(texts) == "제목"     # 첫 블록만 반영
    assert any("remove" in m and "add" in m for m in logs)   # 손실 경고가 있어야 한다


def test_set_block_single_block_markdown_emits_no_warning():
    sess = FakeSession({("GET", "/blocks/b1"):
                        FakeResp(200, {"id": "b1", "type": "paragraph",
                                       "paragraph": {"rich_text": []}}),
                        ("PATCH", "/blocks/b1"): FakeResp(200, {"id": "b1"})})
    logs = []
    D.DocumentStore(sess, log=logs.append).set_block("b1", "그냥 한 줄")
    assert logs == []


def test_remove_block_archives_not_hard_delete():
    sess = FakeSession({("DELETE", "/blocks/b1"): FakeResp(200, {"id": "b1", "archived": True})})
    D.DocumentStore(sess).remove_block("b1")
    assert sess.calls[0][0] == "DELETE"


def test_get_block_fetches_one_block():
    sess = FakeSession({("GET", "/blocks/b1"): FakeResp(200, {"id": "b1", "type": "paragraph"})})
    assert D.DocumentStore(sess).get_block("b1")["id"] == "b1"


def test_store_errors_raise_runtimeerror_on_non_2xx():
    sess = FakeSession({("GET", "/blocks/b1"): FakeResp(404, {})})
    with pytest.raises(RuntimeError):
        D.DocumentStore(sess).get_block("b1")


# --- upload_image / add_image: 공통 이미지 저작 원시(notes salvage) ---

def _resp(status, body):
    from tests.skills.test_templates_store import FakeResp
    return FakeResp(status, body)


def test_upload_image_two_step_direct_upload(tmp_path):
    from notionmemory.skills.templates.document import DocumentStore
    from tests.skills.test_templates_store import FakeSession
    img = tmp_path / "fig.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    sess = FakeSession({
        ("POST", "/file_uploads"): _resp(200, {"id": "up_1", "upload_url": "/file_uploads/up_1/send"}),
        ("POST", "/file_uploads/up_1/send"): _resp(200, {"status": "uploaded"})})
    up_id = DocumentStore(sess).upload_image(img)
    assert up_id == "up_1"
    # 2단계: 생성 → 전송
    paths = [c[1] for c in sess.calls]
    assert paths == ["/file_uploads", "/file_uploads/up_1/send"]


def test_upload_image_rejects_missing_and_empty(tmp_path):
    from notionmemory.skills.templates.document import DocumentStore
    from tests.skills.test_templates_store import FakeSession
    ds = DocumentStore(FakeSession({}))
    assert ds.upload_image(tmp_path / "nope.png") is None      # 없음
    empty = tmp_path / "e.png"; empty.write_bytes(b"")
    assert ds.upload_image(empty) is None                       # 0바이트


def test_add_image_uploads_then_appends_image_block(tmp_path):
    from notionmemory.skills.templates.document import DocumentStore
    from tests.skills.test_templates_store import FakeSession
    img = tmp_path / "fig.png"; img.write_bytes(b"\x89PNG" + b"0" * 32)
    sess = FakeSession({
        ("POST", "/file_uploads"): _resp(200, {"id": "up_9", "upload_url": "/file_uploads/up_9/send"}),
        ("POST", "/file_uploads/up_9/send"): _resp(200, {"status": "uploaded"}),
        ("PATCH", "/blocks/pg1/children"): _resp(200, {"results": [{"id": "blk_1", "type": "image"}]})})
    out = DocumentStore(sess).add_image("pg1", img)
    # PATCH 바디의 첫 블록이 file_upload image 블록
    patch = [c for c in sess.calls if c[0] == "PATCH"][0]
    block = patch[2]["children"][0]
    assert block["type"] == "image"
    assert block["image"] == {"type": "file_upload", "file_upload": {"id": "up_9"}}


def test_add_image_returns_none_when_upload_fails(tmp_path):
    from notionmemory.skills.templates.document import DocumentStore
    from tests.skills.test_templates_store import FakeSession
    img = tmp_path / "fig.png"; img.write_bytes(b"\x89PNG" + b"0" * 32)
    sess = FakeSession({("POST", "/file_uploads"): _resp(500, {})})
    # 업로드 실패 → 블록 append 안 함(빈 image 블록 방지)
    assert DocumentStore(sess).add_image("pg1", img) is None
    assert all(c[0] != "PATCH" for c in sess.calls)


def test_add_image_returns_truthy_when_patch_succeeds_with_empty_results(tmp_path):
    """PATCH 2xx 성공인데 results 가 비어도(드묾) None 이 아니어야 — CLI 가 '삽입 실패'로
    오보하지 않게(최종 리뷰 Minor)."""
    from notionmemory.skills.templates.document import DocumentStore
    from tests.skills.test_templates_store import FakeSession
    img = tmp_path / "fig.png"
    img.write_bytes(b"\x89PNG" + b"0" * 32)
    sess = FakeSession({
        ("POST", "/file_uploads"): _resp(200, {"id": "up_2", "upload_url": "/file_uploads/up_2/send"}),
        ("POST", "/file_uploads/up_2/send"): _resp(200, {"status": "uploaded"}),
        ("PATCH", "/blocks/pg1/children"): _resp(200, {"results": []})})
    assert DocumentStore(sess).add_image("pg1", img) is not None
