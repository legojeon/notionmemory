"""설치 아티팩트 목록 — 무엇을 어디에 심는지의 단일 진실."""
from __future__ import annotations

import os
from pathlib import Path

from notionmemory.core import paths, skill_assets
from notionmemory.core.install.spec import ArtifactSpec

# 훅 소유권 마커. 두 번째는 CLI 서브커맨드화 이전(scripts/memory_hooks/*.py) 설치가
# 남긴 구 마커 — 이것을 인식해야 구버전 설치가 고아가 되지 않는다.
HOOK_MARKERS: tuple[str, ...] = ("notionmemory hook", "memory_hooks")

# 시스템에 아무것도 심지 않는 스킬 — 여기 넣는 것은 "등록을 잊었다"가 아니라
# "설치물이 없음을 확인했다"는 명시적 선언이다. tests/test_artifact_contract.py 참조.
OWNS_NOTHING: frozenset[str] = frozenset()

# 하네스 홈을 옮기는 환경변수. 두 하네스 모두 공식 지원한다.
HOME_ENV = {"claude": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME"}


def harness_home(target: str) -> Path:
    """하네스가 실제로 읽는 홈 디렉터리 — 환경변수 오버라이드를 존중한다.

    실측(2026-07-22): CODEX_HOME 이 다른 곳을 가리키는 셸에서 install 을 돌리자
    훅은 ~/.codex 에 심겼고 Codex 의 hooks/list 는 그것을 전혀 보지 못했다. 훅이
    조용히 안 도는 실패 모드라 사용자가 원인을 찾을 방법이 없다. 심는 곳과 하네스가
    읽는 곳은 같은 함수로 결정돼야 한다 — teardown 스윕도 이 함수를 쓴다(안 그러면
    오버라이드 환경에서 심은 것이 영원히 안 지워진다).
    """
    override = os.environ.get(HOME_ENV.get(target, ""))
    if override:
        return Path(override).expanduser()
    # HOME 은 paths 에게 묻는다 — 예전에는 `paths.state_dir().parents[2]` 로 상태
    # 디렉터리에서 거꾸로 걸어 올라갔는데, state_dir() 이 XDG_STATE_HOME 을
    # 존중하게 되는 날 harness_home() 이 조용히 엉뚱한 루트에 심기 시작한다.
    return paths.home() / f".{target}"


def skills_root(target: str) -> Path:
    return harness_home(target) / "skills"


def hook_file(target: str) -> Path:
    return harness_home(target) / ("hooks.json" if target == "codex" else "settings.json")


def hook_file_is_dedicated(target: str) -> bool:
    """이 훅 파일은 우리가 없으면 존재하지 않는가.

    Codex 의 hooks.json 은 훅 전용이라 우리 블록을 빼면 파일째 지워야 한다 — 안 그러면
    teardown 뒤 `{"hooks": {}}` 껍데기가 남아 계약을 어긴다(실환경 검증에서 발견).
    Claude 의 settings.json 은 하네스·사용자 소유라 비어도 남긴다.
    """
    return target == "codex"


def HOOK_EVENTS(cli_path: str, harness: str = "claude") -> dict:
    """`harness` 는 hook 명령에 `--harness <값>` 으로 그대로 박힌다 — Codex 는
    Stop/PreCompact 에서 평문 stdout 을 실패 처리하므로(실측) 훅이 자신을 부른
    하네스를 알아야 한다. Claude 는 기본값(claude)이라 플래그를 아예 안 붙인다 —
    지금까지의 명령 문자열을 그대로 유지해 기존 신뢰/영수증에 영향이 없다."""
    def entry(hook_name: str) -> dict:
        cmd = f"{cli_path} hook {hook_name}"
        if harness != "claude":
            cmd += f" --harness {harness}"
        return {"hooks": [{"type": "command", "command": cmd, "timeout": 20}]}
    # Stop 은 등록하지 않는다 — 매 턴 발화하는데 그 시점엔 에이전트가 이미 턴을 끝냈고
    # Stop 에는 컨텍스트 주입 채널이 없다(Codex 스키마상 hookSpecificOutput 이 없다).
    # 남는 systemMessage 는 화면 전용이라 Codex 가 `warning:` 으로 매 턴 띄웠고, 정작
    # 실행 주체인 에이전트에게는 닿지 않았다. 근거 있는 큐 안내는 SessionStart 로 옮겼다.
    return {"SessionStart": [entry("session-start")],
            "PreCompact": [entry("save-reminder")]}


def codex_trust_spec() -> ArtifactSpec:
    """`~/.codex/config.toml` 의 우리 `[hooks.state.*]` 블록.

    payload 는 비어 있다 — 실제 entries 는 hooks.json 을 쓴 뒤 `codex hooks/list`
    로 실측해야 정해지므로 install 이 이 명세를 복제(dataclasses.replace)해서
    채운다. 그래도 명세 자체는 여기 하나뿐이어야 한다: 예전에는 runner 와
    teardown._sweep 이 각자 조립해 같은 지식(경로·마커·핸들러)이 두 곳에
    복제돼 있었고, 그건 CLAUDE.md 규칙 1 위반이자 갈라지기를 기다리는 상태다.
    """
    hooks_path = hook_file("codex")
    return ArtifactSpec(
        id="codex.trust", owner="_core", handler="codex_trust", target="codex",
        path=hooks_path.parent / "config.toml", payload={"entries": []},
        markers=(str(hooks_path),))


def build(targets: list[str], cli_path: str) -> list[ArtifactSpec]:
    specs: list[ArtifactSpec] = []
    roots = {t: skills_root(t) for t in targets}
    hook_files = {t: hook_file(t) for t in targets}

    for target in targets:
        for name in skill_assets.skill_names():
            specs.append(ArtifactSpec(
                id=f"{target}.skills.{name}", owner=name, handler="skill_mirror",
                target=target, path=roots[target] / name,
                payload={"source": str(skill_assets.skills_root() / name)},
                markers=(name,)))
        harness = target if target in ("claude", "codex") else "claude"
        specs.append(ArtifactSpec(
            id=f"{target}.hooks", owner="_core", handler="json_hook_block",
            target=target, path=hook_files[target],
            payload={"events": HOOK_EVENTS(cli_path, harness=harness)},
            markers=HOOK_MARKERS))

    # 신뢰 등록은 hooks.json 을 쓴 뒤에만 의미가 있으므로 훅 명세들 다음에 온다.
    if "codex" in targets:
        specs.append(codex_trust_spec())

    # git 은 하네스와 무관하게 리포별 post-commit 훅을 소유한다 — target="shared" 로 한 번만.
    # notionmemory install 이 심지는 않지만(GitHooks.install 은 no-op), 매니페스트에
    # 있어야 teardown 이 찾는다.
    specs.append(ArtifactSpec(
        id="shared.git_hooks", owner="git", handler="git_hooks", target="shared",
        path=paths.config_path(), payload={}, markers=("notionmemory git",)))
    return specs
