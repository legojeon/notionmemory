"""templates CLI — 종료 코드·출력 경제·되물음 경로."""
import json

import pytest

from notionmemory import cli
from notionmemory.skills.templates import introspect as I
from notionmemory.skills.templates import profile as P
from notionmemory.skills.templates.document import MarkdownEditError


@pytest.fixture(autouse=True)
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    return tmp_path


def _saved(slug="job-tracker", pages=None):
    p = P.Profile(
        slug=slug, name="Job Tracker", page_id="pg_root", page_url="https://n/pg_root",
        summary="지원 추적", capabilities=["date", "text"],
        databases=[{"key": "applications", "title": "Applications",
                    "database_id": "db_a", "data_source_id": "ds_a",
                    "title_property": "Position", "missing": False, "properties": [
                        {"name": "Position", "type": "title", "writable": True,
                         "filterable": True},
                        {"name": "Stage", "type": "select", "writable": True,
                         "filterable": True, "choices": ["Applied", "Offer"]},
                        {"name": "Days Open", "type": "formula", "writable": False,
                         "filterable": True}]}],
        body="## 무엇에 쓰는 템플릿인가\n지원 추적한다.\n", pages=pages if pages is not None else [])
    P.save(p)
    return p


class FakeStore:
    instance = None
    # 클래스 레벨로 공유한다 — 실제 CLI 는 `cli.main()` 호출마다(예: update 한 번,
    # archive 한 번, 별도 프로세스 아님) `TemplateStore` 를 새로 만든다(calendar/git
    # 그룹과 동일한 패턴). `self.calls = []` 로 인스턴스 속성으로 두면 두 번째
    # `cli.main()` 호출이 새 인스턴스를 만드는 순간 첫 호출의 기록이 접근 불가능해져
    # `test_update_and_archive_take_a_row_id` 처럼 두 호출에 걸친 순서를 검증할 수
    # 없다. `fake_store` 픽스처가 테스트마다 새 리스트로 갈아 끼워 격리한다.
    calls: list = []

    def __init__(self, session, log=None):
        FakeStore.instance = self
        self.calls = FakeStore.calls

    def query(self, p, db_key, **kw):
        self.calls.append(("query", db_key, kw))
        return {"rows": [{"id": "pg_1", "url": "https://n/pg_1",
                          "Position": "Backend", "Stage": "Applied"}],
                "fields": kw.get("fields") or ["Position", "Stage"],
                "capped": kw.get("_capped", False), "cap": 25,
                "sorted": bool(kw.get("sorts"))}

    def count(self, p, db_key, **kw):
        self.calls.append(("count", db_key, kw))
        return 7

    def add(self, p, db_key, pairs, **kw):
        self.calls.append(("add", db_key, pairs, kw))
        return {"id": "pg_new", "url": "https://n/pg_new"}

    def update(self, p, db_key, row_id, pairs, **kw):
        self.calls.append(("update", db_key, row_id, pairs, kw))
        return {"id": row_id}

    def archive(self, p, db_key, row_id):
        self.calls.append(("archive", db_key, row_id))
        return True

    def health_check(self, p):
        self.calls.append(("health", p.slug))
        return "ok"


@pytest.fixture
def fake_store(monkeypatch):
    FakeStore.instance = None
    FakeStore.calls = []      # 테스트 간 오염 방지 — 새 리스트로 교체
    monkeypatch.setattr(cli, "TemplateStore", FakeStore)
    return FakeStore


# --- list / show ---

def test_list_empty_says_how_to_register(capsys):
    assert cli.main(["templates", "list"]) == 0
    assert "register" in capsys.readouterr().out


def test_list_shows_slug_summary_and_health(capsys):
    _saved()
    assert cli.main(["templates", "list"]) == 0
    out = capsys.readouterr().out
    assert "job-tracker" in out and "지원 추적" in out and "ok" in out


def test_show_is_compact_by_default(capsys):
    _saved()
    assert cli.main(["templates", "show", "job-tracker"]) == 0
    out = capsys.readouterr().out
    assert "applications" in out and "Stage" in out and "select" in out
    assert "Offer" not in out                 # choices 전문은 --full 에서만
    assert "무엇에 쓰는 템플릿인가" not in out   # 산문도 --full 에서만


def test_show_full_adds_choices_and_prose(capsys):
    _saved()
    assert cli.main(["templates", "show", "job-tracker", "--full"]) == 0
    out = capsys.readouterr().out
    assert "Offer" in out and "무엇에 쓰는 템플릿인가" in out


def test_show_warns_that_page_bodies_are_not_searchable(capsys):
    _saved()
    cli.main(["templates", "show", "job-tracker"])
    assert "본문" in capsys.readouterr().out


def test_unknown_slug_exits_two_with_available_list(capsys):
    _saved("reading-list")
    assert cli.main(["templates", "show", "nope"]) == 2
    assert "reading-list" in capsys.readouterr().out


# --- query ---

def test_query_prints_a_flat_table_with_id_first(capsys, fake_store):
    _saved()
    assert cli.main(["templates", "query", "job-tracker", "applications"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[0] == "id"
    assert "pg_1" in lines[1]


def test_query_never_prints_raw_notion_json(capsys, fake_store):
    _saved()
    cli.main(["templates", "query", "job-tracker", "applications"])
    out = capsys.readouterr().out
    assert "plain_text" not in out and "rich_text" not in out


def test_query_passes_parsed_where_and_sort_to_the_store(fake_store):
    _saved()
    cli.main(["templates", "query", "job-tracker", "applications",
              "--where", "Days Open>30", "--where", "Stage=Offer",
              "--sort", "Position desc", "--limit", "5"])
    _, _, kw = FakeStore.instance.calls[0]
    assert kw["wheres"] == [("Days Open", ">", "30"), ("Stage", "=", "Offer")]
    assert kw["sorts"] == [{"property": "Position", "direction": "descending"}]
    assert kw["limit"] == 5


def test_query_json_output_parses(capsys, fake_store):
    _saved()
    assert cli.main(["templates", "query", "job-tracker", "applications", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "pg_1"


def test_query_json_stays_parseable_when_truncated(capsys, fake_store, monkeypatch):
    """--json 은 에이전트 경로다 — 절단돼도 stdout 은 순수 JSON 이어야 하고,
    절단 신호는 stderr 로 가야 한다(최종 리뷰 발견)."""
    _saved()
    monkeypatch.setattr(FakeStore, "query", lambda self, p, k, **kw: {
        "rows": [{"id": "pg_1", "Position": "Backend"}], "fields": ["Position"],
        "capped": True, "cap": 25, "sorted": False})
    assert cli.main(["templates", "query", "job-tracker", "applications", "--json"]) == 0
    captured = capsys.readouterr()
    # stdout 은 통째로 json.loads 가 성공해야 한다 — 한국어 절단 줄이 섞이면 깨진다
    assert json.loads(captured.out)[0]["id"] == "pg_1"
    # 절단 신호는 사라지지 않고 stderr 로 전달된다
    assert "25" in captured.err and "임의 순서" in captured.err


def test_query_count_prints_only_a_number(capsys, fake_store):
    _saved()
    assert cli.main(["templates", "query", "job-tracker", "applications", "--count"]) == 0
    assert capsys.readouterr().out.strip() == "7"


def test_query_truncation_is_announced(capsys, fake_store, monkeypatch):
    _saved()
    monkeypatch.setattr(FakeStore, "query", lambda self, p, k, **kw: {
        "rows": [], "fields": ["Position"], "capped": True, "cap": 25, "sorted": False})
    cli.main(["templates", "query", "job-tracker", "applications"])
    out = capsys.readouterr().out
    assert "25" in out and "임의 순서" in out


def test_bad_where_exits_two(capsys, fake_store):
    _saved()
    assert cli.main(["templates", "query", "job-tracker", "applications",
                     "--where", "Stage"]) == 2
    assert "연산자" in capsys.readouterr().out


# --- 절단 메시지 — cap 원인에 따라 조언이 달라야 한다(carry-forward #3) ---

def test_query_truncation_advises_bigger_limit_when_cause_is_user_limit(capsys, fake_store,
                                                                        monkeypatch):
    """--all 없이 잘렸으면 원인은 사용자(또는 기본값) --limit 이다. "조건을 좁히세요"는
    반대 방향 조언이라 거짓말이 된다 — 대신 --limit/--all 을 안내해야 한다."""
    _saved()
    monkeypatch.setattr(FakeStore, "query", lambda self, p, k, **kw: {
        "rows": [], "fields": ["Position"], "capped": True, "cap": 25, "sorted": True})
    cli.main(["templates", "query", "job-tracker", "applications"])
    out = capsys.readouterr().out
    assert "좁히세요" not in out
    assert "--limit" in out and "--all" in out


def test_query_truncation_keeps_narrow_filter_advice_for_safety_cap(capsys, fake_store,
                                                                     monkeypatch):
    """--all 로 요청했는데도 잘렸으면 진짜 안전 상한(ALL_CAP)에 닿은 것 — "조건을
    좁히세요"가 맞는 조언이다."""
    _saved()
    monkeypatch.setattr(FakeStore, "query", lambda self, p, k, **kw: {
        "rows": [], "fields": ["Position"], "capped": True, "cap": 1000, "sorted": True})
    cli.main(["templates", "query", "job-tracker", "applications", "--all"])
    out = capsys.readouterr().out
    assert "좁히세요" in out


def test_query_stalled_signal_is_threaded_and_does_not_blame_filters(capsys, fake_store,
                                                                     monkeypatch):
    """store.query() 가 주는 `stalled` 은 render.truncation_note 의 `stalled` 로
    그대로 이어져야 한다 — 이름이 다르다고 흘리면 정체를 "정상 완료"로 오인시킨다."""
    _saved()
    monkeypatch.setattr(FakeStore, "query", lambda self, p, k, **kw: {
        "rows": [], "fields": ["Position"], "capped": False, "cap": 25, "sorted": True,
        "stalled": True})
    cli.main(["templates", "query", "job-tracker", "applications"])
    out = capsys.readouterr().out
    assert "불완전" in out
    assert "좁히세요" not in out


# --- 사용자 정의 id/url 속성은 실제 row id 와 섞이지 않는다 ---

def test_query_table_preserves_user_id_and_url_properties(capsys, fake_store, monkeypatch):
    monkeypatch.setattr(FakeStore, "query", lambda self, p, k, **kw: {
        "rows": [{"id": "pg_1", "url": "https://n/pg_1", "id (property)": "JOB-42"}],
        "fields": ["id"], "capped": False, "cap": 25, "sorted": True})
    _saved()
    assert cli.main(["templates", "query", "job-tracker", "applications",
                     "--fields", "id"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[0] == "id"        # 진짜 row id 가 여전히 첫 컬럼
    assert "id (property)" in lines[0]        # 사용자 'id' 속성이 별도 컬럼으로 살아남는다
    assert "JOB-42" in lines[1]               # 값이 real id 와 안 섞인다
    assert "pg_1" in lines[1]


# --- add / update / archive ---

def test_add_parses_set_pairs_and_prints_the_url(capsys, fake_store):
    _saved()
    assert cli.main(["templates", "add", "job-tracker", "applications",
                     "--set", "Position=Backend", "--set", "Stage=Applied"]) == 0
    _, _, pairs, kw = FakeStore.instance.calls[0]
    assert pairs == [("Position", "Backend"), ("Stage", "Applied")]
    assert kw["allow_new_option"] is False
    assert "pg_new" in capsys.readouterr().out


def test_add_forwards_notes_and_allow_new_option(fake_store):
    _saved()
    cli.main(["templates", "add", "job-tracker", "applications",
              "--set", "Position=Backend", "--notes", "# 메모", "--allow-new-option"])
    _, _, _, kw = FakeStore.instance.calls[0]
    assert kw["notes"] == "# 메모" and kw["allow_new_option"] is True


def test_add_without_set_exits_two(capsys, fake_store):
    _saved()
    assert cli.main(["templates", "add", "job-tracker", "applications"]) == 2


def test_update_and_archive_take_a_row_id(capsys, fake_store):
    _saved()
    assert cli.main(["templates", "update", "job-tracker", "applications", "pg_1",
                     "--set", "Stage=Offer"]) == 0
    assert cli.main(["templates", "archive", "job-tracker", "applications", "pg_1"]) == 0
    kinds = [c[0] for c in FakeStore.instance.calls]
    assert kinds == ["update", "archive"]
    assert "복원" in capsys.readouterr().out       # 되돌릴 수 있음을 알린다


# --- register / refresh / remove ---

def test_register_ambiguous_target_exits_two_with_candidates(capsys, monkeypatch):
    def boom(session, target, **kw):
        raise I.AmbiguousTarget("여러 건입니다", [{"id": "a", "title": "Tracker A",
                                              "url": "https://n/a"}])
    monkeypatch.setattr(cli.templates_introspect, "register", boom)
    assert cli.main(["templates", "register", "Tracker"]) == 2
    assert "Tracker A" in capsys.readouterr().out


def test_register_reports_success(capsys, monkeypatch):
    class FakeProfile:
        slug, databases = "job-tracker", [{"key": "a"}, {"key": "b"}]
    monkeypatch.setattr(cli.templates_introspect, "register",
                        lambda session, target, **kw: FakeProfile())
    assert cli.main(["templates", "register", "https://n/x"]) == 0
    assert "job-tracker" in capsys.readouterr().out


def test_refresh_keeps_notes_unless_asked(monkeypatch):
    """드리프트 복구의 기본 경로는 빨라야 한다 — agent 는 명시했을 때만 돈다."""
    _saved()
    seen = {}
    monkeypatch.setattr(cli.templates_introspect, "refresh",
                        lambda session, slug, runtime=None, log=print:
                            seen.setdefault("runtime", runtime) or _saved())
    assert cli.main(["templates", "refresh", "job-tracker"]) == 0
    assert seen["runtime"] is None


def test_remove_deletes_only_the_profile(capsys):
    _saved()
    assert cli.main(["templates", "remove", "job-tracker"]) == 0
    out = capsys.readouterr().out
    assert not P.exists("job-tracker")
    assert "Notion" in out                 # Notion 은 안 건드린다고 반드시 말한다


def test_remove_unknown_exits_two():
    assert cli.main(["templates", "remove", "nope"]) == 2


def test_profile_gone_error_tells_the_user_to_re_register(capsys, monkeypatch):
    from notionmemory.skills.templates.store import ProfileGone
    _saved()

    def boom(self, p, db_key, **kw):
        raise ProfileGone("등록을 해제했습니다 — 다시 register 하세요")
    monkeypatch.setattr(cli, "TemplateStore", FakeStore)
    monkeypatch.setattr(FakeStore, "query", boom)
    assert cli.main(["templates", "query", "job-tracker", "applications"]) == 1
    assert "register" in capsys.readouterr().out


class FakeDocStore:
    instance = None

    def __init__(self, session, log=None):
        FakeDocStore.instance = self
        self.calls = []

    def read(self, page_id):
        self.calls.append(("read", page_id))
        return "[b1] 옛 내용\n[db: d1] Papers"

    def append(self, page_id, markdown):
        self.calls.append(("append", page_id, markdown))

    def add_page(self, parent, title, markdown=""):
        self.calls.append(("add_page", parent, title, markdown))
        return {"id": "pgnew", "url": "https://n/pgnew"}


@pytest.fixture
def fake_doc(monkeypatch):
    FakeDocStore.instance = None
    monkeypatch.setattr(cli, "DocumentStore", FakeDocStore)
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    return FakeDocStore


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


def test_read_reads_a_raw_page_id_directly(capsys, fake_doc):
    """slug 등록 없이 원시 page-id 를 직접 넘기면 그대로 읽는다(override 경로) —
    `<slug|page-id>` 리졸버가 32-hex 를 slug 조회 없이 통과시킨다."""
    pid = "3b2cf80747f2811c9cbcccdbb63225e2"
    assert cli.main(["templates", "read", pid]) == 0
    assert ("read", pid) in FakeDocStore.instance.calls
    assert "[b1] 옛 내용" in capsys.readouterr().out


def test_read_without_page_id_defaults_to_profile_root(fake_doc):
    """스펙 §4: `read <slug>` 는 프로필 루트 페이지 본문을 읽는다."""
    _saved()          # page_id="pg_root" 로 저장된다
    assert cli.main(["templates", "read", "job-tracker"]) == 0
    assert ("read", "pg_root") in FakeDocStore.instance.calls


def test_append_calls_store(monkeypatch, capsys):
    calls = {}
    class S:
        def append(self, pid, md): calls["append"] = (pid, md)
    monkeypatch.setattr(cli, "DocumentStore", lambda *a, **k: S())
    monkeypatch.setattr(cli, "NotionSession", lambda *a, **k: object())
    monkeypatch.setattr(cli, "_resolve_page_target", lambda t: "pid")
    assert cli.main(["templates", "append", "slug", "--markdown", "more"]) == 0
    assert calls["append"] == ("pid", "more")


def test_append_is_free_and_applies_immediately(capsys, fake_doc):
    _saved()
    assert cli.main(["templates", "append", "job-tracker",
                     "--markdown", "## 새 섹션"]) == 0
    assert ("append", "pg_root", "## 새 섹션") in FakeDocStore.instance.calls
    assert "pg_root" in capsys.readouterr().out


def test_page_add_is_free(capsys, fake_doc):
    _saved()
    assert cli.main(["templates", "page", "add", "pg_root",
                     "--title", "새 논문", "--markdown", "## 요약"]) == 0
    assert ("add_page", "pg_root", "새 논문", "## 요약") in FakeDocStore.instance.calls
    assert "pgnew" in capsys.readouterr().out


def test_append_reads_markdown_from_file(tmp_path, fake_doc):
    """백틱·따옴표가 든 마크다운을 셸 인용 없이 파일로 넘긴다(--markdown-file)."""
    _saved()
    body = "## 코드\n```c\nint *i = 0; `backtick` \"quote\" $(cmd)\n```"
    f = tmp_path / "body.md"
    f.write_text(body, encoding="utf-8")
    assert cli.main(["templates", "append", "job-tracker",
                     "--markdown-file", str(f)]) == 0
    call = [c for c in FakeDocStore.instance.calls if c[0] == "append"][0]
    assert call[2] == body                       # 파일 내용이 그대로 전달됨


def test_append_reads_markdown_from_stdin(monkeypatch, fake_doc):
    """`--markdown-file -` 는 stdin 에서 읽는다."""
    import io
    _saved()
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("본문 `code`"))
    assert cli.main(["templates", "append", "job-tracker",
                     "--markdown-file", "-"]) == 0
    call = [c for c in FakeDocStore.instance.calls if c[0] == "append"][0]
    assert call[2] == "본문 `code`"


def test_append_without_any_markdown_exits_2(capsys, fake_doc):
    """--markdown 도 --markdown-file 도 없으면 명확히 막고 exit 2."""
    _saved()
    assert cli.main(["templates", "append", "job-tracker"]) == 2
    assert "필요합니다" in capsys.readouterr().out


def test_page_add_reads_markdown_from_file(tmp_path, fake_doc):
    _saved()
    f = tmp_path / "p.md"
    f.write_text("## 요약 `x`", encoding="utf-8")
    assert cli.main(["templates", "page", "add", "pg_root",
                     "--title", "새 논문", "--markdown-file", str(f)]) == 0
    assert ("add_page", "pg_root", "새 논문", "## 요약 `x`") in FakeDocStore.instance.calls


def test_show_prints_the_pages_outline(capsys):
    _saved(pages=[{"page_id": "pg_root", "title": "루트", "depth": 0, "parent": None,
                   "headings": ["소개", "본론"], "databases": ["applications"]}])
    cli.main(["templates", "show", "job-tracker"])
    out = capsys.readouterr().out
    assert "소개" in out and "본론" in out


def test_prompt_get_and_set(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    P.save(P.Profile(slug="job", name="Job", page_id="pg", page_url="u"))
    assert cli.main(["templates", "prompt", "job", "--set", "표로 정리해라"]) == 0
    assert cli.main(["templates", "prompt", "job"]) == 0
    assert "표로 정리해라" in capsys.readouterr().out


def test_prompt_set_from_file(monkeypatch, tmp_path):
    """백틱 든 프롬프트를 파일로 넘긴다(--set-file) — 셸 인용 우회."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    P.save(P.Profile(slug="job", name="Job", page_id="pg", page_url="u"))
    body = "용어는 `Random variable (확률변수)` 처럼 병기. 식은 $$x$$."
    f = tmp_path / "prompt.md"
    f.write_text(body, encoding="utf-8")
    assert cli.main(["templates", "prompt", "job", "--set-file", str(f)]) == 0
    assert P.load("job").prompt == body


def test_new_prompt_from_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    body = "개념별 헤딩. 코드는 ```c``` 로."
    f = tmp_path / "seed.md"
    f.write_text(body, encoding="utf-8")
    assert cli.main(["templates", "new-prompt", "lec",
                     "--name", "강의노트", "--prompt-file", str(f)]) == 0
    assert P.load("lec").prompt == body


def test_show_includes_prompt(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    P.save(P.Profile(slug="job", name="Job", page_id="pg", page_url="u",
                     prompt="담담한 톤으로"))
    cli.main(["templates", "show", "job"])
    assert "담담한 톤으로" in capsys.readouterr().out


def test_new_prompt_creates_page_less_template(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    assert cli.main(["templates", "new-prompt", "lecture-notes",
                     "--name", "강의노트", "--prompt", "개념별 헤딩으로"]) == 0
    p = P.load("lecture-notes")
    assert p.page_id == "" and p.name == "강의노트"
    assert p.prompt == "개념별 헤딩으로"
    assert p.databases == [] and p.pages == []


def test_new_prompt_allows_empty_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    assert cli.main(["templates", "new-prompt", "todo-notes", "--name", "메모"]) == 0
    assert P.load("todo-notes").prompt == ""      # 나중에 대시보드/CLI 로 편집


def test_new_prompt_rejects_existing_slug(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    P.save(P.Profile(slug="dup", name="기존", page_id="pg", page_url="u"))
    assert cli.main(["templates", "new-prompt", "dup", "--name", "새것"]) == 2
    assert "이미" in capsys.readouterr().out
    assert P.load("dup").name == "기존"           # 덮어쓰지 않는다


def test_image_cli_uploads_and_inserts(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    img = tmp_path / "fig.png"; img.write_bytes(b"\x89PNG" + b"0" * 32)
    seen = {}
    class FakeDoc:
        def __init__(self, session, log=None):
            pass
        def add_image(self, page_id, image_path, *, after=None, caption=""):
            seen["args"] = (page_id, str(image_path), caption)
            return {"id": "blk_1"}
    monkeypatch.setattr(cli, "DocumentStore", FakeDoc)
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    assert cli.main(["templates", "image", "pg1", str(img), "--caption", "그림1"]) == 0
    assert seen["args"] == ("pg1", str(img), "그림1")


def test_create_page_makes_page_then_registers(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    made = {}
    class FakeDoc:
        def __init__(self, session, log=None):
            pass
        def add_page(self, parent_page_id, title, markdown=""):
            made["parent"] = parent_page_id
            made["markdown"] = markdown
            return {"id": "new_pg", "url": "https://n/new_pg"}
    from notionmemory.skills.templates import profile as P
    def fake_register(session, target, *, slug="", log=print):
        made["target"] = target
        p = P.Profile(slug=slug or "new", name="New", page_id="new_pg", page_url=target)
        P.save(p)
        return p
    monkeypatch.setattr(cli, "DocumentStore", FakeDoc)
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    monkeypatch.setattr(cli.templates_introspect, "register", fake_register)
    assert cli.main(["templates", "create-page", "--parent", "root_pg",
                     "--title", "회의록", "--slug", "meeting"]) == 0
    assert made["parent"] == "root_pg"
    # 새 페이지에 앵커 블록(제목 헤딩)을 심어야 register 의 빈-페이지 거부를 피한다
    # (실기 검증에서 빈 페이지 등록이 exit 1 로 막힌 회귀 가드)
    assert made["markdown"].strip() != "" and "회의록" in made["markdown"]
    # 생성된 페이지(url 또는 id)를 register 에 넘긴다
    assert "new_pg" in made["target"]
    assert "meeting" in capsys.readouterr().out


def _page_less(monkeypatch, tmp_path, slug="blueprint"):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    P.save(P.Profile(slug=slug, name="청사진", page_id="", prompt="p"))
    return slug


def test_query_on_prompt_only_is_guarded(capsys, monkeypatch, tmp_path):
    slug = _page_less(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    code = cli.main(["templates", "query", slug, "x"])
    assert code == 2
    out = capsys.readouterr().out
    assert "프롬프트 전용" in out and "데이터베이스" in out
    assert "Traceback" not in out


def test_add_on_prompt_only_is_guarded(capsys, monkeypatch, tmp_path):
    slug = _page_less(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    assert cli.main(["templates", "add", slug, "x", "--set", "제목=t"]) == 2
    assert "프롬프트 전용" in capsys.readouterr().out


def test_refresh_on_prompt_only_is_guarded(capsys, monkeypatch, tmp_path):
    slug = _page_less(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    code = cli.main(["templates", "refresh", slug])
    assert code == 2
    out = capsys.readouterr().out
    assert "프롬프트 전용" in out and "갱신" in out
    assert "Traceback" not in out


def test_show_on_prompt_only_works(capsys, monkeypatch, tmp_path):
    slug = _page_less(monkeypatch, tmp_path)
    assert cli.main(["templates", "show", slug]) == 0   # show 는 빈 구조를 우아하게
    assert "청사진" in capsys.readouterr().out


def test_read_on_prompt_only_is_guarded(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    P.save(P.Profile(slug="bp", name="청사진", page_id="", prompt="p"))
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    code = cli.main(["templates", "read", "bp"])       # 페이지 미지정 → 청사진은 읽을 게 없음
    assert code == 2
    out = capsys.readouterr().out
    assert "프롬프트 전용" in out and "Traceback" not in out
    assert "blocks//children" not in out               # 혼란스러운 Notion 오류가 아님


def test_list_shows_prompt_only_for_page_less(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    P.save(P.Profile(slug="bp", name="청사진", page_id="", prompt="p"))
    assert cli.main(["templates", "list"]) == 0
    out = capsys.readouterr().out
    assert "프롬프트 전용" in out and "DB 0개" not in out


def test_new_prompt_slugifies_slug(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from notionmemory.skills.templates import profile as P
    assert cli.main(["templates", "new-prompt", "My Notes", "--name", "메모"]) == 0
    slugs = [x.slug for x in P.load_all()]
    assert "my-notes" in slugs and "My Notes" not in slugs   # 안전한 파일명


# --- replace / edit / delete — 파괴적 verb 는 --yes 프리뷰 게이트 ---

def _fake_store(monkeypatch, **methods):
    class S:
        def current_markdown(self, pid): return methods.get("current", "alpha beta alpha")
        def is_truncated(self, pid): return methods.get("truncated", False)
        def replace(self, pid, md): methods.setdefault("calls", []).append(("replace", pid, md))
        def edit(self, pid, f, r, all_matches=False):
            methods.setdefault("calls", []).append(("edit", pid, f, r, all_matches))
            if "edit_raises" in methods:
                raise methods["edit_raises"]
        def delete(self, pid, f, all_matches=False):
            methods.setdefault("calls", []).append(("delete", pid, f, all_matches))
            if "delete_raises" in methods:
                raise methods["delete_raises"]
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


def test_edit_multi_match_with_all_mutates_all(monkeypatch):
    m = _fake_store(monkeypatch, current="dup and dup")
    rc = cli.main(["templates", "edit", "slug", "--find", "dup", "--replace", "y",
                   "--all", "--yes"])
    assert rc == 0
    assert ("edit", "pid", "dup", "y", True) in m["calls"]


def test_delete_without_yes_previews_and_does_not_mutate(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="alpha only once")
    rc = cli.main(["templates", "delete", "slug", "--find", "alpha"])
    assert rc == 2
    assert "calls" not in m
    assert "alpha" in capsys.readouterr().out


def test_delete_no_match_is_reported_before_mutation(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="nothing here")
    rc = cli.main(["templates", "delete", "slug", "--find", "zzz"])
    assert rc == 2
    assert "calls" not in m
    assert "찾" in capsys.readouterr().out


def test_delete_multi_match_requires_all(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="dup and dup")
    rc = cli.main(["templates", "delete", "slug", "--find", "dup"])
    assert rc == 2
    assert "calls" not in m
    assert "2" in capsys.readouterr().out


def test_delete_with_yes_mutates(monkeypatch):
    m = _fake_store(monkeypatch, current="alpha only once")
    rc = cli.main(["templates", "delete", "slug", "--find", "alpha", "--yes"])
    assert rc == 0
    assert ("delete", "pid", "alpha", False) in m["calls"]


def test_delete_maps_markdown_edit_error_to_exit_2(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="alpha",
                    delete_raises=MarkdownEditError("No matches found"))
    rc = cli.main(["templates", "delete", "slug", "--find", "alpha", "--yes"])
    assert rc == 2
    assert "No matches" in capsys.readouterr().out


def test_replace_without_yes_previews_and_does_not_mutate(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="old body")
    rc = cli.main(["templates", "replace", "slug", "--markdown", "new body"])
    assert rc == 2
    assert "calls" not in m
    out = capsys.readouterr().out
    assert "교체" in out


def test_replace_with_yes_mutates(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="old body")
    rc = cli.main(["templates", "replace", "slug", "--markdown", "new body", "--yes"])
    assert rc == 0
    assert ("replace", "pid", "new body") in m["calls"]
    assert "pid" in capsys.readouterr().out


def test_replace_without_any_markdown_exits_2(capsys, monkeypatch):
    _fake_store(monkeypatch)
    rc = cli.main(["templates", "replace", "slug"])
    assert rc == 2
    assert "필요합니다" in capsys.readouterr().out


def test_replace_refuses_at_preview_when_truncated(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="old body", truncated=True)
    rc = cli.main(["templates", "replace", "slug", "--markdown", "new body", "--yes"])
    assert rc == 2
    assert "calls" not in m                        # replace 호출 없음
    out = capsys.readouterr().out
    assert "잘립니다" in out or "거부" in out


def test_replace_with_yes_still_mutates_when_not_truncated(monkeypatch, capsys):
    m = _fake_store(monkeypatch, current="old body", truncated=False)
    rc = cli.main(["templates", "replace", "slug", "--markdown", "new body", "--yes"])
    assert rc == 0
    assert ("replace", "pid", "new body") in m["calls"]
