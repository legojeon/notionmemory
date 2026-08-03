import subprocess

import pytest

from notionmemory.core import agent_runtime, detection
from notionmemory.core.agent_runtime import AgentRuntime, AgentRuntimeError, build_runtime
from notionmemory.core.config import Config


def _cp(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_generate_builds_claude_command_and_stdin(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["input"] = argv, kw.get("input")
        return _cp(0, "결과 마크다운\n")

    monkeypatch.setattr(agent_runtime.subprocess, "run", fake_run)
    rt = AgentRuntime("claude", "/bin/claude")
    out = rt.generate("시스템 지시", "사용자 요청")
    assert out == "결과 마크다운"
    assert seen["argv"] == ["/bin/claude", "-p", "--output-format", "text"]
    assert "시스템 지시" in seen["input"] and "사용자 요청" in seen["input"]
    assert seen["input"].index("시스템 지시") < seen["input"].index("사용자 요청")


def test_generate_appends_image_paths_to_prompt(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["input"] = kw.get("input")
        return _cp(0, "ok")

    monkeypatch.setattr(agent_runtime.subprocess, "run", fake_run)
    AgentRuntime("claude", "/bin/claude").generate("s", "u", ["/tmp/p1.png", "/tmp/p2.png"])
    assert "/tmp/p1.png" in seen["input"] and "/tmp/p2.png" in seen["input"]


def test_generate_codex_writes_and_reads_last_message(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["input"] = argv, kw.get("input")
        idx = argv.index("--output-last-message")
        with open(argv[idx + 1], "w", encoding="utf-8") as f:
            f.write("전사 결과\n")
        return _cp(0, "세션 로그 잡음 — 무시돼야 함")  # stdout 은 쓰지 않는다

    monkeypatch.setattr(agent_runtime.subprocess, "run", fake_run)
    out = AgentRuntime("codex", "/bin/codex").generate("s", "u")
    assert out == "전사 결과"
    assert seen["argv"][:2] == ["/bin/codex", "exec"]
    assert "--skip-git-repo-check" in seen["argv"]
    assert seen["input"] and "s" in seen["input"] and "u" in seen["input"]


def test_generate_codex_empty_message_retries_then_raises(monkeypatch):
    count = {"n": 0}

    def fake_run(argv, **kw):
        count["n"] += 1
        return _cp(0, "")  # output 파일을 비운 채 둠 → 빈 결과

    monkeypatch.setattr(agent_runtime.subprocess, "run", fake_run)
    with pytest.raises(AgentRuntimeError):
        AgentRuntime("codex", "/bin/codex").generate("s", "u")
    assert count["n"] == 2


def test_generate_codex_nonzero_exit_raises(monkeypatch):
    def fake_run(argv, **kw):
        return _cp(1, "", "codex 폭발")

    monkeypatch.setattr(agent_runtime.subprocess, "run", fake_run)
    with pytest.raises(AgentRuntimeError):
        AgentRuntime("codex", "/bin/codex").generate("s", "u")


def test_generate_retries_once_then_raises(monkeypatch):
    count = {"n": 0}

    def fake_run(argv, **kw):
        count["n"] += 1
        return _cp(1, "", "boom")

    monkeypatch.setattr(agent_runtime.subprocess, "run", fake_run)
    with pytest.raises(AgentRuntimeError):
        AgentRuntime("claude", "/bin/claude").generate("s", "u")
    assert count["n"] == 2


def test_generate_empty_output_raises_after_retry(monkeypatch):
    count = {"n": 0}

    def fake_run(argv, **kw):
        count["n"] += 1
        return _cp(0, "   \n")

    monkeypatch.setattr(agent_runtime.subprocess, "run", fake_run)
    with pytest.raises(AgentRuntimeError):
        AgentRuntime("claude", "/bin/claude").generate("s", "u")
    assert count["n"] == 2


def test_generate_timeout_raises(monkeypatch):
    def fake_run(argv, **kw):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(agent_runtime.subprocess, "run", fake_run)
    with pytest.raises(AgentRuntimeError):
        AgentRuntime("claude", "/bin/claude", timeout=1).generate("s", "u")


def test_build_runtime_prefers_config_backend(monkeypatch):
    monkeypatch.setattr(detection, "probe_cli",
                        lambda cmd, refresh=False: detection.Probe(ok=True, path=f"/bin/{cmd}", version="v"))
    rt = build_runtime(Config({"integrations": {"agent": {"backend": "codex"}}}))
    assert rt.backend == "codex" and rt.binary == "/bin/codex"


def test_build_runtime_detects_claude_first(monkeypatch):
    monkeypatch.setattr(detection, "probe_cli",
                        lambda cmd, refresh=False: detection.Probe(ok=(cmd == "claude"), path="/bin/claude", version="v")
                        if cmd == "claude" else detection.Probe(ok=False, error="없음"))
    assert build_runtime(Config({})).backend == "claude"


def test_build_runtime_raises_when_undetected():
    with pytest.raises(AgentRuntimeError):
        build_runtime(Config({}))  # 전역 안전망: which → None


def test_model_flag_appended_when_configured_claude(monkeypatch):
    seen = {}
    def fake_run(argv, **kw):
        seen["argv"] = argv
        return _cp(stdout="ok")
    monkeypatch.setattr(agent_runtime.subprocess, "run", fake_run)
    rt = agent_runtime.AgentRuntime("claude", "/bin/claude", model="claude-sonnet-4-20250514")
    rt.generate("s", "u")
    assert seen["argv"] == ["/bin/claude", "-p", "--output-format", "text",
                            "--model", "claude-sonnet-4-20250514"]


def test_model_flag_appended_when_configured_codex(monkeypatch):
    seen = {}
    def fake_run(argv, **kw):
        seen["argv"] = argv
        idx = argv.index("--output-last-message")
        with open(argv[idx + 1], "w", encoding="utf-8") as f:
            f.write("ok")
        return _cp()
    monkeypatch.setattr(agent_runtime.subprocess, "run", fake_run)
    rt = agent_runtime.AgentRuntime("codex", "/bin/codex", model="gpt-5.5-mini")
    rt.generate("s", "u")
    assert seen["argv"][:4] == ["/bin/codex", "exec", "--skip-git-repo-check", "-m"]
    assert seen["argv"][4] == "gpt-5.5-mini"


def test_build_runtime_reads_agent_model_from_config(monkeypatch):
    from notionmemory.core.config import Config
    monkeypatch.setattr(agent_runtime.detection, "probe_cli",
                        lambda c: type("P", (), {"ok": c == "claude", "path": "/bin/claude"})())
    cfg = Config({"integrations": {"agent": {"model": "claude-sonnet-4-20250514"}}})
    rt = agent_runtime.build_runtime(cfg)
    assert rt.model == "claude-sonnet-4-20250514"
    rt2 = agent_runtime.build_runtime(Config({}))
    assert rt2.model == "sonnet"  # 미설정 → claude 기본 별칭(별도 테스트가 상세 검증)


def test_build_runtime_defaults_claude_to_sonnet_when_unset(monkeypatch):
    """배치 작업(판정+요약)엔 상위 티어가 불필요 — agentmemory 와 같은 정책으로 claude
    백엔드는 sonnet 을 기본 핀. codex 는 모델명 변동이 잦아 CLI 기본에 위임(빈 값)."""
    from notionmemory.core.config import Config
    monkeypatch.setattr(agent_runtime.detection, "probe_cli",
                        lambda c: type("P", (), {"ok": c == "claude", "path": "/bin/claude"})())
    assert agent_runtime.build_runtime(Config({})).model == "sonnet"
    monkeypatch.setattr(agent_runtime.detection, "probe_cli",
                        lambda c: type("P", (), {"ok": c == "codex", "path": "/bin/codex"})())
    assert agent_runtime.build_runtime(Config({})).model == ""


def test_build_runtime_explicit_model_overrides_backend_default(monkeypatch):
    from notionmemory.core.config import Config
    monkeypatch.setattr(agent_runtime.detection, "probe_cli",
                        lambda c: type("P", (), {"ok": c == "claude", "path": "/bin/claude"})())
    cfg = Config({"integrations": {"agent": {"model": "opus"}}})
    assert agent_runtime.build_runtime(cfg).model == "opus"


def test_build_runtime_defaults_claude_to_sonnet_alias(monkeypatch):
    """모델 미설정 시 claude 는 sonnet 별칭이 기본 — 판정+요약 급 배치 작업에 상위
    티어(CLI 기본이 opus 인 사용자)를 쓰는 낭비 방지. 별칭이라 모델 세대가 바뀌어도
    안 썩는다. codex 는 안정적 별칭이 없어 CLI 기본 유지(하드코딩 ID 는 개명 시
    백그라운드 전체가 조용히 깨진다)."""
    from notionmemory.core.config import Config
    monkeypatch.setattr(agent_runtime.detection, "probe_cli",
                        lambda c: type("P", (), {"ok": c == "claude", "path": "/bin/claude"})())
    assert agent_runtime.build_runtime(Config({})).model == "sonnet"


def test_build_runtime_codex_default_model_stays_empty(monkeypatch):
    from notionmemory.core.config import Config
    monkeypatch.setattr(agent_runtime.detection, "probe_cli",
                        lambda c: type("P", (), {"ok": c == "codex", "path": "/bin/codex"})())
    assert agent_runtime.build_runtime(Config({})).model == ""


def test_build_runtime_explicit_model_overrides_default(monkeypatch):
    from notionmemory.core.config import Config
    monkeypatch.setattr(agent_runtime.detection, "probe_cli",
                        lambda c: type("P", (), {"ok": c == "claude", "path": "/bin/claude"})())
    cfg = Config({"integrations": {"agent": {"model": "opus"}}})
    assert agent_runtime.build_runtime(cfg).model == "opus"
