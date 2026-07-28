"""teardown — 영수증 ∪ 마커 스윕, 보존 규칙, 레거시 잔재."""
import json

import pytest

from notionmemory.core.install import receipt, runner, teardown
from notionmemory.core.install.handlers import OWNED_MARKER_FILE


@pytest.fixture
def installed(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setattr(runner, "resolve_cli", lambda: "/fake/bin/notionmemory")
    runner.install(["claude"])
    return tmp_path


def test_teardown_removes_everything_it_installed(installed):
    teardown.run(["claude"])
    assert not (installed / ".claude" / "skills" / "memory").exists()
    settings = json.loads((installed / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "notionmemory hook" not in json.dumps(settings)


def test_teardown_preserves_config_and_notion_by_default(installed):
    cfg = installed / ".config" / "notionmemory" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("skills: {}\n", encoding="utf-8")
    teardown.run(["claude"])
    assert cfg.is_file(), "config 는 기본 보존이다"


def test_teardown_purge_config_removes_it(installed):
    cfg = installed / ".config" / "notionmemory" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("skills: {}\n", encoding="utf-8")
    teardown.run(["claude"], purge_config=True)
    assert not cfg.exists()


def test_teardown_clears_receipt(installed):
    teardown.run(["claude"])
    assert receipt.read() == []


def test_teardown_finds_legacy_skill_dirs_without_receipt(tmp_path, monkeypatch):
    """구 이름으로 설치된 잔재는 영수증에 없다 — 마커 스윕이 잡는다."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    legacy = tmp_path / ".claude" / "skills" / "notes-capture"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_text("old\n", encoding="utf-8")
    teardown.run(["claude"])
    assert not legacy.exists()


def test_teardown_finds_legacy_hook_entries_without_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"hooks": {"Stop": [
        {"hooks": [{"type": "command",
                    "command": "/old/venv/bin/python /old/scripts/memory_hooks/session_start.py"}]}]}}),
        encoding="utf-8")
    teardown.run(["claude"])
    assert "memory_hooks" not in settings.read_text(encoding="utf-8")


def test_teardown_removes_git_hooks_from_registered_repos(tmp_path, monkeypatch):
    """스펙 §5.2: git post-commit 훅도 teardown 대상이다."""
    from notionmemory.core import paths
    from notionmemory.skills.git import hooks as gc_hooks

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))

    # `git init` 을 쓰지 말 것 — tests/conftest.py 의 autouse `no_real_cli` 픽스처가
    # subprocess.run 을 전역 교체해(detection.subprocess 는 같은 모듈 객체) check=True
    # 여도 조용히 무시된다. hooks.install/is_installed 는 서브프로세스를 쓰지 않으므로
    # 기존 테스트(_bare_repo)와 동일하게 파일 구조만 갖추면 충분하다.
    repo = tmp_path / "repo"
    (repo / ".git" / "hooks").mkdir(parents=True)

    cfg = paths.config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("skills: {}\n", encoding="utf-8")
    gc_hooks.install(repo, str(cfg))
    assert gc_hooks.is_installed(repo)

    teardown.run(["claude"])
    assert not gc_hooks.is_installed(repo)


def test_teardown_never_touches_unowned_skill_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    mine = tmp_path / ".claude" / "skills" / "memory"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("사용자가 직접 만든 것\n", encoding="utf-8")
    teardown.run(["claude"])
    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "사용자가 직접 만든 것\n"


def test_dry_run_changes_nothing(installed):
    before = (installed / ".claude" / "settings.json").read_text(encoding="utf-8")
    lines = teardown.run(["claude"], dry_run=True)
    assert (installed / ".claude" / "settings.json").read_text(encoding="utf-8") == before
    assert (installed / ".claude" / "skills" / "memory" / OWNED_MARKER_FILE).is_file()
    assert any("claude.hooks" in ln for ln in lines)


def test_dry_run_preview_reflects_purge_flags(installed):
    """리뷰 Important #1: 확인 미리보기가 실제로 벌어질 일과 같은 것을 서술해야
    한다 — purge 플래그를 켰을 때 미리보기가 config/PAT 삭제를 언급하지 않으면
    확인 게이트가 거짓말을 하는 것과 같다."""
    cfg = installed / ".config" / "notionmemory" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("skills: {}\n", encoding="utf-8")

    lines = teardown.run(["claude"], dry_run=True, purge_config=True, purge_secrets=True)
    assert any(ln.startswith("will remove") and "config" in ln for ln in lines)
    assert any(ln.startswith("will remove") and "PAT" in ln for ln in lines)
    assert cfg.is_file(), "dry-run 은 실제로 아무것도 지우지 않는다"

    lines_default = teardown.run(["claude"], dry_run=True)
    assert not any(ln.startswith("will remove") and "config" in ln for ln in lines_default)
    assert not any(ln.startswith("will remove") and "PAT" in ln for ln in lines_default)
    assert any(ln.startswith("kept") and "config" in ln for ln in lines_default)
    assert any(ln.startswith("kept") and "PAT" in ln for ln in lines_default)


def test_cli_confirmation_preview_forwards_purge_flags(installed, monkeypatch, capsys):
    """cli.py 의 --yes 없는 확인 흐름도 purge 플래그를 미리보기에 넘겨야 한다."""
    from notionmemory import cli

    cfg = installed / ".config" / "notionmemory" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("skills: {}\n", encoding="utf-8")

    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    rc = cli.main(["teardown", "--claude", "--purge-config", "--purge-secrets"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "config" in out and "will remove" in out
    assert "PAT" in out
    assert cfg.is_file(), "거부했으므로 아무것도 지워지지 않는다"


def test_cli_confirmation_eof_aborts_cleanly(installed, monkeypatch, capsys):
    """비대화형/닫힌 stdin 에서 input() 이 EOFError 를 던져도 트레이스백 없이
    깔끔하게 취소해야 한다(리뷰 Minor)."""
    from notionmemory import cli

    def _raise_eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise_eof)
    rc = cli.main(["teardown", "--claude"])
    assert rc == 1
    assert "취소" in capsys.readouterr().out


def _write_queue_entry(repo: str, commit_hash: str = "deadbeef") -> None:
    from notionmemory.skills.git import queue as gc_queue
    qdir = gc_queue.repo_queue_dir(repo)
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / commit_hash).write_text(
        f"repo {repo}\nbranch main\nts 2024-01-01T00:00:00Z\nsubject test commit\n"
        "files\nbody\n", encoding="utf-8")


def test_dry_run_warns_about_pending_git_queue(tmp_path, monkeypatch):
    """리뷰 Important #3: 상태 디렉터리를 지우면 미전송 git 커밋 큐도 함께
    사라진다 — 지우기 전에 경고해야 한다."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    _write_queue_entry("/some/repo")

    lines = teardown.run(["claude"], dry_run=True)
    assert any("unsent git commit" in ln and "1" in ln for ln in lines)


def test_real_run_warns_about_pending_git_queue_before_wiping(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    _write_queue_entry("/some/repo")

    lines = teardown.run(["claude"])
    assert any("unsent git commit" in ln and "1" in ln for ln in lines)


# ---------------------------------------------------------------------------
# 최종 리뷰 Critical — 마커를 안 남기던 구 scripts/sync_skills.py 가 심은 미러는
# detect()(사이드카 기준)에 안 걸리고 LEGACY_SKILL_NAMES(구 이름)에도 안 걸린다.
# 그래서 업그레이드한 기계에서 teardown 이 그것들에 대해 한 줄도 출력하지 않았다.
# 스펙 §5.3 이 약속한 "손대지 않고 경고만 출력"이 구현돼 있지 않았다.
# ---------------------------------------------------------------------------

def test_teardown_warns_about_same_named_dir_without_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    orphan = tmp_path / ".claude" / "skills" / "memory"
    orphan.mkdir(parents=True)
    (orphan / "SKILL.md").write_text("구버전이 심었거나 사용자가 만든 것\n",
                                     encoding="utf-8")

    lines = teardown.run(["claude"])

    assert orphan.is_dir(), "손대지 않는다"
    assert any(str(orphan) in ln for ln in lines), lines


def test_dry_run_also_warns_about_same_named_dir_without_marker(tmp_path, monkeypatch):
    """미리보기와 실제 실행이 같은 것을 서술해야 한다."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    # "notes" 는 이제 LEGACY_SKILL_NAMES 라 마커 없이도 제거 대상이 된다 —
    # 이 테스트는 현재도 활성 스킬인 이름으로 "동명 무표시 디렉터리" 케이스를 본다.
    orphan = tmp_path / ".claude" / "skills" / "calendar"
    orphan.mkdir(parents=True)

    lines = teardown.run(["claude"], dry_run=True)
    assert any(str(orphan) in ln for ln in lines), lines


def test_teardown_does_not_warn_about_dirs_it_owns(installed):
    """우리가 심은 것은 그냥 제거된다 — 경고로 시끄럽게 하지 않는다."""
    lines = teardown.run(["claude"])
    owned = installed / ".claude" / "skills" / "memory"
    assert not owned.exists()
    assert not any("소유 표시" in ln for ln in lines), lines


# ---------------------------------------------------------------------------
# 최종 리뷰 Important — `shutil.rmtree(..., ignore_errors=True)` 뒤에 무조건
# `제거:` 를 붙였다. 실패가 삼켜지므로 살아남은 디렉터리를 제거했다고 출력한다.
# 상태 디렉터리의 경우 바로 위에서 "미전송 git 커밋 N건이 삭제됩니다" 라고
# 경고까지 해 놓고, 경고한 삭제도 안 일어나고 제거도 안 됐다.
# ---------------------------------------------------------------------------

def test_state_dir_removal_failure_is_reported_not_claimed(tmp_path, monkeypatch):
    from notionmemory.core import paths

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    state = paths.state_dir()
    stuck = state / "stuck"
    stuck.mkdir(parents=True)
    (stuck / "keep").write_text("x", encoding="utf-8")
    stuck.chmod(0o500)                      # 안의 파일을 지울 수 없다 → rmtree 실패
    try:
        lines = teardown.run(["claude"])
        assert state.exists(), "전제: 지워지지 않았다"
        assert not any(ln.startswith("removed: state directory") for ln in lines), lines
        assert any("remove failed" in ln and "state directory" in ln for ln in lines), lines
    finally:
        stuck.chmod(0o700)


def test_symlinked_legacy_skill_dir_reports_failure(tmp_path, monkeypatch):
    """심링크는 `is_dir()` 을 통과하지만 rmtree 가 거부한다 — 삼켜진 실패였다."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.md").write_text("남의 것\n", encoding="utf-8")
    link = tmp_path / ".claude" / "skills" / "notes-capture"
    link.parent.mkdir(parents=True)
    link.symlink_to(elsewhere, target_is_directory=True)

    lines = teardown.run(["claude"])

    assert link.is_symlink(), "전제: 지워지지 않았다"
    assert (elsewhere / "keep.md").is_file(), "링크가 가리키던 곳도 무사하다"
    assert not any(ln.startswith("removed (legacy name)") for ln in lines), lines
    assert any("remove failed" in ln and str(link) in ln for ln in lines), lines


# ---------------------------------------------------------------------------
# 최종 리뷰 Important — `HANDLERS[s.handler]` 를 JSON 파일 값으로 무방비하게
# 인덱싱했다. 새 버전으로 설치한 뒤 예전 체크아웃의 teardown 을 돌리면 KeyError
# 로 터져 **아무것도** 제거되지 않는다. 복구 경로에서 가장 나쁜 실패다.
# ---------------------------------------------------------------------------

def test_teardown_skips_unknown_handler_in_receipt_with_warning(installed):
    from notionmemory.core import paths

    path = paths.receipt_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["artifacts"].append({"id": "claude.quantum", "owner": "_core",
                             "handler": "quantum_entangler", "target": "claude",
                             "path": str(installed / ".claude" / "quantum"),
                             "markers": ["notionmemory"]})
    path.write_text(json.dumps(raw), encoding="utf-8")

    lines = teardown.run(["claude"])          # KeyError 로 터지면 안 된다

    assert any("quantum_entangler" in ln for ln in lines), lines
    # 나머지는 정상적으로 제거된다 — 모르는 항목 하나가 전체를 막지 않는다
    assert not (installed / ".claude" / "skills" / "memory").exists()


def test_teardown_survives_malformed_receipt_entry(installed):
    from notionmemory.core import paths

    path = paths.receipt_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["artifacts"].append({"handler": "skill_mirror"})       # 필수 필드 없음
    path.write_text(json.dumps(raw), encoding="utf-8")

    teardown.run(["claude"])
    assert not (installed / ".claude" / "skills" / "memory").exists()


def test_handler_error_does_not_abort_the_whole_teardown(installed, monkeypatch):
    """핸들러가 OSError 를 던져도 나머지 제거는 계속돼야 한다.

    `SkillMirror.remove` 는 맨 `shutil.rmtree` 라, 권한 문제나 우리 사이드카를 가진
    심링크 하나가 teardown.run() 전체를 트레이스백으로 끝냈다 — 그 뒤 항목(훅·상태
    디렉터리)은 손도 못 댄다. 복구 경로에서 가장 나쁜 실패이고, 영수증에 모르는
    핸들러가 있을 때와 같은 부류다.
    """
    skills = installed / ".claude" / "skills"
    victim = skills / "memory"
    assert victim.is_dir(), "전제: 설치돼 있다"
    skills.chmod(0o500)                     # 자식 디렉터리 엔트리를 지울 수 없다
    try:
        lines = teardown.run(["claude"])
        assert victim.exists(), "전제: 지워지지 않았다"
        assert any("remove failed" in ln and "memory" in ln for ln in lines), lines
        # 핵심: 사고 이후의 항목들이 그대로 처리됐다
        settings = installed / ".claude" / "settings.json"
        assert "notionmemory hook" not in settings.read_text(encoding="utf-8")
        assert not (installed / ".local" / "state" / "notionmemory").exists()
    finally:
        skills.chmod(0o700)
