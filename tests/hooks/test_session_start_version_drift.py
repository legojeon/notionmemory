"""SessionStart 버전 드리프트 넛지 — 설치 미러가 패키지보다 뒤처졌을 때만, 조용히."""
import io
import json

from notionmemory.core import version
from notionmemory.core.install import receipt
from notionmemory.hooks import session_start


def test_drift_when_versions_differ(monkeypatch):
    monkeypatch.setattr(receipt, "package_version", lambda: "1.2.5")
    monkeypatch.setattr(version, "package_version", lambda: "1.3.0")
    out = session_start.version_drift_injection()
    assert "1.2.5" in out and "1.3.0" in out
    assert "install" in out
    assert out[0] not in "[{"  # JSON 스니핑 회피(평문 접두사)


def test_no_drift_when_versions_match(monkeypatch):
    monkeypatch.setattr(receipt, "package_version", lambda: "1.3.0")
    monkeypatch.setattr(version, "package_version", lambda: "1.3.0")
    assert session_start.version_drift_injection() == ""


def test_no_drift_when_no_receipt(monkeypatch):
    monkeypatch.setattr(receipt, "package_version", lambda: None)
    monkeypatch.setattr(version, "package_version", lambda: "1.3.0")
    assert session_start.version_drift_injection() == ""


def test_drift_reads_a_real_stamped_receipt(tmp_path, monkeypatch):
    """install 이 각인한 실제 receipt 파일을 injection 이 읽어 드리프트를 낸다
    (단위 테스트의 monkeypatch 대신 receipt.write → receipt.package_version 실경로)."""
    monkeypatch.setattr(receipt.paths, "receipt_path", lambda: tmp_path / "install-receipt.json")
    monkeypatch.setattr(version, "package_version", lambda: "1.2.5")  # install 시점
    receipt.write([])
    monkeypatch.setattr(version, "package_version", lambda: "1.3.0")  # 지금 실행 중
    out = session_start.version_drift_injection()
    assert "1.2.5" in out and "1.3.0" in out and "install" in out


def test_main_prints_drift_line(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    for fn in ("resolve_toplevel",):
        monkeypatch.setattr(session_start, fn, lambda cwd: "")
    monkeypatch.setattr(session_start, "memory_injection", lambda project: "")
    monkeypatch.setattr(session_start, "maybe_install_git_hook", lambda top: "")
    monkeypatch.setattr(session_start, "templates_injection", lambda: "")
    monkeypatch.setattr(session_start, "onboarding_injection", lambda: "")
    monkeypatch.setattr(session_start, "library_full_refresh_injection", lambda: "")
    monkeypatch.setattr(session_start, "library_injection", lambda: "")
    monkeypatch.setattr(session_start, "memory_index_injection", lambda: "")
    monkeypatch.setattr(session_start, "git_queue_reminder", lambda top: "")
    monkeypatch.setattr(session_start, "version_drift_injection", lambda: "DRIFT-SENTINEL")
    monkeypatch.setattr("notionmemory.skills.memory.autorun.maybe_spawn", lambda *a, **k: None)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    assert session_start.main() == 0
    assert "DRIFT-SENTINEL" in capsys.readouterr().out
