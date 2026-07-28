"""쓰기 라우팅 — calendar 는 남의 DB 에 절대 쓰지 않는다(표지판이지 어댑터가 아니다)."""
import pytest

from notionmemory.core.config import Config
from notionmemory.skills.calendar import routing
from notionmemory.skills.calendar.store import CalendarStore
from notionmemory.skills.templates import profile as P
from tests.skills.test_calendar_store import FakeSession


@pytest.fixture(autouse=True)
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _template(slug="my-planner", capabilities=("date", "text"), db_key="tasks"):
    p = P.Profile(slug=slug, name=slug, page_id="pg", summary="할 일과 마감 관리",
                  capabilities=list(capabilities),
                  databases=[{"key": db_key, "title": "Tasks", "database_id": "db",
                              "data_source_id": "ds", "title_property": "Name",
                              "missing": False, "properties": [
                                  {"name": "Name", "type": "title", "writable": True,
                                   "filterable": True},
                                  {"name": "Due", "type": "date", "writable": True,
                                   "filterable": True}]}])
    P.save(p)
    return p


def _store(target="", responses=None):
    cfg = Config({"skills": {"calendar": {"data_source_id": "ds_1",
                                          "write_target": target}}}, "")
    return CalendarStore(FakeSession(list(responses or [])), cfg)


# --- 값 파싱·검증 ---

def test_parse_target_three_states():
    assert routing.parse_target("") is None
    assert routing.parse_target("calendar") is None
    assert routing.parse_target("template:my-planner/tasks") == ("my-planner", "tasks")


def test_validate_target_accepts_the_builtin_and_empty():
    assert routing.validate_target("") == ""
    assert routing.validate_target("calendar") == "calendar"


def test_validate_target_requires_the_full_form():
    """slug 만으로는 date DB 가 둘인 템플릿에서 가리키는 곳이 애매해진다."""
    _template()
    with pytest.raises(ValueError) as e:
        routing.validate_target("template:my-planner")
    assert "template:<slug>/<db-key>" in str(e.value)


def test_validate_target_checks_the_profile_exists():
    with pytest.raises(ValueError) as e:
        routing.validate_target("template:nope/tasks")
    assert "nope" in str(e.value)


def test_validate_target_checks_the_db_key_exists():
    _template()
    with pytest.raises(ValueError) as e:
        routing.validate_target("template:my-planner/nosuch")
    assert "tasks" in str(e.value)          # 사용 가능한 key 를 알려준다


def test_validate_target_accepts_a_live_pointer():
    _template()
    assert routing.validate_target("template:my-planner/tasks") == \
        "template:my-planner/tasks"


# --- 겹침 판정 ---

def test_overlapping_needs_the_date_capability():
    _template("dated", capabilities=("date", "text"))
    _template("textonly", capabilities=("text",))
    assert [p.slug for p in routing.overlapping(P.load_all())] == ["dated"]


def test_overlapping_skips_disabled_and_trashed():
    _template("live")
    off = _template("off"); off.enabled = False; P.save(off)
    gone = _template("gone-ish"); gone.health = "trashed"; P.save(gone)
    assert [p.slug for p in routing.overlapping(P.load_all())] == ["live"]


# --- 게이트: 후보 수가 트리거다 ---

def test_no_overlapping_templates_means_no_question():
    """겹치는 게 없는 사용자는 오늘과 똑같이 동작한다 — 회귀 없음."""
    store = _store(responses=[(200, {"id": "ds_1"}),
                              (200, {"id": "pg_1", "url": "https://n/pg1"})])
    assert store.add("회의", start="2026-07-22 15:00")["page_id"] == "pg_1"


def test_one_overlapping_template_triggers_the_question():
    """1개여도 묻는다 — 여전히 Calendar DB 냐 템플릿이냐의 갈림길이다."""
    _template()
    with pytest.raises(routing.AmbiguousWrite) as e:
        _store().add("회의", start="2026-07-22 15:00")
    assert [c["slug"] for c in e.value.candidates] == ["my-planner"]


def test_the_question_is_raised_before_any_notion_call():
    """묻기도 전에 빈 Calendar DB 가 생기면 되묻기가 무의미하다 — 순서가 계약이다."""
    _template()
    store = _store()
    with pytest.raises(routing.AmbiguousWrite):
        store.add("회의", start="2026-07-22 15:00")
    assert store.db.session.calls == []


def test_the_question_names_both_sides_and_the_persistence_choice():
    _template()
    with pytest.raises(routing.AmbiguousWrite) as e:
        _store().add("회의", start="2026-07-22 15:00")
    msg = str(e.value)
    assert "Calendar DB" in msg and "my-planner" in msg
    assert "이번만" in msg and "앞으로 계속" in msg


def test_builtin_confirmed_skips_the_question():
    _template()
    store = _store("calendar", responses=[(200, {"id": "ds_1"}),
                                          (200, {"id": "pg_1", "url": "u"})])
    assert store.add("회의", start="2026-07-22 15:00")["page_id"] == "pg_1"


def test_force_builtin_is_the_one_shot_escape():
    """'이번만 Calendar DB' — config 를 건드리지 않고 통과한다."""
    _template()
    store = _store(responses=[(200, {"id": "ds_1"}), (200, {"id": "pg_1", "url": "u"})])
    assert store.add("회의", start="2026-07-22 15:00", force_builtin=True)["page_id"] == "pg_1"
    assert store.config.skill_options("calendar").get("write_target") == ""


# --- 라우팅이지 어댑터가 아니다 (스펙 §12 경계) ---

def test_template_target_refuses_and_returns_a_command():
    _template()
    with pytest.raises(routing.WriteBlocked) as e:
        _store("template:my-planner/tasks").add("회의", start="2026-07-22 15:00")
    assert e.value.command.startswith("notionmemory templates add my-planner tasks")


def test_template_target_makes_no_notion_call_at_all():
    """calendar 스킬은 남의 DB 에 쓰지 않는다 — 속성 매핑도 하지 않는다."""
    _template()
    store = _store("template:my-planner/tasks")
    with pytest.raises(routing.WriteBlocked):
        store.add("회의", start="2026-07-22 15:00")
    assert store.db.session.calls == []


def test_blocked_message_carries_no_property_mapping():
    """Title↔Name 같은 매핑이 등장하면 그 순간 §12 가 배제한 어댑터가 된다."""
    _template()
    store = _store("template:my-planner/tasks")
    with pytest.raises(routing.WriteBlocked) as e:
        store.add("회의", start="2026-07-22 15:00")
    assert "Title" not in e.value.command       # 우리 스키마 이름을 남의 DB 에 들이밀지 않는다


def test_a_dead_pointer_is_reported_not_silently_ignored():
    """사용자가 템플릿을 지운 뒤에도 write_target 이 남아 있을 수 있다."""
    store = _store("template:removed/tasks")
    with pytest.raises(ValueError) as e:
        store.add("회의", start="2026-07-22 15:00")
    assert "removed" in str(e.value) and "calendar target" in str(e.value)


def test_list_events_is_never_gated():
    """게이트는 쓰기 전용이다 — 조회는 §7 그대로 둘 다 본다.

    data_source_id 를 시드하지 않는다: Task 0 이후 조회는 캐시가 없으면 HTTP 없이
    빈 목록을 준다. 게이트가 조회에 걸려 있었다면 여기서 예외가 났을 것이다.
    """
    _template()
    cfg = Config({"skills": {"calendar": {"write_target": "template:my-planner/tasks"}}}, "")
    assert CalendarStore(FakeSession([]), cfg).list_events(today="2026-07-20") == []
