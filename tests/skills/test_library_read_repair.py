"""library read-repair — 라이브 404 지연삭제 + full 마커.

`library read` 가 삭제/공유해제된 페이지(404)를 만나면 색인에서 그 항목을 걷고
(dirty 표시), `--full` 은 last_full_run 을 찍고 dirty 를 리셋한다. 능동 divergence
감지는 불가능하므로(=크롤) read-404 를 값싼 divergence 신호로 쓴다."""
import pytest

from notionmemory.skills.library import crawl, index


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / ".local" / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    return tmp_path


class _Resp:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body or {}
        self.text = ""
        self.headers = {}

    def json(self):
        return self._body


# --- index markers ---

def test_index_defaults_have_full_markers():
    idx = index.load()
    assert idx["last_full_run"] == ""
    assert idx["dirty_since_full"] is False


def test_mark_dirty_sets_flag():
    idx = index.load()
    index.mark_dirty(idx)
    assert idx["dirty_since_full"] is True


# --- crawl --full resets ---

class _EmptySearchSession:
    def request(self, method, path, **kw):
        return _Resp(200, {"results": [], "has_more": False, "next_cursor": None})


def test_full_refresh_sets_last_full_run_and_resets_dirty():
    idx = index.load()
    index.upsert(idx, "p1", title="t", headings=[], url="",
                 last_edited_time="2026-01-01T00:00:00Z")
    index.mark_dirty(idx)
    index.save(idx)

    crawl.refresh(_EmptySearchSession(), full=True, log=lambda *_: None)

    got = index.load()
    assert got["last_full_run"], "full 은 last_full_run 을 찍어야 한다"
    assert got["dirty_since_full"] is False, "full 은 드리프트 플래그를 리셋해야 한다"
    assert "p1" not in got["pages"], "full 은 더 이상 없는 항목을 prune 해야 한다"


def test_incremental_refresh_does_not_touch_full_markers():
    idx = index.load()
    index.mark_dirty(idx)
    index.save(idx)
    crawl.refresh(_EmptySearchSession(), full=False, log=lambda *_: None)
    got = index.load()
    # 증분은 prune 도 last_full_run 도 dirty 리셋도 하지 않는다
    assert got["last_full_run"] == ""
    assert got["dirty_since_full"] is True


# --- document _req raises PageNotFound on 404 ---

def test_document_req_raises_page_not_found_on_404():
    from notionmemory.skills.templates.document import DocumentStore, PageNotFound

    class _S:
        def request(self, method, path, **kw):
            return _Resp(404)

    store = DocumentStore(_S())
    with pytest.raises(PageNotFound):
        store.read("gone")


# --- CLI library read: 404 -> prune + mark dirty ---

def test_cli_library_read_404_prunes_and_marks_dirty(monkeypatch, capsys):
    from notionmemory import cli

    idx = index.load()
    index.upsert(idx, "dead", title="old", headings=[], url="",
                 last_edited_time="2026-01-01T00:00:00Z")
    index.save(idx)

    class _S:
        def request(self, method, path, **kw):
            return _Resp(404)

    monkeypatch.setattr(cli, "NotionSession", lambda *a, **k: _S())
    assert cli.main(["library", "read", "dead"]) == 0

    got = index.load()
    assert "dead" not in got["pages"], "죽은 항목을 색인에서 걷어야 한다"
    assert got["dirty_since_full"] is True, "드리프트를 표시해야 한다(→ --full 넛지)"
    out = capsys.readouterr().out
    assert "refresh --full" in out


def test_cli_library_read_404_unknown_id_is_graceful(monkeypatch, capsys):
    from notionmemory import cli

    class _S:
        def request(self, method, path, **kw):
            return _Resp(404)

    monkeypatch.setattr(cli, "NotionSession", lambda *a, **k: _S())
    # 색인에 없던 id 여도 트레이스백 없이 안내만
    assert cli.main(["library", "read", "never-indexed"]) == 0
    assert "library" in capsys.readouterr().out.lower()
