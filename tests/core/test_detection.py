import subprocess

from notionmemory.core import detection


def _cp(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _pin_shell_path(monkeypatch):
    monkeypatch.setattr(detection, "login_shell_path", lambda: "/bin")


def test_probe_ok_with_version(monkeypatch):
    _pin_shell_path(monkeypatch)
    monkeypatch.setattr(detection.shutil, "which", lambda cmd, path=None: f"/usr/local/bin/{cmd}")
    monkeypatch.setattr(detection.subprocess, "run", lambda *a, **k: _cp(0, "claude 2.1.0\n"))
    p = detection.probe_cli("claude")
    assert p.ok is True
    assert p.version == "claude 2.1.0"
    assert p.path == "/usr/local/bin/claude"


def test_probe_missing_command(monkeypatch):
    _pin_shell_path(monkeypatch)
    p = detection.probe_cli("nope")
    assert p.ok is False
    assert "PATH" in p.error


def test_probe_broken_binary(monkeypatch):
    _pin_shell_path(monkeypatch)
    monkeypatch.setattr(detection.shutil, "which", lambda cmd, path=None: "/bin/x")
    monkeypatch.setattr(detection.subprocess, "run", lambda *a, **k: _cp(1, "", "boom"))
    p = detection.probe_cli("x")
    assert p.ok is False
    assert "run failed" in p.error


def test_probe_timeout(monkeypatch):
    _pin_shell_path(monkeypatch)
    monkeypatch.setattr(detection.shutil, "which", lambda cmd, path=None: "/bin/slow")

    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="slow", timeout=5.0)

    monkeypatch.setattr(detection.subprocess, "run", raise_timeout)
    p = detection.probe_cli("slow")
    assert p.ok is False
    assert "timed out" in p.error


def test_probe_cached_until_refresh(monkeypatch):
    _pin_shell_path(monkeypatch)
    count = {"n": 0}
    monkeypatch.setattr(detection.shutil, "which", lambda cmd, path=None: "/bin/y")

    def fake_run(argv, **kw):
        count["n"] += 1
        return _cp(0, "y 1.0")

    monkeypatch.setattr(detection.subprocess, "run", fake_run)
    detection.probe_cli("y")
    detection.probe_cli("y")
    assert count["n"] == 1
    detection.probe_cli("y", refresh=True)
    assert count["n"] == 2


def test_login_shell_path_falls_back_to_env(monkeypatch):
    monkeypatch.setattr(detection.subprocess, "run", lambda *a, **k: _cp(1, "", ""))
    monkeypatch.setenv("PATH", "/fallback/bin")
    assert detection.login_shell_path() == "/fallback/bin"


def test_login_shell_path_merges_and_caches(monkeypatch):
    count = {"n": 0}

    def fake_run(argv, **kw):
        count["n"] += 1
        return _cp(0, "/login/bin\n")

    monkeypatch.setattr(detection.subprocess, "run", fake_run)
    monkeypatch.setenv("PATH", "/env/bin")
    merged = detection.login_shell_path()
    assert "/login/bin" in merged and "/env/bin" in merged
    detection.login_shell_path()
    assert count["n"] == 1


def test_run_cli_caches_by_key(monkeypatch):
    count = {"n": 0}

    def fake_run(argv, **kw):
        count["n"] += 1
        return _cp(0, "ok")

    monkeypatch.setattr(detection.subprocess, "run", fake_run)
    assert detection.run_cli(["gh", "auth", "status"], cache_key="gh-auth") == (0, "ok")
    detection.run_cli(["gh", "auth", "status"], cache_key="gh-auth")
    assert count["n"] == 1
    detection.run_cli(["gh", "auth", "status"], cache_key="gh-auth", refresh=True)
    assert count["n"] == 2
