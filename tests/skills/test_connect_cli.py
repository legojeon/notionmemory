"""memory `connect --new|--url` + `connection` CLI 동사.

adopt/ensure 는 실제 Notion 을 절대 부르지 않는다 — DB 클래스 메서드를 monkeypatch 해
호출·인자 전달만 확인한다(계약 테스트, 통합 테스트 아님). `connection` 은 DB 를 만들지
않는다는 불변식을 지키므로 NotionSession 조차 만들지 않는다 — 그 경로에서는
`cli.NotionSession` 을 일부러 patch 하지 않고(호출되면 실패해야 진짜 검증) config 만
읽는다.
"""
from notionmemory import cli


def run_cli(argv):
    return cli.main(argv)


def _cfg(tmp_path, body: str = "skills: {}\n"):
    p = tmp_path / "config.yaml"
    p.write_text(body, encoding="utf-8")
    return str(p)


# ---- memory connect (신규 top-level 서브파서 그룹) ----

def test_memory_connect_url_calls_adopt(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    seen = {}
    monkeypatch.setattr(
        "notionmemory.skills.memory.notion_db.SecondBrainDB.adopt",
        lambda self, dbid, meta: seen.setdefault("id", dbid) or [])
    rc = run_cli(["memory", "connect", "--url",
                 "https://www.notion.so/x-0123456789abcdef0123456789abcdef",
                 "--config", _cfg(tmp_path)])
    assert rc == 0 and seen["id"] == "0123456789abcdef0123456789abcdef"


def test_memory_connect_new_calls_ensure(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    seen = {}
    monkeypatch.setattr(
        "notionmemory.skills.memory.notion_db.SecondBrainDB.ensure",
        lambda self, parent, meta: seen.setdefault("called", True) or "ds_1")
    rc = run_cli(["memory", "connect", "--new", "--config", _cfg(tmp_path)])
    assert rc == 0 and seen["called"] is True


def test_memory_connect_url_success_prints_db_link(monkeypatch, tmp_path, capsys):
    """Fix round 1, item 2 — memory 쪽도 동일하게 성공 메시지에 DB 링크가 붙는다."""
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())

    def fake_adopt(self, dbid, meta):
        meta.set_meta("database_id", dbid)
        return []
    monkeypatch.setattr("notionmemory.skills.memory.notion_db.SecondBrainDB.adopt", fake_adopt)
    rc = run_cli(["memory", "connect", "--url",
                 "https://www.notion.so/x-0123456789abcdef0123456789abcdef",
                 "--config", _cfg(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "https://www.notion.so/0123456789abcdef0123456789abcdef" in out


def test_memory_connect_refusal_is_clean(monkeypatch, tmp_path, capsys):
    from notionmemory.skills.memory import notion_db as nd
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    monkeypatch.setattr(nd.SecondBrainDB, "adopt",
                        lambda *_a: (_ for _ in ()).throw(nd.NotASecondBrainError("nope")))
    rc = run_cli(["memory", "connect", "--url",
                 "https://www.notion.so/x-0123456789abcdef0123456789abcdef",
                 "--config", _cfg(tmp_path)])
    assert rc != 0
    out = capsys.readouterr().out
    assert "nope" in out and "Traceback" not in out


def test_memory_connect_bad_url_rejected(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())

    def boom(self, dbid, meta):
        raise AssertionError("adopt 가 호출되면 안 된다")
    monkeypatch.setattr("notionmemory.skills.memory.notion_db.SecondBrainDB.adopt", boom)
    rc = run_cli(["memory", "connect", "--url", "junk", "--config", _cfg(tmp_path)])
    assert rc != 0
    assert "유효한 Notion DB URL/ID 가 아닙니다" in capsys.readouterr().out


def test_memory_connect_requires_new_or_url(tmp_path):
    # argparse mutually-exclusive required group -> SystemExit(2), argparse 사용법 메시지
    import pytest
    with pytest.raises(SystemExit) as exc:
        run_cli(["memory", "connect", "--config", _cfg(tmp_path)])
    assert exc.value.code != 0


def test_memory_connection_reports_binding_without_creating_db(monkeypatch, tmp_path, capsys):
    def boom(**kw):
        raise AssertionError("connection 이 NotionSession 을 생성했다 — DB 를 만들면 안 된다")
    monkeypatch.setattr(cli, "NotionSession", boom)
    cfg = _cfg(tmp_path, "skills:\n  memory:\n    database_id: def456\n")
    rc = run_cli(["memory", "connection", "--config", cfg])
    assert rc == 0
    out = capsys.readouterr().out
    assert "def456" in out and "bound" in out


def test_memory_connection_respects_ko_language(monkeypatch, tmp_path, capsys):
    def boom(**kw):
        raise AssertionError("connection 이 NotionSession 을 생성했다")
    monkeypatch.setattr(cli, "NotionSession", boom)
    cfg = _cfg(tmp_path, "language: ko\nskills:\n  memory:\n    database_id: def456\n")
    rc = run_cli(["memory", "connection", "--config", cfg])
    assert rc == 0
    out = capsys.readouterr().out
    assert "연결됨" in out and "def456" in out
    assert "bound" not in out.lower()


def test_remember_recall_forget_remain_top_level(monkeypatch, tmp_path, capsys):
    """memory 서브파서 그룹 신설이 기존 top-level remember/recall/forget 을 건드리지 않는다."""
    class FakeStore:
        def __init__(self, session, config):
            pass

        def recall(self, query, mem_type="", project="", top=5):
            return {"results": [], "fallback": False}
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    monkeypatch.setattr(cli, "MemoryStore", FakeStore)
    rc = run_cli(["recall", "--config", _cfg(tmp_path)])
    assert rc == 0
    assert "저장된 memory 없음" in capsys.readouterr().out
