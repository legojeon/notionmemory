"""훅이 CLI 서브커맨드로 동작하고 레포 경로에 의존하지 않는다."""
import io
import json
import subprocess
import sys

import pytest

from notionmemory.hooks import common, save_reminder, session_start


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    """실기 HOME 상태(설치된 templates 프로필·git 큐·library 색인)로부터 격리한다.

    이게 없으면 SessionStart 의 `out == ""` 침묵 단언이 이 머신의 실제 주입에 오염될 수
    있다(Task 5 리뷰가 지목한 pre-existing 위생 결함). save_reminder 테스트는
    payload cwd 로 config 를 찾으므로 HOME 이동에 영향받지 않는다."""
    monkeypatch.setenv("HOME", str(tmp_path))


def _run_main(mod, monkeypatch, payload: dict, capsys, **main_kwargs):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = mod.main(**main_kwargs)
    return code, capsys.readouterr().out


def test_session_start_never_raises_on_garbage_stdin(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
    assert session_start.main() == 0
    assert capsys.readouterr().out == ""


def test_save_reminder_prints_reminder_when_auto(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills:\n  memory:\n    capture_mode: auto\n", encoding="utf-8")
    monkeypatch.setattr(common.paths, "config_path", lambda: cfg)
    code, out = _run_main(save_reminder, monkeypatch, {"cwd": str(tmp_path)}, capsys)
    assert code == 0
    assert "remember --auto" in out
    # 훅 stdout 은 '[' / '{' 로 시작하면 안 된다 (양쪽 하네스가 JSON 으로 스니핑)
    assert not out.lstrip().startswith(("[", "{"))


def test_save_reminder_silent_when_manual(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills:\n  memory:\n    capture_mode: manual\n", encoding="utf-8")
    monkeypatch.setattr(common.paths, "config_path", lambda: cfg)
    code, out = _run_main(save_reminder, monkeypatch, {"cwd": str(tmp_path)}, capsys)
    assert code == 0
    assert out.strip() == ""


# ── save_reminder — harness=codex: Stop/PreCompact 는 평문이 아니라 JSON ────
# 실기(2026-07-21): Codex 는 이 두 이벤트에서 평문 stdout 을 실패 처리한다
# (`hook: Stop Failed`) — {"systemMessage": "..."} 를 찍으면 성공한다.

def test_save_reminder_emits_system_message_json_for_codex_harness(
        tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills:\n  memory:\n    capture_mode: auto\n", encoding="utf-8")
    monkeypatch.setattr(common.paths, "config_path", lambda: cfg)
    code, out = _run_main(save_reminder, monkeypatch, {"cwd": str(tmp_path)}, capsys,
                          harness="codex")
    assert code == 0
    payload = json.loads(out.strip())          # 유효한 JSON 이어야 한다 — 파싱 실패 = 회귀
    assert "remember --auto" in payload["systemMessage"]


def test_save_reminder_codex_harness_silent_when_manual(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills:\n  memory:\n    capture_mode: manual\n", encoding="utf-8")
    monkeypatch.setattr(common.paths, "config_path", lambda: cfg)
    code, out = _run_main(save_reminder, monkeypatch, {"cwd": str(tmp_path)}, capsys,
                          harness="codex")
    assert code == 0
    assert out.strip() == ""


def test_save_reminder_claude_harness_output_is_byte_identical_to_default(
        tmp_path, monkeypatch, capsys):
    """harness="claude" 를 명시해도 기본값(무플래그)과 출력이 한 글자도 다르지
    않아야 한다 — Claude Code 쪽 동작은 이 태스크로 바뀌면 안 된다."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills:\n  memory:\n    capture_mode: auto\n", encoding="utf-8")
    monkeypatch.setattr(common.paths, "config_path", lambda: cfg)
    _, default_out = _run_main(save_reminder, monkeypatch, {"cwd": str(tmp_path)}, capsys)
    _, explicit_out = _run_main(save_reminder, monkeypatch, {"cwd": str(tmp_path)}, capsys,
                                harness="claude")
    assert default_out == explicit_out
    assert not default_out.lstrip().startswith(("[", "{"))


def test_hook_subcommand_is_wired():
    """CLI 표면에 hook 서브커맨드가 있고 알 수 없는 이름은 거부한다."""
    import pytest

    from notionmemory.cli import main
    # argparse 의 choices 위반은 SystemExit(2) 로 나온다
    with pytest.raises(SystemExit) as excinfo:
        main(["hook", "nonexistent-hook"])
    assert excinfo.value.code == 2


def test_hook_module_has_no_repo_venv_path():
    """훅 모듈 어디에도 체크아웃/venv 절대경로가 없어야 한다."""
    for mod in (session_start, save_reminder):
        src = __import__("pathlib").Path(mod.__file__).read_text(encoding="utf-8")
        assert "venv/bin" not in src
        assert "/Users/" not in src


def test_hook_cli_forwards_harness_flag_to_save_reminder(tmp_path, monkeypatch, capsys):
    """CLI 표면의 --harness 가 실제로 save_reminder.main 까지 전달된다."""
    from notionmemory.cli import main as cli_main

    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills:\n  memory:\n    capture_mode: auto\n", encoding="utf-8")
    monkeypatch.setattr(common.paths, "config_path", lambda: cfg)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert cli_main(["hook", "save-reminder", "--harness", "codex"]) == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert "systemMessage" in payload


def test_hook_cli_harness_defaults_to_claude(tmp_path, monkeypatch, capsys):
    """--harness 를 안 주면(기본값) 지금까지의 평문 출력 그대로다."""
    from notionmemory.cli import main as cli_main

    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills:\n  memory:\n    capture_mode: auto\n", encoding="utf-8")
    monkeypatch.setattr(common.paths, "config_path", lambda: cfg)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert cli_main(["hook", "save-reminder"]) == 0
    out = capsys.readouterr().out
    assert "remember --auto" in out
    assert not out.lstrip().startswith(("[", "{"))


# ── session_start — memory 섹션(브리프+고Strength+pending nudge) ────────
# 옛 recall 서브프로세스(resolve_cli/PATH 폴백 포함) 회귀 가드는 그 메커니즘 자체가
# Second Brain v2 Phase 2a Task 5 로 대체되며 함께 은퇴했다 — 새 동작의 전담 테스트는
# tests/hooks/test_session_start_brief.py (브리프/고Strength/pending nudge/침묵/
# Notion 에러 흡수). "세션 시작을 막지 않는다" 예외 흡수 계약 자체는 그 파일의
# test_notion_error_is_silent_no_raise 가 이어받는다.

def test_session_start_cli_guidance_constant_stays_bare_name():
    """사용자 안내 문구에 넣는 CLI 이름은 절대경로로 바뀌면 안 된다 — 그대로
    따라 칠 수 있어야 한다."""
    assert session_start.CLI == "notionmemory"


# ── session_start — 프로젝트 이름 해석 ──────────────────────────────

def test_resolve_project_prefers_git_toplevel(monkeypatch):
    monkeypatch.setattr(
        session_start.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 0, stdout="/Users/x/myrepo\n", stderr=""))
    assert session_start.resolve_project("/Users/x/myrepo/sub") == "myrepo"


def test_resolve_project_falls_back_to_cwd_basename(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("no git")
    monkeypatch.setattr(session_start.subprocess, "run", boom)
    assert session_start.resolve_project(str(tmp_path)) == tmp_path.name


# ── save_reminder — config 견고성 ───────────────────────────────────

def _reminder_with_cfg(monkeypatch, tmp_path, body):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(body, encoding="utf-8")
    monkeypatch.setattr(common.paths, "config_path", lambda: cfg)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    return save_reminder


def test_reminder_default_is_auto(monkeypatch, tmp_path, capsys):
    # skills.memory 키 자체가 없어도 기본값은 auto 다.
    sr = _reminder_with_cfg(monkeypatch, tmp_path, "skills: {}\n")
    assert sr.main() == 0
    assert "remember --auto" in capsys.readouterr().out


def test_reminder_swallows_config_errors(monkeypatch, tmp_path, capsys):
    # config 파일 자체가 없는 실제 최초 실행 상태 → 조용히 auto 로 폴백.
    missing = tmp_path / "없는폴더" / "config.yaml"
    monkeypatch.setattr(common.paths, "config_path", lambda: missing)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert save_reminder.main() == 0
    assert "remember --auto" in capsys.readouterr().out


def test_reminder_swallows_invalid_yaml(monkeypatch, tmp_path, capsys):
    sr = _reminder_with_cfg(monkeypatch, tmp_path, "skills: [unclosed\n")
    assert sr.main() == 0  # YAML 파싱 실패 → 기본 auto → 리마인더는 출력
    assert "remember --auto" in capsys.readouterr().out


def test_reminder_survives_malformed_stdin(monkeypatch, tmp_path, capsys):
    # stdin JSON 파싱이 깨져도(예: hook 호출부 버그) 리마인더 자체는 죽지
    # 않아야 한다 — stdin 내용과 무관하게 항상 출력되는 동작.
    cfg = tmp_path / "config.yaml"
    cfg.write_text("skills:\n  memory:\n    capture_mode: auto\n", encoding="utf-8")
    monkeypatch.setattr(common.paths, "config_path", lambda: cfg)
    monkeypatch.setattr(sys, "stdin", io.StringIO("이거 json 아님 {{{"))
    assert save_reminder.main() == 0
    assert "remember --auto" in capsys.readouterr().out
