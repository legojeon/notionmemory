"""install-receipt 에 패키지 버전 각인 + 읽기. 구 receipt(필드 없음)는 None."""
import json

from notionmemory.core import version
from notionmemory.core.install import receipt


def test_write_stamps_package_version(tmp_path, monkeypatch):
    rp = tmp_path / "install-receipt.json"
    monkeypatch.setattr(receipt.paths, "receipt_path", lambda: rp)
    monkeypatch.setattr(version, "package_version", lambda: "1.2.3")
    receipt.write([])
    data = json.loads(rp.read_text(encoding="utf-8"))
    assert data["package_version"] == "1.2.3"
    assert receipt.package_version() == "1.2.3"


def test_package_version_none_for_old_format_receipt(tmp_path, monkeypatch):
    rp = tmp_path / "install-receipt.json"
    rp.write_text(json.dumps({"version": 1, "artifacts": []}), encoding="utf-8")
    monkeypatch.setattr(receipt.paths, "receipt_path", lambda: rp)
    assert receipt.package_version() is None


def test_package_version_none_when_no_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(receipt.paths, "receipt_path", lambda: tmp_path / "nope.json")
    assert receipt.package_version() is None
