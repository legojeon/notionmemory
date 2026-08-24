# templates 문서편집 → Markdown Content API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** templates 페이지 본문 편집을 블록-id 주소지정에서 Notion Markdown Content API 기반 텍스트 주소지정으로 이관한다.

**Architecture:** `DocumentStore`를 마크다운 연산(read/add_page/append/replace/edit/delete)으로 재작성하고, 편집은 `PATCH /pages/:id/markdown`의 텍스트 매치(update_content)로 수행한다. 파괴적 연산은 CLI에서 `read` 기반 로컬 미리보기 + `--yes` 게이트로 감싼다. 업로드 이미지 삽입만 블록 API에 남긴다.

**Tech Stack:** Python 3.13, requests, pytest. Notion API 버전 `2026-03-11`(이미 전송 중).

**Spec:** `docs/superpowers/specs/2026-08-25-templates-markdown-api-design.md`

## Global Constraints

- Notion 클라이언트는 `NotionSession`(`notionmemory/core/notion_client.py`) 하나로만 HTTP를 탄다. 새 엔드포인트도 `self.session.request(method, path, **kw)`로 호출.
- archive는 `DELETE /blocks/{id}`(in_trash), 하드딜리트 금지.
- 파괴적 연산(replace/edit/delete)은 `--yes` 없으면 **변이 호출 0건 + 미리보기 + exit 2**.
- 마크다운 입력은 `_text_or_file`(인라인/`--markdown-file`/stdin)로 받는다(기존 헬퍼, `cli.py:535`).
- 설치 계약(`tests/test_artifact_contract.py`) 무영향 — 새 ArtifactSpec 없음.
- `core/notion_markdown.markdown_to_blocks`는 memory/library가 아직 쓰므로 **삭제 금지**.
- 대상 지정은 `<slug|page-id>`: `templates_introspect.extract_page_id(target)`가 비면 slug로 보고 `templates_profile.load(target).page_id` 사용.

## File Structure

- Modify: `notionmemory/skills/templates/document.py` — `DocumentStore` 마크다운 연산 재작성, `MarkdownEditError` 추가, 블록 렌더/블록-id 연산 제거, 이미지 연산·`_req`·`PageNotFound` 유지.
- Modify: `notionmemory/cli.py` — templates 서브파서(`read`/`block`/`page` → `read`/`append`/`replace`/`edit`/`delete`/`page`) + 핸들러 재작성 + `_resolve_page_target` 헬퍼.
- Modify: `notionmemory/agent_skills/templates/SKILL.md` — 문서편집 섹션 텍스트-주소지정 워크플로우로 재작성.
- Modify: `pyproject.toml` — `live_notion` 마커 등록.
- Create: `tests/test_templates_document.py` — DocumentStore 마크다운 연산 유닛테스트(가짜 세션).
- Create: `tests/test_templates_document_live.py` — `live_notion` 마커 라이브 스모크.
- Modify: `tests/test_cli_templates.py` — 새 verb + `--yes` 게이트 테스트.

---

### Task 1: DocumentStore.read (markdown API) + truncation

**Files:**
- Modify: `notionmemory/skills/templates/document.py`
- Test: `tests/test_templates_document.py`

**Interfaces:**
- Consumes: `NotionSession.request`, 기존 `_req`/`PageNotFound`.
- Produces: `TRUNCATION_MARKER: str`; `DocumentStore._get_markdown(page_id) -> tuple[str, bool]`; `DocumentStore.read(page_id) -> str`; `DocumentStore.current_markdown(page_id) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_templates_document.py
from notionmemory.skills.templates import document as D


class FakeResp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body or {}
        self.text = text
    def json(self):
        return self._body


class FakeSession:
    """responses: callable(method, path, kwargs) -> FakeResp, or a list popped in order."""
    def __init__(self, responses):
        self.calls = []
        self._responses = responses
    def request(self, method, path, **kw):
        self.calls.append((method, path, kw))
        r = self._responses
        return r(method, path, kw) if callable(r) else r.pop(0)


def _store(responses):
    return D.DocumentStore(FakeSession(responses), log=lambda *_: None)


def test_read_returns_markdown_field():
    s = _store(lambda m, p, k: FakeResp(200, {"markdown": "# T\n\nbody", "truncated": False}))
    assert s.read("pid") == "# T\n\nbody"
    assert s.session.calls[0][0] == "GET"
    assert s.session.calls[0][1] == "/pages/pid/markdown"


def test_read_appends_truncation_marker_when_truncated():
    s = _store(lambda m, p, k: FakeResp(200, {"markdown": "partial", "truncated": True}))
    out = s.read("pid")
    assert "partial" in out
    assert D.TRUNCATION_MARKER in out


def test_current_markdown_never_adds_marker():
    s = _store(lambda m, p, k: FakeResp(200, {"markdown": "partial", "truncated": True}))
    assert s.current_markdown("pid") == "partial"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_templates_document.py -q`
Expected: FAIL — `AttributeError` (`TRUNCATION_MARKER`/`_get_markdown`/`current_markdown` 미정의) 또는 read가 여전히 블록 기반.

- [ ] **Step 3: Implement in document.py**

모듈 상단(기존 `markdown_to_blocks` import 아래)에 상수 추가:

```python
TRUNCATION_MARKER = (
    "[본문이 잘렸습니다 — 페이지가 커서 전체를 읽지 못했습니다. "
    "replace(전체 재작성)는 거부됩니다. edit/append 로 부분 수정하세요.]"
)
```

`DocumentStore.read`(기존 116-161)를 아래로 교체:

```python
    def _get_markdown(self, page_id: str) -> tuple[str, bool]:
        data = self._req("GET", f"/pages/{page_id}/markdown").json()
        return data.get("markdown", ""), bool(data.get("truncated"))

    def read(self, page_id: str) -> str:
        md, truncated = self._get_markdown(page_id)
        if truncated:
            md = (md + "\n\n" + TRUNCATION_MARKER) if md else TRUNCATION_MARKER
        return md

    def current_markdown(self, page_id: str) -> str:
        """미리보기용 — truncation 마커 없이 현재 본문만."""
        return self._get_markdown(page_id)[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_templates_document.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add notionmemory/skills/templates/document.py tests/test_templates_document.py
git commit -m "feat(templates): read page body via Markdown API with truncation marker"
```

---

### Task 2: DocumentStore write backbone — add_page, append, replace

**Files:**
- Modify: `notionmemory/skills/templates/document.py`
- Test: `tests/test_templates_document.py`

**Interfaces:**
- Consumes: Task 1 `_get_markdown`, `current_markdown`; `_req`.
- Produces: `DocumentStore.add_page(parent_page_id, title, markdown="") -> dict`; `DocumentStore.append(page_id, markdown) -> None`; `DocumentStore.replace(page_id, markdown) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_templates_document.py
def test_add_page_posts_markdown_body():
    s = _store(lambda m, p, k: FakeResp(200, {"id": "new", "url": "http://x"}))
    r = s.add_page("parent", "Title", "# Body")
    assert r == {"id": "new", "url": "http://x"}
    method, path, kw = s.session.calls[0]
    assert (method, path) == ("POST", "/pages")
    body = kw["json"]
    assert body["parent"] == {"page_id": "parent"}
    assert body["markdown"] == "# Body"
    assert body["properties"]["title"]["title"][0]["text"]["content"] == "Title"


def test_append_uses_insert_content_end():
    s = _store(lambda m, p, k: FakeResp(200, {}))
    s.append("pid", "more text")
    method, path, kw = s.session.calls[0]
    assert (method, path) == ("PATCH", "/pages/pid/markdown")
    assert kw["json"] == {"type": "insert_content",
                          "insert_content": {"content": "more text",
                                             "position": {"type": "end"}}}


def test_replace_sends_replace_content_when_not_truncated():
    resps = [FakeResp(200, {"markdown": "old", "truncated": False}),  # _get_markdown
             FakeResp(200, {})]                                        # PATCH
    s = _store(resps)
    s.replace("pid", "brand new")
    patch_call = s.session.calls[1]
    assert patch_call[0] == "PATCH"
    assert patch_call[2]["json"] == {"type": "replace_content",
                                     "replace_content": {"new_str": "brand new"}}


def test_replace_refuses_when_truncated():
    import pytest
    s = _store([FakeResp(200, {"markdown": "partial", "truncated": True})])
    with pytest.raises(RuntimeError):
        s.replace("pid", "brand new")
    # 변이 PATCH 는 절대 나가지 않는다 — GET 하나만.
    assert len(s.session.calls) == 1
    assert s.session.calls[0][0] == "GET"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_templates_document.py -q`
Expected: FAIL — `append`/`replace` 미정의, 또는 `add_page`가 여전히 `children=markdown_to_blocks`.

- [ ] **Step 3: Implement in document.py**

기존 `add_page`(195-200)를 아래로 교체하고 `append`/`replace` 추가:

```python
    def add_page(self, parent_page_id: str, title: str, markdown: str = "") -> dict:
        body = {"parent": {"page_id": parent_page_id},
                "properties": {"title": {"title": [{"text": {"content": title}}]}},
                "markdown": markdown}
        data = self._req("POST", "/pages", json=body).json()
        return {"id": data.get("id", ""), "url": data.get("url", "")}

    def append(self, page_id: str, markdown: str) -> None:
        self._markdown_patch(page_id, {
            "type": "insert_content",
            "insert_content": {"content": markdown, "position": {"type": "end"}}})

    def replace(self, page_id: str, markdown: str) -> None:
        _, truncated = self._get_markdown(page_id)
        if truncated:
            raise RuntimeError(
                "이 페이지는 read 가 잘립니다(본문이 큼) — 전체 재작성(replace)은 잘린 "
                "꼬리를 잃을 위험이라 거부합니다. edit/append 로 부분 수정하세요.")
        self._markdown_patch(page_id, {
            "type": "replace_content", "replace_content": {"new_str": markdown}})
```

`_markdown_patch`는 Task 3에서 정의한다. 이 태스크의 `append`/`replace` 테스트가
그것을 필요로 하므로, **Task 3의 `_markdown_patch` 정의를 이 커밋에 함께 포함**한다
(아래 Task 3 Step 3의 `_markdown_patch` 코드를 지금 추가). `edit`/`delete`는 Task 3에서.

`_markdown_patch` (지금 추가):

```python
    def _markdown_patch(self, page_id: str, body: dict) -> None:
        resp = self.session.request("PATCH", f"/pages/{page_id}/markdown", json=body)
        if resp.status_code == 404:
            raise PageNotFound(
                f"Notion PATCH /pages/{page_id}/markdown 실패: 404 (페이지 없음/공유 안 됨)")
        if resp.status_code == 400:
            try:
                msg = resp.json().get("message", "") or resp.text[:200]
            except Exception:
                msg = resp.text[:200]
            if "match" in msg.lower():
                raise MarkdownEditError(msg)
            raise RuntimeError(f"Notion PATCH 실패: 400 {msg}")
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Notion PATCH /pages/{page_id}/markdown 실패: {resp.status_code} {resp.text[:200]}")
```

`MarkdownEditError`도 Task 3 Step 3에서 정의하지만 `_markdown_patch`가 참조하므로
지금 함께 추가(모듈에 클래스 하나): `PageNotFound` 정의 아래에

```python
class MarkdownEditError(RuntimeError):
    """Markdown API 편집이 대상 텍스트를 못 찾음(0건) 또는 모호함(다중). API 400
    메시지를 그대로 담아 CLI 가 exit 2 + 사람이 읽는 안내로 변환한다."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_templates_document.py -q`
Expected: PASS (7 passed 누계).

- [ ] **Step 5: Commit**

```bash
git add notionmemory/skills/templates/document.py tests/test_templates_document.py
git commit -m "feat(templates): add_page/append/replace via Markdown API (+ truncated refusal)"
```

---

### Task 3: DocumentStore surgical ops — edit, delete, error mapping

**Files:**
- Modify: `notionmemory/skills/templates/document.py`
- Test: `tests/test_templates_document.py`

**Interfaces:**
- Consumes: Task 2 `_markdown_patch`, `MarkdownEditError`.
- Produces: `DocumentStore.edit(page_id, find, replace, all_matches=False) -> None`; `DocumentStore.delete(page_id, find, all_matches=False) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_templates_document.py
def test_edit_sends_update_content():
    s = _store([FakeResp(200, {})])
    s.edit("pid", "old text", "new text")
    method, path, kw = s.session.calls[0]
    assert (method, path) == ("PATCH", "/pages/pid/markdown")
    assert kw["json"] == {"type": "update_content", "update_content":
                          {"content_updates": [{"old_str": "old text", "new_str": "new text"}]}}


def test_edit_all_sets_replace_all_matches():
    s = _store([FakeResp(200, {})])
    s.edit("pid", "x", "y", all_matches=True)
    upd = s.session.calls[0][2]["json"]["update_content"]["content_updates"][0]
    assert upd["replaceAllMatches"] is True


def test_edit_no_match_raises_markdown_edit_error():
    import pytest
    s = _store([FakeResp(400, {"message": "No matches found for zzz."})])
    with pytest.raises(D.MarkdownEditError):
        s.edit("pid", "zzz", "y")


def test_edit_multi_match_raises_markdown_edit_error():
    import pytest
    s = _store([FakeResp(400, {"message": 'Multiple matches found for "dup". Found 2 matches.'})])
    with pytest.raises(D.MarkdownEditError):
        s.edit("pid", "dup", "y")


def test_delete_sends_empty_new_str():
    s = _store([FakeResp(200, {})])
    s.delete("pid", "remove me")
    upd = s.session.calls[0][2]["json"]["update_content"]["content_updates"][0]
    assert upd == {"old_str": "remove me", "new_str": ""}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_templates_document.py -q`
Expected: FAIL — `edit`/`delete` 미정의.

- [ ] **Step 3: Implement in document.py**

`replace` 아래에 추가:

```python
    def edit(self, page_id: str, find: str, replace: str, all_matches: bool = False) -> None:
        upd: dict = {"old_str": find, "new_str": replace}
        if all_matches:
            upd["replaceAllMatches"] = True
        self._markdown_patch(page_id, {
            "type": "update_content", "update_content": {"content_updates": [upd]}})

    def delete(self, page_id: str, find: str, all_matches: bool = False) -> None:
        self.edit(page_id, find, "", all_matches=all_matches)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_templates_document.py -q`
Expected: PASS (12 passed 누계).

- [ ] **Step 5: Commit**

```bash
git add notionmemory/skills/templates/document.py tests/test_templates_document.py
git commit -m "feat(templates): edit/delete via update_content, fail loudly on 0/multi match"
```

---

### Task 4: Remove dead block-rendering code

**Files:**
- Modify: `notionmemory/skills/templates/document.py`
- Test: `tests/test_templates_document.py` (전체 재실행으로 회귀 없음 확인)

**Interfaces:**
- Consumes: 없음(삭제만).
- Produces: 없음. `upload_image`/`add_image`/`_req`/`PageNotFound`/`MarkdownEditError`는 **유지**.

- [ ] **Step 1: Write the guard test**

```python
# append to tests/test_templates_document.py
def test_dead_block_helpers_removed():
    # 블록-id 렌더/편집 표면은 제거됐다(마크다운 API 로 대체).
    assert not hasattr(D, "render_blocks")
    assert not hasattr(D, "block_markdown")
    for gone in ("get_block", "add_blocks", "set_block", "remove_block"):
        assert not hasattr(D.DocumentStore, gone)


def test_image_ops_retained():
    assert hasattr(D.DocumentStore, "upload_image")
    assert hasattr(D.DocumentStore, "add_image")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_templates_document.py::test_dead_block_helpers_removed -q`
Expected: FAIL — 심볼이 아직 존재.

- [ ] **Step 3: Delete dead code in document.py**

제거 대상: module-level `_PREFIX`(20-25), `_plain`(28-30), `block_markdown`(33-54),
`render_blocks`(57-83), `DOC_PAGE_SIZE`/`DOC_NODE_CAP`(86-87), 그리고 `DocumentStore`의
`get_block`/`add_blocks`/`set_block`/`remove_block`(163-193). `markdown_to_blocks`
import(17)도 이 파일에선 더 안 쓰면 제거. 모듈 docstring(1-11)의 블록-id 설명을 새
동작(마크다운 API)으로 갱신. **유지**: `PageNotFound`, `MarkdownEditError`, `_req`,
`_get_markdown`/`read`/`current_markdown`/`add_page`/`append`/`replace`/`edit`/`delete`/
`_markdown_patch`, `upload_image`/`add_image`(그 안의 `PATCH /blocks/:id/children`는 유지).

- [ ] **Step 4: Run full document tests + templates suite**

Run: `./venv/bin/python -m pytest tests/test_templates_document.py tests/test_cli_templates.py -q`
Expected: 문서 유닛테스트 PASS. `test_cli_templates.py`는 이 시점에 옛 verb를 참조해 실패할 수 있다 — Task 5/6에서 갱신하므로, 여기서는 `tests/test_templates_document.py`만 초록이면 통과로 본다(다음 커밋 전 `import notionmemory.cli` 가 깨지지 않는지만 확인).

Run: `./venv/bin/python -c "import notionmemory.skills.templates.document"`
Expected: import 성공(NameError 없음).

- [ ] **Step 5: Commit**

```bash
git add notionmemory/skills/templates/document.py tests/test_templates_document.py
git commit -m "refactor(templates): drop block-render/block-id editing surface"
```

---

### Task 5: CLI non-destructive verbs — read, append, page add + target resolver

**Files:**
- Modify: `notionmemory/cli.py`
- Test: `tests/test_cli_templates.py`

**Interfaces:**
- Consumes: `DocumentStore.read/append/add_page`, `templates_introspect.extract_page_id`, `templates_profile.load`, `_text_or_file`.
- Produces: `_resolve_page_target(target: str) -> str`; CLI verbs `templates read <slug|page-id>`, `templates append <slug|page-id> --markdown/-file`, `templates page add <parent> --title …`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli_templates.py`의 기존 read/block 테스트가 옛 표면을 참조하면 이 태스크에서
새 표면으로 교체한다. 새 테스트(가짜 세션 주입은 기존 파일 패턴을 따르되, 없으면 아래처럼):

```python
# tests/test_cli_templates.py — 추가/교체
from notionmemory import cli


def test_resolve_page_target_passthrough_id():
    pid = "3b2cf80747f2811c9cbcccdbb63225e2"
    assert cli._resolve_page_target(pid) == pid  # 32-hex → 그대로(dashless)


def test_read_prints_markdown(monkeypatch, capsys):
    class S:
        def __init__(self, *a, **k): pass
        def read(self, pid): return "# Doc\n\nhello"
    monkeypatch.setattr(cli, "DocumentStore", lambda *a, **k: S())
    monkeypatch.setattr(cli, "NotionSession", lambda *a, **k: object())
    monkeypatch.setattr(cli, "_resolve_page_target", lambda t: "pid")
    assert cli.main(["templates", "read", "pid"]) == 0
    assert "# Doc" in capsys.readouterr().out


def test_append_calls_store(monkeypatch, capsys):
    calls = {}
    class S:
        def append(self, pid, md): calls["append"] = (pid, md)
    monkeypatch.setattr(cli, "DocumentStore", lambda *a, **k: S())
    monkeypatch.setattr(cli, "NotionSession", lambda *a, **k: object())
    monkeypatch.setattr(cli, "_resolve_page_target", lambda t: "pid")
    assert cli.main(["templates", "append", "slug", "--markdown", "more"]) == 0
    assert calls["append"] == ("pid", "more")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_cli_templates.py -q`
Expected: FAIL — `append` 파서 없음(argparse SystemExit 2) / `_resolve_page_target` 미정의.

- [ ] **Step 3: Implement in cli.py**

(a) `_resolve_page_target` 헬퍼 추가(`_templates_read` 위, 517 근처):

```python
def _resolve_page_target(target: str) -> str:
    """`<slug|page-id>` → page_id. URL/ID 면 그대로, 아니면 등록 slug 의 루트 페이지."""
    pid = templates_introspect.extract_page_id(target)
    if pid:
        return pid
    p = templates_profile.load(target)   # 미등록이면 ValueError → exit 2
    if not p.page_id:
        raise ValueError(
            f"'{target}' 은 프롬프트 전용 템플릿이라 연결 페이지가 없습니다 — "
            "읽거나 편집할 page-id 를 직접 지정하세요.")
    return p.page_id
```

(b) `_templates_read`(518-532)를 교체:

```python
def _templates_read(args) -> int:
    target = _resolve_page_target(args.target)
    store = DocumentStore(NotionSession(), log=print)
    print(store.read(target))
    return 0
```

(c) `_templates_append` 신규:

```python
def _templates_append(args) -> int:
    md = _text_or_file(args.markdown, args.markdown_file)
    if md is None:
        print("--markdown 또는 --markdown-file 이 필요합니다")
        return 2
    target = _resolve_page_target(args.target)
    DocumentStore(NotionSession(), log=print).append(target, md)
    print(f"추가됨: {target}")
    return 0
```

(d) `_templates_page`(602-612)는 유지하되 `add_page`가 이미 마크다운 기반(Task 2)이라
변경 불필요. 확인만.

(e) argparse(977-996): `read`/`block` 정의를 교체. `read`:

```python
    trd = tpl_sub.add_parser("read")
    trd.add_argument("target")            # <slug|page-id>
    tap = tpl_sub.add_parser("append")
    tap.add_argument("target")
    tap.add_argument("--markdown", default=None)
    tap.add_argument("--markdown-file", default="",
                     help="마크다운을 파일에서 읽는다(`-`=stdin)")
```

`block` 서브파서(980-996) 전체 삭제(Task 6에서 replace/edit/delete 추가).

(f) 디스패치(`_cmd_templates`, 677-682): `read`/`append` 라우팅, `block` 제거:

```python
    if args.action == "read":
        return _templates_read(args)
    if args.action == "append":
        return _templates_append(args)
    if args.action == "page":
        return _templates_page(args)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_cli_templates.py -q`
Expected: 새 read/append 테스트 PASS. (replace/edit/delete 테스트는 Task 6에서.)

- [ ] **Step 5: Commit**

```bash
git add notionmemory/cli.py tests/test_cli_templates.py
git commit -m "feat(templates): CLI read/append verbs + <slug|page-id> resolver"
```

---

### Task 6: CLI destructive verbs — replace, edit, delete + --yes preview gates

**Files:**
- Modify: `notionmemory/cli.py`
- Test: `tests/test_cli_templates.py`

**Interfaces:**
- Consumes: `DocumentStore.replace/edit/delete/current_markdown`, `MarkdownEditError`, `_text_or_file`, `_resolve_page_target`.
- Produces: CLI verbs `replace`/`edit`/`delete` with `--yes` 게이트.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_templates.py — 추가
from notionmemory.skills.templates.document import MarkdownEditError


def _fake_store(monkeypatch, **methods):
    class S:
        def current_markdown(self, pid): return methods.get("current", "alpha beta alpha")
        def replace(self, pid, md): methods.setdefault("calls", []).append(("replace", pid, md))
        def edit(self, pid, f, r, all_matches=False):
            methods.setdefault("calls", []).append(("edit", pid, f, r, all_matches))
            if "edit_raises" in methods:
                raise methods["edit_raises"]
        def delete(self, pid, f, all_matches=False):
            methods.setdefault("calls", []).append(("delete", pid, f, all_matches))
    monkeypatch.setattr(cli, "DocumentStore", lambda *a, **k: S())
    monkeypatch.setattr(cli, "NotionSession", lambda *a, **k: object())
    monkeypatch.setattr(cli, "_resolve_page_target", lambda t: "pid")
    return methods


def test_edit_without_yes_previews_and_does_not_mutate(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="alpha only once")
    rc = cli.main(["templates", "edit", "slug", "--find", "alpha", "--replace", "ALPHA"])
    assert rc == 2
    assert "calls" not in m                       # 변이 0건
    out = capsys.readouterr().out
    assert "alpha" in out and "ALPHA" in out       # 미리보기


def test_edit_no_match_is_reported_before_mutation(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="nothing here")
    rc = cli.main(["templates", "edit", "slug", "--find", "zzz", "--replace", "y"])
    assert rc == 2
    assert "calls" not in m
    assert "찾" in capsys.readouterr().out          # "매치를 찾지 못" 안내


def test_edit_multi_match_requires_all(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="dup and dup")
    rc = cli.main(["templates", "edit", "slug", "--find", "dup", "--replace", "y"])
    assert rc == 2
    assert "calls" not in m
    assert "2" in capsys.readouterr().out           # N=2 개 매치 안내


def test_edit_with_yes_mutates(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="alpha only once")
    rc = cli.main(["templates", "edit", "slug", "--find", "alpha", "--replace", "A", "--yes"])
    assert rc == 0
    assert ("edit", "pid", "alpha", "A", False) in m["calls"]


def test_edit_maps_markdown_edit_error_to_exit_2(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="alpha", edit_raises=MarkdownEditError("No matches found"))
    rc = cli.main(["templates", "edit", "slug", "--find", "alpha", "--replace", "A", "--yes"])
    assert rc == 2
    assert "No matches" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_cli_templates.py -q`
Expected: FAIL — `edit` 파서/핸들러 없음.

- [ ] **Step 3: Implement in cli.py**

(a) argparse(Task 5에서 block 제거한 자리)에 추가:

```python
    trp = tpl_sub.add_parser("replace")
    trp.add_argument("target")
    trp.add_argument("--markdown", default=None)
    trp.add_argument("--markdown-file", default="", help="`-`=stdin")
    trp.add_argument("--yes", action="store_true")
    ted = tpl_sub.add_parser("edit")
    ted.add_argument("target")
    ted.add_argument("--find", required=True)
    ted.add_argument("--replace", required=True)
    ted.add_argument("--all", action="store_true", help="모든 매치 치환(replaceAllMatches)")
    ted.add_argument("--yes", action="store_true")
    tde = tpl_sub.add_parser("delete")
    tde.add_argument("target")
    tde.add_argument("--find", required=True)
    tde.add_argument("--all", action="store_true")
    tde.add_argument("--yes", action="store_true")
```

(b) 핸들러 추가:

```python
def _templates_replace(args) -> int:
    md = _text_or_file(args.markdown, args.markdown_file)
    if md is None:
        print("--markdown 또는 --markdown-file 이 필요합니다")
        return 2
    target = _resolve_page_target(args.target)
    store = DocumentStore(NotionSession(), log=print)
    if not args.yes:
        cur = store.current_markdown(target)
        print(f"이 페이지 본문 전체를 교체합니다({len(cur)}자 → {len(md)}자).\n"
              "확인하면 --yes 를 붙여 다시 실행하세요.")
        return 2
    store.replace(target, md)
    print(f"교체됨: {target}")
    return 0


def _templates_edit(args) -> int:
    target = _resolve_page_target(args.target)
    store = DocumentStore(NotionSession(), log=print)
    n = store.current_markdown(target).count(args.find)   # 로컬 매치 수(지표)
    if n == 0:
        print(f"'{args.find}' 매치를 찾지 못했습니다 — 편집을 취소합니다(변경 없음).")
        return 2
    if n > 1 and not args.all:
        print(f"'{args.find}' 이(가) {n}개 위치에서 매치됩니다 — 검색어를 더 구체적으로 "
              "하거나 --all 로 전체 치환하세요(변경 없음).")
        return 2
    if not args.yes:
        print(f"이 편집을 적용합니다({n}개 매치):\n  찾기: {args.find}\n  바꾸기: {args.replace}\n"
              "확인하면 --yes 를 붙여 다시 실행하세요.")
        return 2
    try:
        store.edit(target, args.find, args.replace, all_matches=args.all)
    except MarkdownEditError as e:
        print(f"편집 실패: {e}")
        return 2
    print(f"편집됨: {target}")
    return 0


def _templates_delete(args) -> int:
    target = _resolve_page_target(args.target)
    store = DocumentStore(NotionSession(), log=print)
    n = store.current_markdown(target).count(args.find)
    if n == 0:
        print(f"'{args.find}' 매치를 찾지 못했습니다 — 삭제를 취소합니다(변경 없음).")
        return 2
    if n > 1 and not args.all:
        print(f"'{args.find}' 이(가) {n}개 위치에서 매치됩니다 — 더 구체적으로 하거나 "
              "--all 로 전체 삭제하세요(변경 없음).")
        return 2
    if not args.yes:
        print(f"이 내용을 삭제합니다({n}개 매치):\n  {args.find}\n"
              "확인하면 --yes 를 붙여 다시 실행하세요.")
        return 2
    try:
        store.delete(target, args.find, all_matches=args.all)
    except MarkdownEditError as e:
        print(f"삭제 실패: {e}")
        return 2
    print(f"삭제됨: {target}")
    return 0
```

(c) `MarkdownEditError`를 cli 상단 import에 추가(기존 32행 `from ...document import DocumentStore, PageNotFound, block_markdown` → `block_markdown` 제거, `MarkdownEditError` 추가):

```python
from notionmemory.skills.templates.document import DocumentStore, PageNotFound, MarkdownEditError
```

(d) 디스패치에 라우팅 추가(`_cmd_templates`):

```python
    if args.action == "replace":
        return _templates_replace(args)
    if args.action == "edit":
        return _templates_edit(args)
    if args.action == "delete":
        return _templates_delete(args)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_cli_templates.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add notionmemory/cli.py tests/test_cli_templates.py
git commit -m "feat(templates): replace/edit/delete verbs with --yes preview gates"
```

---

### Task 7: live_notion marker + live smoke

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/test_templates_document_live.py`

**Interfaces:**
- Consumes: 전체 `DocumentStore` 표면 + 실제 `NotionSession`.
- Produces: `live_notion` pytest 마커; 왕복 스모크 1건.

- [ ] **Step 1: Register the marker + write the smoke test**

`pyproject.toml`의 `markers`(48-50)에 한 줄 추가:

```toml
    "live_notion: 실제 Notion 워크스페이스 왕복이 필요하다 (PAT 소모, 기본 제외)",
```

```python
# tests/test_templates_document_live.py
import pytest

from notionmemory.core.notion_client import NotionSession
from notionmemory.skills.templates.document import DocumentStore, MarkdownEditError


@pytest.mark.live_notion
def test_markdown_roundtrip_against_real_notion():
    """create → append → edit → delete → replace → read → archive. 스크래치 페이지 자기정리."""
    sess = NotionSession()
    parent = sess.request("POST", "/search",
                          json={"filter": {"value": "page", "property": "object"},
                                "page_size": 1}).json()["results"][0]["id"]
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
        sess.request("DELETE", f"/blocks/{pid}")   # archive (in_trash)
```

- [ ] **Step 2: Confirm it is skipped by default**

Run: `./venv/bin/python -m pytest tests/test_templates_document_live.py -q`
Expected: 기본 스위트에서 수집되나 마커로 실행 제외되려면 아래 실행 규약 확인 — 기본
`pytest`는 마커 테스트도 도는가? 이 리포는 `harness` 마커를 `-m "not harness"` 없이도
기본 제외하는지 확인하고(기존 관행), 필요하면 `pyproject.toml`의 `addopts`에
`-m "not harness and not live_notion"`를 맞춘다. 최소한 이 테스트는 PAT 없으면
`NotionSession()`이 RuntimeError 를 던지므로, 마커 없이 도는 CI에서 실패하지 않도록
**반드시 마커 기반 제외를 실동작 확인**한다.

- [ ] **Step 3: Run the live smoke explicitly (구현자=Claude가 직접)**

Run: `./venv/bin/python -m pytest tests/test_templates_document_live.py -m live_notion -q`
Expected: PASS(실제 Notion, 스크래치 페이지 archive됨). 실패 시 원인(권한/부모페이지)
확인.

- [ ] **Step 4: Full suite still green**

Run: `./venv/bin/python -m pytest -q`
Expected: PASS(라이브 스모크는 제외된 채).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_templates_document_live.py
git commit -m "test(templates): live_notion marker + markdown API roundtrip smoke"
```

---

### Task 8: SKILL.md rewrite — text-addressed workflow

**Files:**
- Modify: `notionmemory/agent_skills/templates/SKILL.md`

**Interfaces:**
- Consumes: 최종 CLI 표면(Task 5/6).
- Produces: 없음(문서).

- [ ] **Step 1: Read the current document-editing section**

Run: `sed -n '94,238p' notionmemory/agent_skills/templates/SKILL.md`
현재 "Document editing"/"Content authoring" 섹션이 `read`(블록-id) → `block add/set/remove`
워크플로우를 가르친다.

- [ ] **Step 2: Rewrite to the new verbs**

블록-id 워크플로우 문장을 텍스트-주소지정으로 교체:
- `read <slug|page-id>` → 순수 마크다운(블록 id 없음).
- 수정: `edit <slug|page-id> --find "…" --replace "…" [--all] --yes`.
- 추가: `append <slug|page-id> --markdown/-file`.
- 삭제: `delete <slug|page-id> --find "…" [--all] --yes`.
- 통째 재작성: `replace <slug|page-id> --markdown/-file --yes`(잘린 큰 페이지엔 거부됨).
- 파괴적 연산은 `--yes` 전에 미리보기가 나오고, 매치 0/다중이면 변경 없이 안내됨.
- Notion-flavored 방언 주의: 블록 수식 `$$`는 독립 줄, toggle은 `<details>`/`<summary>`
  독립 줄, callout `<callout>`, columns `<columns>/<column>`, TOC `<table_of_contents/>`.
- 이미지 삽입은 종전대로 `templates image <page-id> <path>`(블록 API, 변경 없음).
`block add/set/remove`/블록-id 언급을 모두 제거.

- [ ] **Step 3: Verify no stale references remain**

Run: `grep -n "block add\|block set\|block remove\|block-id\|\[block" notionmemory/agent_skills/templates/SKILL.md`
Expected: 매치 없음(빈 결과).

- [ ] **Step 4: Skill doc sanity test**

Run: `./venv/bin/python -m pytest tests/test_skill_md.py -q`
Expected: PASS(SKILL.md 구조 검증 통과).

- [ ] **Step 5: Commit**

```bash
git add notionmemory/agent_skills/templates/SKILL.md
git commit -m "docs(templates): rewrite SKILL.md for text-addressed markdown editing"
```

---

## Self-Review

**1. Spec coverage**
- 범위(templates 문서편집만): Task 1-8 전부 templates 한정. ✓
- 접근 3(read+replace+append + edit/delete find, 취약 op 버림): Task 1-3, 6. ✓
- 명령 표면 6 verb + `<slug|page-id>` + `--yes` 게이트: Task 5, 6. ✓
- DocumentStore 재작성 + 이미지 잔존 + 죽은 코드 제거: Task 1-4. ✓
- truncated 시 replace 거부: Task 2. ✓
- edit 0/다중 매치 큰 소리 실패 + `MarkdownEditError` 매핑: Task 3, 6. ✓
- 하이브리드 테스트(유닛 + live_notion 스모크): Task 1-6(유닛), 7(라이브). ✓
- SKILL.md 재작성: Task 8. ✓
- 설치 계약 무영향: 새 ArtifactSpec 없음, manifest 미변경 — 전 태스크에서 건드리지 않음. ✓

**2. Placeholder scan:** TBD/TODO 없음. 각 코드 스텝은 실제 코드. ✓

**3. Type consistency:**
- `DocumentStore.edit(page_id, find, replace, all_matches=False)` — Task 3 정의, Task 6/7에서 동일 시그니처 사용. ✓
- `_resolve_page_target(target) -> str` — Task 5 정의, Task 6에서 monkeypatch로 동일 이름. ✓
- `current_markdown`/`read`/`append`/`replace`/`delete` 시그니처 Task 1-3과 6/7 일치. ✓
- `MarkdownEditError` — Task 2에서 정의(부트스트랩), Task 3/6/7에서 참조. ✓
- `_markdown_patch` — Task 2에서 정의, Task 3 `edit`/`delete`가 사용. ✓

**주의(실행자):** Task 2가 `_markdown_patch`+`MarkdownEditError`를 부트스트랩으로 함께
추가한다(Task 3 테스트가 그 전에 append/replace 경유로 이미 필요로 하므로). Task 3은
그 위에 `edit`/`delete`만 얹는다.
