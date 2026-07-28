"""templates 설치물 — 프로필은 걷히고 Notion 데이터는 남는다(CLAUDE.md 규칙 5)."""
import pytest

from notionmemory.core import skill_assets
from notionmemory.core.install import manifest, teardown
from notionmemory.skills.templates import profile as P


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    return tmp_path


def _save(slug):
    P.save(P.Profile(slug=slug, name=slug, page_id="pg", databases=[]))


def test_templates_owns_the_skill_mirror_in_the_manifest():
    """이름으로 지우지 않는다 — 매니페스트에 항목이 있어야 teardown 이 찾는다."""
    owners = {s.owner for s in manifest.build(["claude", "codex"], "/x/notionmemory")}
    assert "templates" in owners
    assert "templates" not in manifest.OWNS_NOTHING


def test_templates_ships_a_skill_md_so_the_mirror_exists():
    assert "templates" in skill_assets.skill_names()


def test_teardown_removes_profile_files_with_the_state_directory():
    _save("job-tracker")
    assert P.store_dir().is_dir()
    teardown.run(["claude"], dry_run=False)
    assert not P.store_dir().exists()


def test_teardown_announces_how_many_profiles_go_and_that_notion_survives():
    _save("job-tracker")
    _save("reading-list")
    lines = teardown.run(["claude"], dry_run=True)
    joined = "\n".join(lines)
    assert "2" in joined and "Notion" in joined and "re-register" in joined


def test_teardown_says_nothing_about_profiles_when_there_are_none():
    lines = "\n".join(teardown.run(["claude"], dry_run=True))
    assert "re-register" not in lines


def test_dry_run_does_not_delete_profiles():
    _save("job-tracker")
    teardown.run(["claude"], dry_run=True)
    assert P.exists("job-tracker")


def test_profiles_live_under_the_state_dir_so_no_extra_artifact_is_needed(isolated_home):
    """이 위치 제약 자체가 계약이다 — 여기를 벗어나면 ArtifactSpec 이 필요해진다."""
    from notionmemory.core import paths
    assert P.store_dir().is_relative_to(paths.state_dir())


def test_teardown_never_instantiates_a_notion_session(monkeypatch):
    """진짜 불변식은 '지워진다'가 아니라 'Notion 은 건드리지 않는다'다.

    프록시(문자열 "Notion" 이 안내문에 들어 있는지)가 아니라, teardown 경로가
    실제로 NotionSession 을 만들지 않는지를 못 박는다 — 여기서 호출되면 즉시
    실패하도록 생성자를 폭탄으로 바꾼다.
    """
    from notionmemory.core.notion_client import NotionSession

    def _boom(self, *a, **k):
        raise AssertionError("teardown 이 NotionSession 을 만들었다 — 사용자 데이터를 건드릴 뻔했다")

    monkeypatch.setattr(NotionSession, "__init__", _boom)
    _save("job-tracker")
    teardown.run(["claude"], dry_run=False)
    assert not P.store_dir().exists()


def test_notes_is_a_legacy_skill_for_orphan_cleanup():
    from notionmemory.core.install import teardown
    assert "notes" in teardown.LEGACY_SKILL_NAMES


def test_templates_remove_never_instantiates_a_notion_session(monkeypatch):
    """`templates remove` 는 로컬 프로필 파일만 지운다 — Notion 페이지는 그대로다.

    CLI 의 remove 액션(cli.py `_cmd_templates`)이 `profile.delete()`만 부르고
    NotionSession 근처에도 안 가는지를 실제 CLI 진입점으로 확인한다.
    """
    from notionmemory import cli
    from notionmemory.core.notion_client import NotionSession

    def _boom(self, *a, **k):
        raise AssertionError("templates remove 가 NotionSession 을 만들었다 — Notion 삭제 위험")

    monkeypatch.setattr(NotionSession, "__init__", _boom)
    _save("job-tracker")
    rc = cli.main(["templates", "remove", "job-tracker"])
    assert rc == 0
    assert not P.exists("job-tracker")
