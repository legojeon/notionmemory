import subprocess
import sys

import pytest

from notionmemory.core import detection, paths


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def set_password(self, service, account, value):
        self.store[(service, account)] = value

    def get_password(self, service, account):
        return self.store.get((service, account))

    def delete_password(self, service, account):
        self.store.pop((service, account), None)


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    return fake


@pytest.fixture(autouse=True)
def no_real_cli(monkeypatch):
    monkeypatch.setattr(detection.shutil, "which", lambda cmd, path=None: None)
    monkeypatch.setattr(
        detection.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], 1, "", ""),
    )


@pytest.fixture(autouse=True)
def clear_detection_cache():
    detection.clear_cache()
    yield
    detection.clear_cache()


@pytest.fixture(autouse=True)
def no_harness_home_override(monkeypatch):
    """`manifest.harness_home()`이 존중하는 CODEX_HOME / CLAUDE_CONFIG_DIR 을 지운다.

    이 변수들이 설정된 셸에서 pytest 를 돌리면(개발기에 실제로 있었다 — Codex 앱이
    CODEX_HOME 을 자기 런타임 홈으로 덮는다) HOME 을 tmp 로 바꿔치기한 테스트가
    tmp 밖 실제 하네스 홈에 스킬·훅을 쓰고 지운다. 오버라이드 동작을 검증하는
    테스트는 이 fixture 이후 자기 값을 직접 setenv 하므로 그쪽이 우선한다."""
    for var in ("CODEX_HOME", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(var, raising=False)


# no_real_state_dir 가 패치하기 전의 진짜 구현 — 파생 규칙(HOME→state_dir) 자체를
# 검증하는 테스트가 이걸 받아 되돌린다(fixture 반환값).
REAL_STATE_DIR = paths.state_dir


@pytest.fixture(autouse=True)
def no_real_state_dir(monkeypatch, tmp_path):
    """`paths.state_dir()`는 기본적으로 실사용 `~/.local/state/notionmemory`를 가리킨다.
    `store.remember`의 write-through(`mem_index.add_memory`)를 타는 테스트가 격리 없이
    돌면 **실사용 memory 색인에 유닛테스트 픽스처가 들어간다** — 실제로 일어났다
    (index.json에 "첫 줄 제목"·"수동 저장" 등 7건, UserPromptSubmit 힌트훅과 recall
    로컬랭킹이 가짜 문서 위에서 돌게 됨). calendar 테스트가 실사용 config를 침범했던
    것과 같은 계열의 격리 누락이라 여기(루트, 전 테스트 autouse)서 막는다 — 앞으로
    어떤 테스트가 write-through·library 색인·install receipt 를 타든 tmp 로 간다.
    프로덕션 코드는 전부 `paths.state_dir()` 모듈 경유 호출이라(직접-이름 임포트 0건)
    함수 패치로 충분하고, 자체 state_dir 를 patch 하는 테스트는 이 fixture 이후
    자기 값으로 다시 덮으므로 그쪽이 우선한다. 반환값 = 패치 전 진짜 구현
    (파생 규칙을 검증하는 테스트가 `monkeypatch.setattr(paths, "state_dir", 반환값)`
    로 되돌린다)."""
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    return REAL_STATE_DIR


@pytest.fixture(autouse=True)
def no_real_repo_config(monkeypatch, tmp_path):
    """`paths.legacy_repo_config()`는 기본적으로 `paths.__file__`을 거슬러 올라가
    이 체크아웃의 실제 `<repo>/config.yaml`(민감정보 포함, git-ignored)을 가리킨다.
    `runner.install()` → `paths.migrate_config()`를 부르는 테스트는 HOME/XDG_CONFIG_HOME을
    바꿔치기해도 이 경로만은 여전히 실제 레포를 가리켜, 실제 시크릿을 임시 디렉터리로
    복사해 흘릴 수 있다. 존재하지 않는 경로로 기본값을 돌려 이 유출을 막는다 — 마이그레이션
    자체를 테스트하는 곳(`tests/core/test_paths.py`)은 이 fixture 이후 자체적으로
    `legacy_repo_config`를 다시 monkeypatch 하므로 그쪽이 우선한다."""
    monkeypatch.setattr(
        paths, "legacy_repo_config",
        lambda: tmp_path / "__no-such-legacy-config-for-tests__" / "config.yaml")
