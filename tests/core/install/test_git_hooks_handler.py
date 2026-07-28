"""GitHooks — 레지스트리에 등록된 리포의 post-commit 훅을 찾아 제거한다."""
from notionmemory.core.install.handlers import GitHooks
from notionmemory.core.install.spec import ArtifactSpec
from notionmemory.skills.git import hooks as gc_hooks


def _spec(config_path) -> ArtifactSpec:
    return ArtifactSpec(id="shared.git_hooks", owner="git", handler="git_hooks",
                        target="shared", path=config_path, payload={},
                        markers=("notionmemory git",))


def test_detect_and_remove_registered_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    # 실제 `git init` 을 쓰지 않는다: tests/conftest.py 의 autouse no_real_cli 픽스처가
    # detection.subprocess.run 을 패치하는데, detection.py 가 `import subprocess` 로
    # 가져오므로 이는 모듈 전역 subprocess.run 을 프로세스 전체에서 가짜로 바꾼다
    # (check=True 여도 예외 없이 가짜 CompletedProcess 를 반환) — 그래서 여기서
    # subprocess.run(["git", "init", ...]) 을 호출하면 조용히 아무 일도 안 일어난다.
    # gc_hooks 는 실제 git 상태를 쓰지 않고 .git/hooks/post-commit 파일만 다루므로
    # 디렉터리만 만들어주면 충분하다.
    (repo / ".git" / "hooks").mkdir(parents=True)
    config = tmp_path / "config.yaml"
    config.write_text("skills: {}\n", encoding="utf-8")

    gc_hooks.install(repo, str(config))
    spec = _spec(config)
    assert GitHooks().detect(spec) is True
    assert GitHooks().remove(spec) is True
    assert not gc_hooks.is_installed(repo)
    assert GitHooks().detect(spec) is False


def test_install_is_noop(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("skills: {}\n", encoding="utf-8")
    assert GitHooks().install(_spec(config)) is False


def test_detect_false_when_registry_empty(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("skills: {}\n", encoding="utf-8")
    assert GitHooks().detect(_spec(config)) is False
