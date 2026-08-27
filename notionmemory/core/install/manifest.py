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


def _home_env(target: str) -> str:
    # 지연 임포트: notionmemory.providers 의 provider 모듈들이 이 모듈(manifest)을
    # 되임포트하며 codex_trust_spec 등을 module-level 에서 참조한다(providers/codex.py).
    # manifest 가 먼저 임포트되는 경로(예: 이 테스트 파일이 `from ... import manifest`
    # 로 시작)에서 최상단에 `from notionmemory import providers` 를 두면, providers 패키지가
    # codex_trust_spec 정의 이전에 부분 실행 중인 manifest 모듈을 참조해 AttributeError 로
    # 깨진다. 함수 안에서 임포트해 항상 manifest 가 완전히 로드된 뒤 providers 를 당긴다.
    from notionmemory import providers
    return providers.get(target).config_home_env if target in providers.names() else ""


def harness_home(target: str) -> Path:
    """하네스가 실제로 읽는 홈 디렉터리 — 환경변수 오버라이드를 존중한다.

    실측(2026-07-22): CODEX_HOME 이 다른 곳을 가리키는 셸에서 install 을 돌리자
    훅은 ~/.codex 에 심겼고 Codex 의 hooks/list 는 그것을 전혀 보지 못했다. 훅이
    조용히 안 도는 실패 모드라 사용자가 원인을 찾을 방법이 없다. 심는 곳과 하네스가
    읽는 곳은 같은 함수로 결정돼야 한다 — teardown 스윕도 이 함수를 쓴다(안 그러면
    오버라이드 환경에서 심은 것이 영원히 안 지워진다).
    """
    from notionmemory import providers

    override = os.environ.get(_home_env(target))
    if override:
        return Path(override).expanduser()
    # HOME 은 paths 에게 묻는다 — 예전에는 `paths.state_dir().parents[2]` 로 상태
    # 디렉터리에서 거꾸로 걸어 올라갔는데, state_dir() 이 XDG_STATE_HOME 을
    # 존중하게 되는 날 harness_home() 이 조용히 엉뚱한 루트에 심기 시작한다.
    dirname = providers.get(target).home_dirname if target in providers.names() else f".{target}"
    return paths.home() / dirname


def skills_root(target: str) -> Path:
    return harness_home(target) / "skills"


def hook_file(target: str) -> Path:
    from notionmemory import providers
    return harness_home(target) / providers.get(target).hook_file_name


def hook_file_is_dedicated(target: str) -> bool:
    """이 훅 파일은 우리가 없으면 존재하지 않는가.

    Codex 의 hooks.json 은 훅 전용이라 우리 블록을 빼면 파일째 지워야 한다 — 안 그러면
    teardown 뒤 `{"hooks": {}}` 껍데기가 남아 계약을 어긴다(실환경 검증에서 발견).
    Claude 의 settings.json 은 하네스·사용자 소유라 비어도 남긴다.
    """
    from notionmemory import providers
    return target in providers.names() and providers.get(target).hook_file_dedicated


def broker_agent_path() -> Path:
    """The macOS service that can read the user's Keychain outside agent sandboxes."""
    return paths.home() / "Library" / "LaunchAgents" / "com.notionmemory.notion-broker.plist"


def broker_spec(cli_path: str = "notionmemory") -> ArtifactSpec:
    return ArtifactSpec(
        id="shared.notion_broker", owner="_core", handler="launch_agent", target="shared",
        path=broker_agent_path(),
        payload={"label": "com.notionmemory.notion-broker", "program": cli_path,
                 "home": str(paths.home())},
        markers=("notionmemory broker",))


def HOOK_EVENTS(cli_path: str, harness: str = "claude") -> dict:
    """`harness` 는 hook 명령에 `--harness <값>` 으로 그대로 박힌다 — Codex 는
    Stop/PreCompact 에서 평문 stdout 을 실패 처리하므로(실측) 훅이 자신을 부른
    하네스를 알아야 한다. Claude 는 기본값(claude)이라 플래그를 아예 안 붙인다 —
    지금까지의 명령 문자열을 그대로 유지해 기존 신뢰/영수증에 영향이 없다."""
    def entry(hook_name: str, timeout: int = 20) -> dict:
        cmd = f"{cli_path} hook {hook_name}"
        if harness != "claude":
            cmd += f" --harness {harness}"
        return {"hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}
    # Stop 은 컨텍스트 주입용으로는 등록하지 않는다 — 매 턴 발화하는데 그 시점엔
    # 에이전트가 이미 턴을 끝냈고 Codex 스키마상 hookSpecificOutput 이 없다(위와 같은
    # 이유로 SessionStart 로 안내를 옮긴 내력은 그대로다). 하지만 Second Brain v2 는
    # Stop 을 **큐잉 전용**(session-stop, 무출력·비블로킹)으로 쓴다 — 컨텍스트를
    # 주입하지 않으므로 위 제약과 충돌하지 않는다.
    # SessionEnd 는 **스폰 전용**(무출력)이다 — Stop 을 컨텍스트 주입에 못 쓰게 만든
    # "additionalContext 채널 없음" 제약 자체가 여기선 적용되지 않는다(애초에 아무것도
    # 주입하지 않으므로). Codex 공식 문서상 SessionEnd 타임아웃은 기본 1초/최대 3초라
    # 여기서는 그 상한(3)을 쓴다 — Claude 는 기존 훅들과 같은 20초 그대로.
    return {"SessionStart": [entry("session-start")],
            "PreCompact": [entry("save-reminder")],
            "Stop": [entry("session-stop")],
            # UserPromptSubmit 은 메시지마다 로컬 memory 색인만 훑어 관련성 게이트를
            # 넘을 때만 힌트를 주입한다(네트워크 0, task-3 계약) — Stop 과 달리
            # additionalContext 채널이 있어 컨텍스트 주입에 써도 된다.
            "UserPromptSubmit": [entry("user-prompt")],
            "SessionEnd": [entry("session-end", timeout=3 if harness == "codex" else 20)]}


def KIMI_HOOK_EVENTS(cli_path: str) -> dict:
    """Kimi capture pipeline: UserPromptSubmit injects recall; Stop enqueues the
    session (session_stop resolves wire.jsonl); SessionEnd spawns consolidation
    (observation-only, timeout 3). SessionStart/PreCompact are omitted — Kimi
    discards their stdout, so recall/reminder injection there has no effect."""
    def entry(hook_name: str, timeout: int) -> dict:
        return {"hooks": [{"type": "command",
                           "command": f"{cli_path} hook {hook_name} --harness kimi",
                           "timeout": timeout}]}
    return {"UserPromptSubmit": [entry("user-prompt", 20)],
            "Stop": [entry("session-stop", 20)],
            "SessionEnd": [entry("session-end", 3)]}


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
    from notionmemory import providers

    specs: list[ArtifactSpec] = []

    # post-install 명세(예: codex.trust)는 루프 도중 모아 루프가 끝난 뒤 append 한다 —
    # 신뢰 등록은 hooks.json 을 쓴 뒤에만 의미가 있으므로(예전 코드의 순서 그대로
    # 훅 명세들 다음 위치를 유지) 방출 순서가 바뀌면 안 된다.
    post_specs: list[ArtifactSpec] = []
    for target in targets:
        provider = providers.get(target)
        if provider.install_kind == "bundle":
            specs.append(ArtifactSpec(
                id=f"{target}.bundle", owner="_core", handler="bundle_mirror",
                target=target,
                path=harness_home(target) / provider.bundle_install_subpath,
                payload={"source": provider.bundle_source, "cli_path": cli_path},
                markers=(f"notionmemory {target} bundle",)))
            if provider.post_install_spec is not None:
                post_specs.append(provider.post_install_spec())
            continue
        for name in skill_assets.skill_names():
            specs.append(ArtifactSpec(
                id=f"{target}.skills.{name}", owner=name, handler="skill_mirror",
                target=target, path=skills_root(target) / name,
                payload={"source": str(skill_assets.skills_root() / name)},
                markers=(name,)))
        handler = "toml_hook_block" if provider.hook_format == "toml" else "json_hook_block"
        specs.append(ArtifactSpec(
            id=f"{target}.hooks", owner="_core", handler=handler,
            target=target, path=hook_file(target),
            payload={"events": provider.events(cli_path)},
            markers=HOOK_MARKERS))
        if provider.post_install_spec is not None:
            post_specs.append(provider.post_install_spec())
    specs.extend(post_specs)

    # git 은 하네스와 무관하게 리포별 post-commit 훅을 소유한다 — target="shared" 로 한 번만.
    # notionmemory install 이 심지는 않지만(GitHooks.install 은 no-op), 매니페스트에
    # 있어야 teardown 이 찾는다.
    specs.append(ArtifactSpec(
        id="shared.git_hooks", owner="git", handler="git_hooks", target="shared",
        path=paths.config_path(), payload={}, markers=("notionmemory git",)))
    # Codex 같은 sandbox 안의 CLI는 macOS Keychain을 직접 읽을 수 없다. 이 서비스는
    # PAT를 노출하지 않고 private Unix socket을 통해 Notion 요청만 프록시한다.
    specs.append(broker_spec(cli_path))
    return specs
