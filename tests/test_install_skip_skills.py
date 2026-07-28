import json
import pytest
from notionmemory.core.install import runner, codex


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setattr(runner, "resolve_cli", lambda: "/fake/bin/notionmemory")
    monkeypatch.setattr(codex, "available", lambda: True)   # codex 바이너리 없이도 경로 진행
    return tmp_path


def _receipt_handlers(home):
    from notionmemory.core import paths
    data = json.loads(paths.receipt_path().read_text(encoding="utf-8"))
    return {a["handler"] for a in data["artifacts"]}


def test_skip_skills_installs_hooks_not_skill_mirror(home):
    runner.install(["codex"], skip_skills=True)
    skills_dir = home / ".codex" / "skills"
    assert not skills_dir.exists() or not any(skills_dir.iterdir()), "스킬 미러가 생기면 안 된다"
    assert (home / ".codex" / "hooks.json").is_file(), "훅은 설치돼야 한다"
    handlers = _receipt_handlers(home)
    assert "skill_mirror" not in handlers, "영수증에 스킬 미러가 없어야 teardown 이 오지 않는다"
    assert "json_hook_block" in handlers


def test_default_install_still_mirrors_skills(home):
    runner.install(["codex"])                  # skip_skills 기본 False
    assert (home / ".codex" / "skills" / "calendar").is_dir()
    assert "skill_mirror" in _receipt_handlers(home)


def test_skip_skills_is_codex_scoped_not_claude(home):
    runner.install(["claude"], skip_skills=True)
    assert (home / ".claude" / "skills" / "calendar").is_dir(), \
        "skip-skills is codex-only; claude skills must still mirror"
