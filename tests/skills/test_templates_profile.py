"""프로필 파일 — 단일 소스. 상태 디렉터리 밖으로 나가지 않는다(스펙 §9)."""
import pytest

from notionmemory.skills.templates import profile as P


@pytest.fixture(autouse=True)
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _sample(slug="job-tracker") -> P.Profile:
    return P.Profile(
        slug=slug, name="Job Application Tracker", page_id="2a1b", page_url="https://n/2a1b",
        enabled=True, health="ok", health_checked_at="2026-07-22",
        schema_fetched_at="2026-07-22", summary="지원 현황 추적",
        capabilities=["date", "text"],
        databases=[{
            "key": "applications", "title": "Applications", "database_id": "8c3f",
            "data_source_id": "91ab", "title_property": "Position", "missing": False,
            "properties": [
                {"name": "Position", "type": "title", "writable": True, "filterable": True},
                {"name": "Status", "type": "status", "writable": True, "filterable": True,
                 "choices": ["Applied", "Interview"]},
                {"name": "Days Open", "type": "formula", "writable": False, "filterable": True},
            ]}],
        body="## 무엇에 쓰는 템플릿인가\n지원 추적.\n")


def test_store_dir_is_under_state_dir(state_home, monkeypatch, no_real_state_dir):
    # 파생 규칙(HOME→state_dir→templates) 자체가 검증 대상 — conftest 격리를 원본으로 되돌린다.
    from notionmemory.core import paths
    monkeypatch.setattr(paths, "state_dir", no_real_state_dir)
    assert P.store_dir() == state_home / ".local" / "state" / "notionmemory" / "templates"


def test_round_trip_preserves_everything():
    saved = P.save(_sample())
    assert saved.name == "job-tracker.md"
    got = P.load("job-tracker")
    assert got == _sample()


def test_body_survives_a_yaml_looking_line():
    """본문에 '---' 나 'key: value' 가 있어도 프론트매터로 오해하지 않는다."""
    p = _sample()
    p.body = "## 노트\nkey: value\n\n---\n\n끝\n"
    P.save(p)
    assert P.load("job-tracker").body == p.body


def test_load_missing_slug_raises_with_available_list():
    P.save(_sample("reading-list"))
    with pytest.raises(ValueError) as e:
        P.load("nope")
    assert "nope" in str(e.value) and "reading-list" in str(e.value)


def test_list_slugs_is_sorted_and_delete_removes():
    P.save(_sample("zeta"))
    P.save(_sample("alpha"))
    assert P.list_slugs() == ["alpha", "zeta"]
    assert P.delete("alpha") is True
    assert P.delete("alpha") is False
    assert P.list_slugs() == ["zeta"]


def test_load_all_skips_unparsable_files_without_crashing():
    P.save(_sample())
    P.store_dir().joinpath("broken.md").write_text("not a profile", encoding="utf-8")
    assert [p.slug for p in P.load_all()] == ["job-tracker"]


def test_find_db_lists_available_keys_on_miss():
    p = _sample()
    assert P.find_db(p, "applications")["title"] == "Applications"
    with pytest.raises(ValueError) as e:
        P.find_db(p, "applicaton")
    assert "applications" in str(e.value)


def test_find_prop_suggests_close_name_and_points_at_refresh():
    db = _sample().databases[0]
    assert P.find_prop(db, "Status")["type"] == "status"
    with pytest.raises(ValueError) as e:
        P.find_prop(db, "Staus")
    msg = str(e.value)
    assert "Status" in msg
    assert "refresh" in msg          # 드리프트 탈출구를 항상 알려준다(스펙 §8)


def test_injection_line_is_empty_when_nothing_registered():
    assert P.injection_line([]) == ""


def test_injection_line_excludes_disabled_and_trashed():
    ok = _sample("job-tracker")
    off = _sample("off-one"); off.enabled = False
    trashed = _sample("trashed-one"); trashed.health = "trashed"
    degraded = _sample("degraded-one"); degraded.health = "degraded"
    line = P.injection_line([ok, off, trashed, degraded])
    assert "job-tracker" in line and "degraded-one" in line
    assert "off-one" not in line and "trashed-one" not in line


def test_injection_line_never_starts_with_a_json_sniffable_char():
    """훅 stdout 첫 글자가 '[' 나 '{' 면 Claude Code 2.1.215+ 가 훅을 실패 처리한다."""
    line = P.injection_line([_sample()])
    assert line.startswith("notionmemory templates:")
    assert line[0] not in "[{"


def test_profile_round_trips_the_pages_field():
    from notionmemory.skills.templates import profile as P
    p = P.Profile(slug="doc", name="Doc", page_id="pg",
                  pages=[{"page_id": "pg", "title": "Doc", "depth": 0, "parent": None,
                          "headings": ["소개", "본론"], "databases": ["notes"]}])
    P.save(p)
    got = P.load("doc")
    assert got.pages == p.pages


def test_profile_pages_defaults_to_empty_list():
    from notionmemory.skills.templates import profile as P
    p = P.Profile(slug="d", name="D", page_id="pg")
    assert p.pages == []


def _profile(**kw):
    base = dict(slug="job", name="Job Tracker", page_id="pg", page_url="u")
    base.update(kw)
    return P.Profile(**base)


def test_prompt_defaults_empty():
    assert _profile().prompt == ""


def test_prompt_round_trips_through_save_load():
    P.save(_profile(prompt="지원현황을 표로, 담담한 톤으로 정리해라"))
    got = P.load("job")
    assert got.prompt == "지원현황을 표로, 담담한 톤으로 정리해라"


def test_load_old_profile_without_prompt_field_defaults_empty():
    # 구버전 프로필(프론트매터에 prompt 없음)도 기본값으로 로드된다
    P.save(_profile())                      # prompt="" 로 저장
    path = P.path_for("job")
    text = path.read_text(encoding="utf-8").replace("prompt: ''\n", "")
    path.write_text(text, encoding="utf-8")  # prompt 줄 제거해 구버전 흉내
    assert P.load("job").prompt == ""
