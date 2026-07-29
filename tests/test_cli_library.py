"""library CLI — search(포인터)/read(라이브)/refresh/status."""
import pytest

from notionmemory import cli
from notionmemory.skills.library import index as I


@pytest.fixture(autouse=True)
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    return tmp_path


def test_search_prints_pointers_grouped_by_source(capsys, monkeypatch):
    monkeypatch.setattr(cli.library_retrieve, "search",
                        lambda s, c, q, **kw: [
                            {"source": "content", "id": "pg1", "title": "논문정리",
                             "section": "요약", "score": 8},
                            {"source": "memory", "id": "mem_1", "title": "어텐션 정리",
                             "section": "architecture", "score": 0}])
    assert cli.main(["library", "search", "어텐션"]) == 0
    out = capsys.readouterr().out
    assert "content" in out and "pg1" in out and "요약" in out
    assert "memory" in out and "mem_1" in out


def test_search_never_dumps_bodies(capsys, monkeypatch):
    monkeypatch.setattr(cli.library_retrieve, "search",
                        lambda s, c, q, **kw: [{"source": "content", "id": "pg1",
                                               "title": "T", "section": "", "score": 1}])
    cli.main(["library", "search", "x"])
    out = capsys.readouterr().out
    assert "rich_text" not in out and "plain_text" not in out


def test_search_empty_says_nothing_found(capsys, monkeypatch):
    monkeypatch.setattr(cli.library_retrieve, "search", lambda s, c, q, **kw: [])
    assert cli.main(["library", "search", "없는것"]) == 0
    assert "없" in capsys.readouterr().out


def test_search_source_content_forwards_content_only(monkeypatch):
    seen = {}

    def fake_search(s, c, q, *, limit=25, sources=None):
        seen["sources"] = sources
        return []
    monkeypatch.setattr(cli.library_retrieve, "search", fake_search)
    assert cli.main(["library", "search", "x", "--source", "content"]) == 0
    assert seen["sources"] == ("content",)


def test_search_source_invalid_exits_2():
    assert cli.main(["library", "search", "x", "--source", "bad"]) == 2


def test_read_reads_a_page_by_id_without_registration(capsys, monkeypatch):
    class FakeDoc:
        def __init__(self, session, log=None):
            pass

        def read(self, page_id):
            return f"[b1] {page_id} 본문"
    monkeypatch.setattr(cli, "DocumentStore", FakeDoc)
    assert cli.main(["library", "read", "pg1"]) == 0
    assert "pg1 본문" in capsys.readouterr().out


def test_refresh_runs_crawl_and_reports(capsys, monkeypatch):
    monkeypatch.setattr(cli.library_crawl, "refresh",
                        lambda s, *, full=False, log=print: {"indexed": 3, "pruned": 0, "total": 3})
    assert cli.main(["library", "refresh"]) == 0
    assert "3" in capsys.readouterr().out


def test_refresh_full_flag_forwarded(monkeypatch):
    seen = {}

    def fake_refresh(s, *, full=False, log=print):
        seen["full"] = full
        return {"indexed": 0, "pruned": 0, "total": 0}
    monkeypatch.setattr(cli.library_crawl, "refresh", fake_refresh)
    cli.main(["library", "refresh", "--full"])
    assert seen["full"] is True


def test_status_prints_count_and_age(capsys):
    idx = I.load()
    I.upsert(idx, "pg1", title="x", headings=[], url="u", last_edited_time="t")
    idx["last_refreshed"] = "2026-07-24T10:00:00.000Z"
    I.save(idx)
    assert cli.main(["library", "status"]) == 0
    out = capsys.readouterr().out
    assert "1" in out and "2026-07-24" in out


def test_status_empty_index(capsys):
    assert cli.main(["library", "status"]) == 0
    assert "훑" in capsys.readouterr().out or "0" in capsys.readouterr().out


def test_status_refreshed_but_empty_workspace(capsys):
    """refresh 는 돌았는데 공유 페이지가 0개 — '없음'(미갱신)이 아니라 '0건'으로 구분한다."""
    idx = I.load()
    idx["last_run"] = "2026-07-25T00:00:00+00:00"
    I.save(idx)
    assert cli.main(["library", "status"]) == 0
    out = capsys.readouterr().out
    assert "0건" in out and "없음" not in out
