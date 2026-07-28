import pytest

from notionmemory import cli


class FakeStore:
    """CalendarStore 계약의 기록형 페이크 — cli.CalendarStore로 monkeypatch."""
    instance = None

    def __init__(self, session, config, log=None):
        FakeStore.instance = self
        self.calls = []
        self.events = [
            {"event_id": "evt_1", "title": "회의", "start": "2026-07-21T14:00:00+09:00",
             "end": "2026-07-21T15:00:00+09:00", "status": "Scheduled",
             "location": "", "link": "", "page_id": "pg", "url": "https://notion.so/pg"}]
        self.known = {"evt_1"}

    def add(self, title, **kw):
        self.calls.append(("add", title, kw))
        from notionmemory.skills.calendar.store import parse_when
        parse_when(kw["start"])  # 형식 검증은 실물과 동일하게 ValueError 전파
        return dict(self.events[0], title=title)

    def list_events(self, **kw):
        self.calls.append(("list", kw))
        return self.events

    def update(self, event_id, **kw):
        self.calls.append(("update", event_id, kw))
        return {"event_id": event_id, "warning": ""} if event_id in self.known else None

    def cancel(self, event_id):
        self.calls.append(("cancel", event_id))
        return event_id in self.known


@pytest.fixture(autouse=True)
def fake_store(monkeypatch):
    # NotionSession은 토큰 없으면 __init__에서 raise — 기존 tests/test_cli.py의
    # memory verb 픽스처와 동일하게 세션도 페이크로 치환한다.
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    monkeypatch.setattr(cli, "CalendarStore", FakeStore)
    return FakeStore


def test_list_prints_lines(capsys):
    assert cli.main(["calendar", "list"]) == 0
    out = capsys.readouterr().out
    assert "evt_1" in out and "회의" in out


def test_list_rejects_to_plus_days(capsys):
    assert cli.main(["calendar", "list", "--to", "2026-07-25", "--days", "3"]) == 2
    assert "동시" in capsys.readouterr().out


def test_list_rejects_negative_days():
    assert cli.main(["calendar", "list", "--days", "-1"]) == 2


def test_add_prints_saved_and_url(capsys):
    assert cli.main(["calendar", "add", "점심", "--start", "2026-07-21 12:00"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Saved evt_1")
    assert "https://notion.so/pg" in out


def test_add_bad_date_exit2(capsys):
    assert cli.main(["calendar", "add", "x", "--start", "내일"]) == 2
    assert "날짜 형식" in capsys.readouterr().out


def test_update_requires_at_least_one_field(capsys):
    assert cli.main(["calendar", "update", "evt_1"]) == 2
    assert "변경할" in capsys.readouterr().out


def test_update_unknown_id_exit1(capsys):
    assert cli.main(["calendar", "update", "evt_x", "--title", "t"]) == 1
    assert "일정 없음" in capsys.readouterr().out


def test_update_passes_fields(capsys):
    assert cli.main(["calendar", "update", "evt_1", "--start", "2026-07-21 15:00",
                     "--end", ""]) == 0
    action, eid, kw = FakeStore.instance.calls[-1]
    assert (action, eid) == ("update", "evt_1")
    assert kw["start"] == "2026-07-21 15:00" and kw["end"] == ""
    assert kw["title"] is None  # 안 준 필드는 None(미변경)


def test_setup_prints_steps_without_touching_notion(tmp_path, capsys, monkeypatch):
    """setup은 안내 전용 — Notion 세션을 만들지 않아야 오프라인·미연결에서도 동작한다."""
    def boom(**kw):
        raise AssertionError("setup이 NotionSession을 생성했다")
    monkeypatch.setattr(cli, "NotionSession", boom)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills:\n  calendar:\n    database_id: abc123\n", encoding="utf-8")
    assert cli.main(["calendar", "setup", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "Add Notion database" in out and "default calendar" in out
    assert "https://www.notion.so/abc123" in out   # DB 바로가기


def test_setup_without_bootstrapped_db_tells_user_to_add_first(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills: {}\n", encoding="utf-8")
    assert cli.main(["calendar", "setup", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "calendar add" in out   # DB가 아직 없으니 첫 일정 등록으로 부트스트랩하라고 안내


def test_cancel_ok_and_unknown(capsys):
    assert cli.main(["calendar", "cancel", "evt_1"]) == 0
    assert "휴지통" in capsys.readouterr().out
    assert cli.main(["calendar", "cancel", "evt_x"]) == 1


def test_target_prints_current_value_when_no_argument(capsys, tmp_path):
    # 격리된 config 를 명시 — HOME monkeypatch 는 DEFAULT_CONFIG 가 import 시 고정돼
    # 효과가 없어, 이 테스트가 실사용 config(~/.config/notionmemory)를 읽어 calendar
    # write_target 이 설정된 환경에서 실패하던 사고. 형제 setup 테스트처럼 --config 로 격리.
    cfg = tmp_path / "config.yaml"
    assert cli.main(["calendar", "target", "--config", str(cfg)]) == 0
    assert "미결정" in capsys.readouterr().out


def test_target_rejects_a_bad_format(capsys, tmp_path):
    cfg = tmp_path / "config.yaml"
    assert cli.main(["calendar", "target", "junk", "--config", str(cfg)]) == 2
    assert "template:<slug>/<db-key>" in capsys.readouterr().out


def test_add_here_forwards_force_builtin(fake_store):
    assert cli.main(["calendar", "add", "회의", "--start", "2026-07-22 15:00",
                     "--here"]) == 0
    assert FakeStore.instance.calls[-1][2]["force_builtin"] is True


def test_ambiguous_write_exits_two_with_the_question(capsys, fake_store, monkeypatch):
    from notionmemory.skills.calendar import routing

    def boom(title, **kw):
        raise routing.ambiguous([type("P", (), {
            "slug": "my-planner", "summary": "할 일", "name": "my-planner",
            "databases": [{"key": "tasks"}]})()])
    monkeypatch.setattr(FakeStore, "add", lambda self, title, **kw: boom(title, **kw))
    assert cli.main(["calendar", "add", "회의", "--start", "2026-07-22 15:00"]) == 2
    out = capsys.readouterr().out
    assert "my-planner" in out and "이번만" in out
