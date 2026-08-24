"""문서 편집 — upload_image / add_image: 공통 이미지 저작 원시(notes salvage).

블록-id 렌더/편집 표면(block_markdown/render_blocks/get_block/add_blocks/set_block/
remove_block)은 마크다운 API 로 대체되며 제거됐다 — 회귀 가드는
tests/test_templates_document.py::test_dead_block_helpers_removed 참조.
"""
from tests.skills.test_templates_store import FakeResp, FakeSession


def _resp(status, body):
    return FakeResp(status, body)


def test_upload_image_two_step_direct_upload(tmp_path):
    from notionmemory.skills.templates.document import DocumentStore
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
    ds = DocumentStore(FakeSession({}))
    assert ds.upload_image(tmp_path / "nope.png") is None      # 없음
    empty = tmp_path / "e.png"; empty.write_bytes(b"")
    assert ds.upload_image(empty) is None                       # 0바이트


def test_add_image_uploads_then_appends_image_block(tmp_path):
    from notionmemory.skills.templates.document import DocumentStore
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
    img = tmp_path / "fig.png"; img.write_bytes(b"\x89PNG" + b"0" * 32)
    sess = FakeSession({("POST", "/file_uploads"): _resp(500, {})})
    # 업로드 실패 → 블록 append 안 함(빈 image 블록 방지)
    assert DocumentStore(sess).add_image("pg1", img) is None
    assert all(c[0] != "PATCH" for c in sess.calls)


def test_add_image_returns_truthy_when_patch_succeeds_with_empty_results(tmp_path):
    """PATCH 2xx 성공인데 results 가 비어도(드묾) None 이 아니어야 — CLI 가 '삽입 실패'로
    오보하지 않게(최종 리뷰 Minor)."""
    from notionmemory.skills.templates.document import DocumentStore
    img = tmp_path / "fig.png"
    img.write_bytes(b"\x89PNG" + b"0" * 32)
    sess = FakeSession({
        ("POST", "/file_uploads"): _resp(200, {"id": "up_2", "upload_url": "/file_uploads/up_2/send"}),
        ("POST", "/file_uploads/up_2/send"): _resp(200, {"status": "uploaded"}),
        ("PATCH", "/blocks/pg1/children"): _resp(200, {"results": []})})
    assert DocumentStore(sess).add_image("pg1", img) is not None
