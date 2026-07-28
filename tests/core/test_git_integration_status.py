"""GitIntegration.status() 는 gh 가 아니라 git + 훅 설치 여부로 판정한다.

관찰(2026-07-21): 판정이 `gh` 설치 + `gh auth status` 에만 묶여 있어서, gh 없는
환경에서 **정상 동작하는 연동**을 대시보드가 "미설치"로 빨갛게 표시했다. git 캡처는
로컬 post-commit 훅 + `git` CLI 만으로 완전히 동작하고, gh 는 커밋 Link URL 보강용
폴백일 뿐이다(실패하면 `git remote` 파싱으로 대체 — flusher.py).
"""
import pytest

from notionmemory.core import detection, integrations
from notionmemory.core.config import Config
from notionmemory.skills.git import hooks as gc_hooks


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("{}\n", encoding="utf-8")
    return Config.load(str(path))


@pytest.fixture
def cli(monkeypatch):
    """어떤 CLI 가 있다고 볼지 테스트마다 지정한다."""
    present: dict[str, str] = {}

    def fake_probe(cmd, *, refresh=False):
        if cmd in present:
            return detection.Probe(True, path=f"/usr/bin/{cmd}", version=present[cmd])
        return detection.Probe(False, error="not found")

    monkeypatch.setattr(integrations.detection, "probe_cli", fake_probe)
    return present


@pytest.fixture
def repos(monkeypatch):
    """훅 레지스트리 응답을 지정한다(gc_hooks.status 와 같은 형태)."""
    state: list[dict] = []
    monkeypatch.setattr(integrations.gc_hooks, "status", lambda _path: state)
    return state


def test_connected_without_gh_when_a_repo_has_the_hook(cfg, cli, repos):
    """핵심 회귀: gh 가 없어도 연결됨이어야 한다."""
    cli["git"] = "git version 2.43.0"
    repos.append({"repo": "/r/one", "exists": True, "installed": True})

    st = integrations.GitIntegration().status(cfg)

    assert st.connected is True, st.detail
    assert "gh" not in st.detail or "선택" in st.detail


def test_not_connected_when_git_cli_is_missing(cfg, cli, repos):
    repos.append({"repo": "/r/one", "exists": True, "installed": True})

    st = integrations.GitIntegration().status(cfg)

    assert st.connected is False
    assert "git" in st.detail


def test_not_connected_when_no_repo_has_the_hook(cfg, cli, repos):
    """git 은 있는데 어디에도 안 걸려 있으면 캡처가 일어나지 않는다 — 할 일을 알린다."""
    cli["git"] = "git version 2.43.0"
    repos.append({"repo": "/r/one", "exists": True, "installed": False})

    st = integrations.GitIntegration().status(cfg)

    assert st.connected is False
    assert "notionmemory git install" in st.detail


def test_gh_is_reported_as_optional_not_as_failure(cfg, cli, repos):
    """gh 유무는 detail 에만 나타나고 connected 를 바꾸지 않는다."""
    cli["git"] = "git version 2.43.0"
    repos.append({"repo": "/r/one", "exists": True, "installed": True})
    without = integrations.GitIntegration().status(cfg)

    cli["gh"] = "gh version 2.62.0"
    with_gh = integrations.GitIntegration().status(cfg)

    assert without.connected is with_gh.connected is True
    assert without.detail != with_gh.detail


def test_name_no_longer_claims_to_be_github(cfg):
    """이름이 'GitHub (gh CLI)' 면 사용자는 gh 를 필수로 읽는다."""
    assert "gh CLI" not in integrations.GitIntegration().name


def test_status_survives_an_unreadable_registry(cfg, cli, monkeypatch):
    """설정이 깨져 있어도 대시보드 전체가 500 으로 죽으면 안 된다."""
    cli["git"] = "git version 2.43.0"

    def boom(_path):
        raise OSError("config gone")

    monkeypatch.setattr(integrations.gc_hooks, "status", boom)

    st = integrations.GitIntegration().status(cfg)

    assert st.connected is False
    assert st.detail


def test_real_registry_is_wired_up(tmp_path, cli):
    """monkeypatch 없이 실제 gc_hooks.status 경로가 도는지 — 배선 확인."""
    repo = tmp_path / "repo"
    (repo / ".git" / "hooks").mkdir(parents=True)
    path = tmp_path / "config.yaml"
    path.write_text("{}\n", encoding="utf-8")
    gc_hooks.install(repo, str(path))
    cli["git"] = "git version 2.43.0"

    st = integrations.GitIntegration().status(Config.load(str(path)))

    assert st.connected is True, st.detail
