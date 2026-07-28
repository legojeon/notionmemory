"""설치 → 검증 → 제거 → 잔재 0. HOME 을 갈아끼워 실제 홈을 건드리지 않는다.

수용 기준 매트릭스의 1층: 설치·teardown 칸 (Claude·Codex 양쪽).
"""
import json

import pytest

from notionmemory.core.install import codex, runner, teardown

SAMPLE_HOOKS = [
    {"key": "{hooks}:session_start:0:0", "currentHash": "sha256:aaa",
     "trustStatus": "untrusted", "sourcePath": "{hooks}", "source": "user",
     "command": "/fake/bin/notionmemory hook session-start"},
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setattr(runner, "resolve_cli", lambda: "/fake/bin/notionmemory")
    return tmp_path


def _residue(home) -> list[str]:
    """teardown 이후 남아 있으면 안 되는 것들."""
    out = []
    for rel in (".claude/skills", ".codex/skills"):
        d = home / rel
        if d.is_dir() and any(d.iterdir()):
            out.append(str(d))
    # Claude 의 settings.json 은 하네스·사용자 소유라 비어도 남는다 — 우리 흔적만 본다.
    settings = home / ".claude" / "settings.json"
    if settings.is_file() and "notionmemory" in settings.read_text(encoding="utf-8"):
        out.append(str(settings))
    # Codex 의 hooks.json 은 훅 전용이고 이 HOME 에는 우리가 만든 것밖에 없다 —
    # 존재 자체가 잔재다. 내용에 "notionmemory" 가 있는지로 보면 `{"hooks": {}}`
    # 껍데기가 그대로 통과한다(실환경에서 잡힌 L5 가 정확히 그 형태였다).
    codex_hooks = home / ".codex" / "hooks.json"
    if codex_hooks.exists():
        out.append(str(codex_hooks))
    cfg = home / ".codex" / "config.toml"
    if cfg.is_file() and "hooks.state" in cfg.read_text(encoding="utf-8"):
        out.append(str(cfg))
    if (home / ".local" / "state" / "notionmemory").exists():
        out.append("state dir")
    return out


def test_claude_install_teardown_leaves_no_residue(home):
    runner.install(["claude"])
    assert (home / ".claude" / "skills" / "memory" / "SKILL.md").is_file()
    teardown.run(["claude"])
    assert _residue(home) == []


def test_codex_install_teardown_leaves_no_residue(home, monkeypatch):
    hooks_path = str(home / ".codex" / "hooks.json")
    sample = [dict(h, key=h["key"].format(hooks=hooks_path),
                   sourcePath=h["sourcePath"].format(hooks=hooks_path))
              for h in SAMPLE_HOOKS]
    monkeypatch.setattr(codex, "available", lambda: True)
    monkeypatch.setattr(codex, "hooks_list", lambda cwd="": sample)

    runner.install(["codex"], trust_codex=True)
    assert (home / ".codex" / "skills" / "memory" / "SKILL.md").is_file()
    config = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "trusted_hash" in config

    teardown.run(["codex"])
    assert _residue(home) == []


def test_both_targets_are_functionally_equivalent(home, monkeypatch):
    """같은 이벤트 집합·같은 훅이 양쪽에 설치돼야 한다(기능 동등성) — 단 Codex
    쪽 명령에는 `--harness codex` 가 붙는다.

    실기(2026-07-21)로 확인됨: Codex 는 Stop/PreCompact 훅의 평문 stdout 을
    실패(`hook: Stop Failed`) 처리한다 — SessionStart 는 받아들이는데 Stop/
    PreCompact 는 거부해, 훅이 자신을 부른 하네스를 알아야 stdout 형태를 맞게
    낼 수 있다. 그래서 "완전히 동일한 명령 문자열"은 더 이상 옳은 기능 동등성
    정의가 아니다 — "같은 이벤트에 같은 훅이 걸리고, Codex 쪽에만 harness
    플래그가 얹힌다, 그 외에는 동일하다"가 맞는 정의다.
    """
    hooks_path = str(home / ".codex" / "hooks.json")
    sample = [dict(h, key=h["key"].format(hooks=hooks_path),
                   sourcePath=h["sourcePath"].format(hooks=hooks_path))
              for h in SAMPLE_HOOKS]
    monkeypatch.setattr(codex, "available", lambda: True)
    monkeypatch.setattr(codex, "hooks_list", lambda cwd="": sample)
    runner.install(["claude", "codex"], trust_codex=True)

    claude = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    codex_hooks = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    assert set(claude["hooks"]) == set(codex_hooks["hooks"])

    claude_blob = json.dumps(claude["hooks"], sort_keys=True)
    codex_blob = json.dumps(codex_hooks["hooks"], sort_keys=True)
    assert "--harness codex" not in claude_blob      # Claude 쪽은 플래그 없이 그대로
    assert "--harness codex" in codex_blob            # Codex 쪽은 실제로 플래그가 박혀 있다
    assert claude_blob == codex_blob.replace(" --harness codex", "")

    claude_skills = sorted(p.name for p in (home / ".claude" / "skills").iterdir())
    codex_skills = sorted(p.name for p in (home / ".codex" / "skills").iterdir())
    assert claude_skills == codex_skills


def test_install_twice_then_teardown_once_is_clean(home):
    runner.install(["claude"])
    runner.install(["claude"])
    assert (home / ".claude" / "skills" / "memory" / "SKILL.md").is_file()
    teardown.run(["claude"])
    assert _residue(home) == []
