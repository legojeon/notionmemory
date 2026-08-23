"""package_version() — 런타임 패키지 버전 단일 소스(설치 메타데이터), 미설치 폴백."""
from importlib.metadata import PackageNotFoundError

from notionmemory.core import version as V


def test_returns_installed_metadata_version(monkeypatch):
    monkeypatch.setattr(V, "version", lambda name: "9.9.9")
    assert V.package_version() == "9.9.9"


def test_falls_back_when_not_installed(monkeypatch):
    def boom(name):
        raise PackageNotFoundError(name)
    monkeypatch.setattr(V, "version", boom)
    assert V.package_version() == "0+unknown"
