"""하네스 홈 오버라이드(CODEX_HOME / CLAUDE_CONFIG_DIR).

실환경에서 잡힌 결함: Codex 앱이 CODEX_HOME 을 자기 런타임 홈으로 덮은 셸에서
install 을 돌리자 훅이 ~/.codex 에 심겼고, Codex 의 hooks/list 는 그 훅을 전혀
보지 못했다. 훅이 조용히 안 도는 실패 모드다 — 로그도 오류도 없다.
"""
import json

import pytest

from notionmemory.core.install import codex, manifest, runner, teardown


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setattr(runner, "resolve_cli", lambda: "/fake/bin/notionmemory")
    # autouse no_real_cli 가 which 를 막아 codex.available() 이 False 가 된다 —
    # 그러면 install() 이 codex 타깃을 통째로 건너뛰어 이 테스트들이 공허해진다.
    monkeypatch.setattr(codex, "available", lambda: True)
    return tmp_path


def test_defaults_to_dot_dir_under_home(fake_home):
    assert manifest.harness_home("codex") == fake_home / ".codex"
    assert manifest.harness_home("claude") == fake_home / ".claude"


@pytest.mark.parametrize("target,var,hook_name", [
    ("codex", "CODEX_HOME", "hooks.json"),
    ("claude", "CLAUDE_CONFIG_DIR", "settings.json"),
])
def test_env_override_moves_everything(fake_home, monkeypatch, target, var, hook_name):
    elsewhere = fake_home / "elsewhere"
    monkeypatch.setenv(var, str(elsewhere))

    runner.install([target])

    assert (elsewhere / "skills" / "memory" / "SKILL.md").is_file()
    blob = json.dumps(json.loads((elsewhere / hook_name).read_text(encoding="utf-8")))
    assert "notionmemory hook" in blob
    # 기본 위치에는 아무것도 심지 않았다 — 하네스가 안 읽는 곳이다.
    assert not (fake_home / f".{target}").exists()


def test_teardown_sweep_follows_the_override(fake_home, monkeypatch):
    """스윕이 자체 경로 계산을 갖고 있으면 오버라이드 환경에서 심은 것을 영원히 못 지운다."""
    elsewhere = fake_home / "elsewhere"
    monkeypatch.setenv("CODEX_HOME", str(elsewhere))
    runner.install(["codex"])

    paths = {str(s.path) for s in teardown._sweep(["codex"])}
    assert str(elsewhere / "skills" / "memory") in paths
    assert str(elsewhere / "hooks.json") in paths
    assert str(elsewhere / "config.toml") in paths      # 신뢰 항목도 같은 홈을 따라간다


def test_teardown_removes_from_the_override(fake_home, monkeypatch):
    elsewhere = fake_home / "elsewhere"
    monkeypatch.setenv("CODEX_HOME", str(elsewhere))
    runner.install(["codex"])
    assert (elsewhere / "skills" / "memory").is_dir()

    teardown.run(["codex"], purge_config=False, purge_secrets=False, dry_run=False)

    assert not (elsewhere / "skills" / "memory").exists()
    assert not (elsewhere / "hooks.json").exists()      # 전용 파일 — 껍데기도 안 남는다


# ---------------------------------------------------------------------------
# 최종 리뷰 Minor — manifest._home() 이 `paths.state_dir().parents[2]` 로 상태
# 디렉터리에서 거꾸로 걸어 올라가 HOME 을 추론했다. 오늘은 맞지만, 누군가
# state_dir() 에서 XDG_STATE_HOME 을 존중하는 순간 harness_home() 이 조용히
# 엉뚱한 루트에 스킬과 훅을 심기 시작한다. paths 는 이미 HOME 을 직접 안다.
# ---------------------------------------------------------------------------

def test_harness_home_does_not_derive_home_from_state_dir(tmp_path, monkeypatch):
    from notionmemory.core import paths

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    # state_dir 이 다른 깊이/루트로 옮겨가도 하네스 홈은 HOME 을 따라야 한다
    monkeypatch.setattr(paths, "state_dir",
                        lambda: tmp_path / ".local" / "share" / "nm" / "state")
    assert manifest.harness_home("claude") == tmp_path / ".claude"
    assert manifest.harness_home("codex") == tmp_path / ".codex"
