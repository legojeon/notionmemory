"""install — Claude 타깃 전체 경로. HOME 을 임시로 갈아끼워 실제 홈을 건드리지 않는다."""
import json

import pytest

from notionmemory.core.install import manifest, receipt, runner


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setattr(runner, "resolve_cli", lambda: "/fake/bin/notionmemory")
    return tmp_path


def test_resolve_cli_raises_when_missing(monkeypatch):
    monkeypatch.setattr(runner.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="PATH"):
        runner.resolve_cli()


def test_install_claude_creates_skills_and_hooks(fake_home):
    runner.install(["claude"])
    skills = fake_home / ".claude" / "skills"
    for name in ("memory", "calendar", "templates", "settings"):
        assert (skills / name / "SKILL.md").is_file(), name
    settings = json.loads((fake_home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for event in ("SessionStart", "PreCompact", "Stop"):
        assert "notionmemory hook" in json.dumps(settings["hooks"][event])
    # Stop 은 컨텍스트 주입용으로는 여전히 안 쓴다(주입 채널이 없다) — 대신
    # Second Brain v2 부터 큐잉 전용(session-stop, 비블로킹)으로 등록된다.
    assert "notionmemory hook session-stop" in json.dumps(settings["hooks"]["Stop"])


def test_install_hook_command_is_absolute(fake_home):
    runner.install(["claude"])
    settings = json.loads((fake_home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    blob = json.dumps(settings["hooks"]["SessionStart"])
    assert "/fake/bin/notionmemory hook session-start" in blob


def test_install_writes_receipt(fake_home):
    runner.install(["claude"])
    entries = receipt.read()
    ids = {e["id"] for e in entries}
    assert "claude.hooks" in ids
    assert "claude.skills.memory" in ids
    assert all(e["target"] in ("claude", "shared") for e in entries)


def test_install_is_idempotent(fake_home):
    runner.install(["claude"])
    first = (fake_home / ".claude" / "settings.json").read_text(encoding="utf-8")
    runner.install(["claude"])
    assert (fake_home / ".claude" / "settings.json").read_text(encoding="utf-8") == first
    # 영수증도 중복 누적되지 않는다
    ids = [e["id"] for e in receipt.read()]
    assert len(ids) == len(set(ids))


def test_manifest_hook_markers_include_legacy():
    """구 마커(memory_hooks)를 인식해야 구버전 설치를 교체·제거할 수 있다."""
    assert "notionmemory hook" in manifest.HOOK_MARKERS
    assert "memory_hooks" in manifest.HOOK_MARKERS


def test_manifest_skill_specs_are_owned_by_their_skill():
    specs = manifest.build(["claude"], "/fake/bin/notionmemory")
    memory = next(s for s in specs if s.id == "claude.skills.memory")
    assert memory.owner == "memory"


# ---------------------------------------------------------------------------
# 최종 리뷰 Critical — 사이드카 없는 동명 디렉터리(사용자가 직접 만든 스킬이거나,
# 마커를 안 남기던 구 scripts/sync_skills.py 가 심은 것)를 install 이 말없이
# 통째로 날렸다. 이제는 손대지 않고 건너뛴다 — 그리고 §4.4 부분 실패 규칙대로
# 나머지 설치는 계속 진행하고, 건너뛴 것은 영수증에 넣지 않는다.
# ---------------------------------------------------------------------------

def test_install_skips_unowned_skill_dir_and_keeps_going(fake_home):
    mine = fake_home / ".claude" / "skills" / "memory"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("사용자가 직접 만든 것\n", encoding="utf-8")

    lines = runner.install(["claude"])

    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "사용자가 직접 만든 것\n"
    assert any(str(mine) in ln for ln in lines), lines
    # 부분 실패 — 나머지는 정상 설치된다
    for name in ("calendar", "templates", "settings"):
        assert (fake_home / ".claude" / "skills" / name / "SKILL.md").is_file(), name
    assert json.loads(
        (fake_home / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
    # 심지 못한 것은 영수증에 없다 — teardown 이 남의 디렉터리를 지우면 안 되므로
    ids = {e["id"] for e in receipt.read()}
    assert "claude.skills.memory" not in ids
    assert "claude.skills.calendar" in ids
