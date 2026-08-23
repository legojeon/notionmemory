"""`notionmemory status` 상단 버전 줄 — 최신/드리프트/미각인 3분기."""
from notionmemory import cli
from notionmemory.core import version
from notionmemory.core.install import receipt


def test_version_line_up_to_date(monkeypatch):
    monkeypatch.setattr(version, "package_version", lambda: "1.3.0")
    monkeypatch.setattr(receipt, "package_version", lambda: "1.3.0")
    line = cli._version_status_line("en")
    assert "1.3.0" in line
    assert "install" not in line


def test_version_line_drift_points_at_install(monkeypatch):
    monkeypatch.setattr(version, "package_version", lambda: "1.3.0")
    monkeypatch.setattr(receipt, "package_version", lambda: "1.2.5")
    line = cli._version_status_line("en")
    assert "1.3.0" in line and "1.2.5" in line
    assert "install" in line


def test_version_line_no_receipt_is_bare(monkeypatch):
    monkeypatch.setattr(version, "package_version", lambda: "1.3.0")
    monkeypatch.setattr(receipt, "package_version", lambda: None)
    line = cli._version_status_line("en")
    assert "1.3.0" in line
    assert "install" not in line
