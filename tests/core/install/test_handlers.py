"""아티팩트 핸들러 — 소유권 판정, 멱등, 남의 것 보존."""
import json
from pathlib import Path

from notionmemory.core.install.handlers import (
    OWNED_MARKER_FILE, JsonHookBlock, SkillMirror)
from notionmemory.core.install.spec import ArtifactSpec


def _skill_spec(src: Path, dest: Path) -> ArtifactSpec:
    return ArtifactSpec(id="claude.skills.memory", owner="memory", handler="skill_mirror",
                        target="claude", path=dest,
                        payload={"source": str(src)}, markers=("memory",))


def _make_source(tmp_path: Path) -> Path:
    src = tmp_path / "src" / "memory"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: memory\n---\n", encoding="utf-8")
    return src


def test_skill_mirror_installs_with_owned_marker(tmp_path):
    src = _make_source(tmp_path)
    dest = tmp_path / "home" / ".claude" / "skills" / "memory"
    assert SkillMirror().install(_skill_spec(src, dest)) is True
    assert (dest / "SKILL.md").is_file()
    assert (dest / OWNED_MARKER_FILE).is_file()


def test_skill_mirror_is_idempotent(tmp_path):
    src = _make_source(tmp_path)
    dest = tmp_path / "home" / ".claude" / "skills" / "memory"
    spec = _skill_spec(src, dest)
    SkillMirror().install(spec)
    SkillMirror().install(spec)
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "---\nname: memory\n---\n"


def test_skill_mirror_removes_only_owned(tmp_path):
    """마커 없는 동명 디렉터리는 사용자 것이므로 절대 지우지 않는다."""
    src = _make_source(tmp_path)
    dest = tmp_path / "home" / ".claude" / "skills" / "memory"
    spec = _skill_spec(src, dest)
    SkillMirror().install(spec)
    assert SkillMirror().remove(spec) is True
    assert not dest.exists()

    # 사용자가 직접 만든 동명 디렉터리 — 마커가 없다
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("mine\n", encoding="utf-8")
    assert SkillMirror().remove(spec) is False
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "mine\n"


def test_skill_mirror_detect(tmp_path):
    src = _make_source(tmp_path)
    dest = tmp_path / "home" / ".claude" / "skills" / "memory"
    spec = _skill_spec(src, dest)
    assert SkillMirror().detect(spec) is False
    SkillMirror().install(spec)
    assert SkillMirror().detect(spec) is True


def _hook_spec(path: Path) -> ArtifactSpec:
    events = {
        "SessionStart": [{"hooks": [{"type": "command",
                                     "command": "/bin/notionmemory hook session-start",
                                     "timeout": 20}]}],
        "Stop": [{"hooks": [{"type": "command",
                             "command": "/bin/notionmemory hook save-reminder",
                             "timeout": 20}]}],
    }
    return ArtifactSpec(id="claude.hooks", owner="_core", handler="json_hook_block",
                        target="claude", path=path, payload={"events": events},
                        markers=("notionmemory hook", "memory_hooks"))


def test_json_hook_block_creates_and_is_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    spec = _hook_spec(settings)
    assert JsonHookBlock().install(spec) is True
    first = settings.read_text(encoding="utf-8")
    data = json.loads(first)
    assert "notionmemory hook" in json.dumps(data["hooks"]["SessionStart"])
    assert JsonHookBlock().install(spec) is False
    assert settings.read_text(encoding="utf-8") == first


def test_json_hook_block_preserves_foreign_and_replaces_legacy(tmp_path):
    settings = tmp_path / "settings.json"
    foreign = {"hooks": [{"type": "command", "command": "/other/tool.sh"}]}
    legacy = {"hooks": [{"type": "command",
                         "command": "/old/venv/bin/python /old/scripts/memory_hooks/session_start.py"}]}
    settings.write_text(json.dumps({"model": "keep-me",
                                    "hooks": {"Stop": [foreign, legacy]}}), encoding="utf-8")
    JsonHookBlock().install(_hook_spec(settings))
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["model"] == "keep-me"          # 최상위 사용자 키 보존
    stop = data["hooks"]["Stop"]
    assert foreign in stop                      # 남의 훅 보존
    assert "/old/scripts/memory_hooks" not in json.dumps(stop)   # 레거시 교체
    ours = [e for e in stop if "notionmemory hook" in json.dumps(e)]
    assert len(ours) == 1


def test_json_hook_block_remove_leaves_foreign(tmp_path):
    settings = tmp_path / "settings.json"
    foreign = {"hooks": [{"type": "command", "command": "/other/tool.sh"}]}
    settings.write_text(json.dumps({"hooks": {"Stop": [foreign]}}), encoding="utf-8")
    spec = _hook_spec(settings)
    JsonHookBlock().install(spec)
    assert JsonHookBlock().remove(spec) is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["hooks"]["Stop"] == [foreign]
    assert "SessionStart" not in data["hooks"] or data["hooks"]["SessionStart"] == []


def test_json_hook_block_remove_strips_legacy_markers(tmp_path):
    """구 마커(memory_hooks)만 있는 설치도 teardown 이 찾아 제거한다."""
    settings = tmp_path / "settings.json"
    legacy = {"hooks": [{"type": "command",
                         "command": "/old/venv/bin/python /old/scripts/memory_hooks/save_reminder.py"}]}
    settings.write_text(json.dumps({"hooks": {"Stop": [legacy]}}), encoding="utf-8")
    spec = _hook_spec(settings)
    assert JsonHookBlock().detect(spec) is True
    assert JsonHookBlock().remove(spec) is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "memory_hooks" not in json.dumps(data)


def test_json_hook_block_does_not_false_positive_on_path_fragment(tmp_path):
    """리뷰 재현: `memory_hooks`가 남의 경로 조각(디렉터리 이름의 일부)으로 우연히
    들어간 command 는 우리 것이 아니다 — CodexTrust 에서 이미 고친 것과 같은
    부분일치 버그가 JsonHookBlock 에도 있었다(리뷰 Important). 진짜 레거시
    스크립트 경로는 여전히 인식·제거돼야 한다."""
    settings = tmp_path / "settings.json"
    foreign = {"hooks": [{"type": "command",
                          "command": "/Users/bob/backups/old_memory_hooks_project/run.sh"}]}
    legacy = {"hooks": [{"type": "command",
                         "command": "/old/venv/bin/python /old/scripts/memory_hooks/session_start.py"}]}
    settings.write_text(json.dumps({"hooks": {"Stop": [foreign, legacy]}}), encoding="utf-8")
    spec = _hook_spec(settings)

    JsonHookBlock().install(spec)
    data = json.loads(settings.read_text(encoding="utf-8"))
    stop = data["hooks"]["Stop"]
    assert foreign in stop                                        # 남의 것 — 설치 후에도 보존
    assert "/old/scripts/memory_hooks/session_start.py" not in json.dumps(stop)  # 레거시 교체

    settings.write_text(json.dumps({"hooks": {"Stop": [foreign, legacy]}}), encoding="utf-8")
    assert JsonHookBlock().remove(spec) is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    stop = data["hooks"]["Stop"]
    assert foreign in stop                                        # 남의 것 — 제거 후에도 보존
    assert "/old/scripts/memory_hooks/session_start.py" not in json.dumps(stop)  # 레거시만 제거


def test_json_hook_block_recognizes_codex_harness_suffix(tmp_path):
    """Codex 타깃 명령에는 `--harness codex` 가 붙는다(manifest.HOOK_EVENTS) — 그
    꼬리가 붙어도 여전히 우리 것으로 인식·제거돼야 한다. 이 회귀는 실제로 한 번
    터졌다: `_CLI_HOOK_COMMAND_RE` 가 명령 끝을 `hook \\S+$` 로 앵커링해서, 꼬리를
    허용하도록 고치기 전까지는 codex.hooks 를 방금 설치하고도 detect()가 False 를
    반환해 teardown 이 지우지 못하고 재설치도 계속 중복 병합했다."""
    settings = tmp_path / "settings.json"
    events = {
        "SessionStart": [{"hooks": [{"type": "command",
                                     "command": "/bin/notionmemory hook session-start "
                                                "--harness codex",
                                     "timeout": 20}]}],
        "Stop": [{"hooks": [{"type": "command",
                             "command": "/bin/notionmemory hook save-reminder "
                                        "--harness codex",
                             "timeout": 20}]}],
    }
    spec = ArtifactSpec(id="codex.hooks", owner="_core", handler="json_hook_block",
                        target="codex", path=settings, payload={"events": events},
                        markers=("notionmemory hook", "memory_hooks"))
    assert JsonHookBlock().install(spec) is True
    assert JsonHookBlock().detect(spec) is True
    assert JsonHookBlock().install(spec) is False       # 멱등 — 다시 넣어도 변경 없음
    assert JsonHookBlock().remove(spec) is True
    # codex 타깃의 훅 파일은 전용이라, 우리 것만 있던 파일은 통째로 사라진다.
    assert not settings.exists()


def _dedicated_spec(path):
    """Codex 의 hooks.json 처럼 훅 전용 파일에 붙는 명세.

    전용 여부는 target 으로 결정된다(manifest.hook_file_is_dedicated) — payload 에
    담으면 teardown 이 만드는 명세(payload={})에서 조용히 꺼진다."""
    spec = _hook_spec(path)
    return ArtifactSpec(id="codex.hooks", owner="_core", handler="json_hook_block",
                        target="codex", path=path, payload=spec.payload,
                        markers=spec.markers)


def test_dedicated_hook_file_is_deleted_when_nothing_remains(tmp_path):
    """실환경 teardown 에서 잡힌 잔재: 우리가 만든 ~/.codex/hooks.json 이 블록만
    빠지고 `{"hooks": {}}` 18바이트 껍데기로 남았다. 계약은 "심은 것은 teardown
    한 번으로 전부 지워진다"이므로 빈 껍데기도 잔재다."""
    hooks_json = tmp_path / "hooks.json"
    spec = _dedicated_spec(hooks_json)
    assert JsonHookBlock().install(spec) is True
    assert hooks_json.exists()
    assert JsonHookBlock().remove(spec) is True
    assert not hooks_json.exists()
    assert JsonHookBlock().remove(spec) is False        # 이미 없는 파일에 멱등


def test_dedicated_hook_file_survives_when_user_has_own_content(tmp_path):
    """전용 파일이라도 사용자가 자기 훅이나 다른 키를 넣어뒀으면 지우지 않는다."""
    for extra in ({"hooks": {"Stop": [{"hooks": [{"type": "command",
                                                  "command": "/other/tool.sh"}]}]}},
                  {"someOtherSetting": 1}):
        hooks_json = tmp_path / f"hooks-{list(extra)[0]}.json"
        hooks_json.write_text(json.dumps(extra), encoding="utf-8")
        spec = _dedicated_spec(hooks_json)
        JsonHookBlock().install(spec)
        assert JsonHookBlock().remove(spec) is True
        assert hooks_json.exists(), extra
        assert "notionmemory" not in hooks_json.read_text(encoding="utf-8")


def test_non_dedicated_hook_file_is_kept_even_when_empty(tmp_path):
    """Claude 의 settings.json 은 하네스·사용자 소유다 — 비어도 지우지 않는다."""
    settings = tmp_path / "settings.json"
    spec = _hook_spec(settings)                          # dedicated 없음
    JsonHookBlock().install(spec)
    assert JsonHookBlock().remove(spec) is True
    assert settings.exists()
    assert json.loads(settings.read_text(encoding="utf-8")) == {"hooks": {}}


# ---------------------------------------------------------------------------
# 최종 리뷰 Critical — install 은 `if dest.exists(): rmtree(dest)` 로 사용자가
# 직접 만든 동명 디렉터리를 통째로 날렸다. remove 는 사이드카가 없으면 거부하는데
# install 만 판정이 없었다. 스펙 §5.3 이 memory/calendar/notes 는 사용자가 직접
# 만들 법한 이름이라고 길게 논증한 바로 그 사고다.
# ---------------------------------------------------------------------------

def test_skill_mirror_install_refuses_to_destroy_unowned_dir(tmp_path):
    import pytest

    from notionmemory.core.install.handlers import OwnershipConflict

    src = _make_source(tmp_path)
    dest = tmp_path / "home" / ".claude" / "skills" / "memory"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("사용자가 직접 만든 것\n", encoding="utf-8")

    with pytest.raises(OwnershipConflict):
        SkillMirror().install(_skill_spec(src, dest))
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "사용자가 직접 만든 것\n"
    assert not (dest / OWNED_MARKER_FILE).exists()


def test_skill_mirror_install_replaces_our_own_dir(tmp_path):
    """우리 사이드카가 있으면 예전처럼 교체한다 — 재설치는 계속 멱등이다."""
    src = _make_source(tmp_path)
    dest = tmp_path / "home" / ".claude" / "skills" / "memory"
    spec = _skill_spec(src, dest)
    SkillMirror().install(spec)
    (dest / "stale.md").write_text("이전 설치가 남긴 파일\n", encoding="utf-8")
    assert SkillMirror().install(spec) is True
    assert not (dest / "stale.md").exists()


def test_skill_mirror_install_refuses_symlink_at_dest(tmp_path):
    """심링크도 우리 것이라는 근거가 없다 — 따라가서 남의 디렉터리를 지우면 안 된다."""
    import pytest

    from notionmemory.core.install.handlers import OwnershipConflict

    src = _make_source(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.md").write_text("남의 것\n", encoding="utf-8")
    dest = tmp_path / "home" / ".claude" / "skills" / "memory"
    dest.parent.mkdir(parents=True)
    dest.symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(OwnershipConflict):
        SkillMirror().install(_skill_spec(src, dest))
    assert (elsewhere / "keep.md").is_file()


def test_install_strips_our_entries_from_events_we_no_longer_use(tmp_path):
    """매니페스트에서 이벤트를 빼면 이미 설치된 그 항목이 고아가 된다.

    install() 이 payload 의 이벤트만 훑으면, 구버전이 심은 Stop 항목이 업그레이드
    후에도 계속 발화한다 — 사용자는 "지웠는데 왜 아직 뜨지"를 겪고, 우리는 매니페스트를
    유일한 진실로 삼는다는 계약(CLAUDE.md)을 어긴다. 남의 항목은 물론 보존한다.
    """
    settings = tmp_path / "settings.json"
    old = _hook_spec(settings)                       # SessionStart + Stop 을 심는 구 명세
    JsonHookBlock().install(old)
    assert "Stop" in json.loads(settings.read_text(encoding="utf-8"))["hooks"]

    foreign = {"hooks": [{"type": "command", "command": "/other/tool.sh"}]}
    raw = json.loads(settings.read_text(encoding="utf-8"))
    raw["hooks"]["Stop"].append(foreign)
    settings.write_text(json.dumps(raw), encoding="utf-8")

    new = ArtifactSpec(                              # Stop 을 뺀 새 명세
        id=old.id, owner=old.owner, handler=old.handler, target=old.target,
        path=settings, payload={"events": {"SessionStart": old.payload["events"]["SessionStart"]}},
        markers=old.markers)
    assert JsonHookBlock().install(new) is True

    hooks = json.loads(settings.read_text(encoding="utf-8"))["hooks"]
    assert "notionmemory hook" not in json.dumps(hooks.get("Stop", []))
    assert foreign in hooks["Stop"]                  # 남의 것은 그대로
    assert "notionmemory hook" in json.dumps(hooks["SessionStart"])


def test_install_drops_the_event_key_when_only_ours_was_there(tmp_path):
    settings = tmp_path / "settings.json"
    old = _hook_spec(settings)
    JsonHookBlock().install(old)
    new = ArtifactSpec(
        id=old.id, owner=old.owner, handler=old.handler, target=old.target,
        path=settings, payload={"events": {"SessionStart": old.payload["events"]["SessionStart"]}},
        markers=old.markers)
    JsonHookBlock().install(new)
    assert "Stop" not in json.loads(settings.read_text(encoding="utf-8"))["hooks"]
