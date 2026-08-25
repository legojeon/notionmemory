"""teardown — 심은 것을 전부 되돌린다. Notion DB 와 사용자 데이터는 보존한다.

2층 구조:
  1층 영수증 — 이 설치가 실제로 심은 것의 정확한 기록
  2층 마커 스윕 — 구버전이 심은 것, 영수증이 유실된 것, 다른 체크아웃이 심은 것
합집합을 제거한다.
"""
from __future__ import annotations

from pathlib import Path

from notionmemory.core import paths, skill_assets
from notionmemory.core.install import manifest, receipt
from notionmemory.core.install.handlers import HANDLERS, OWNED_MARKER_FILE
from notionmemory.core.install.spec import ArtifactSpec
from notionmemory.skills.git import queue as gc_queue

# 구 이름으로 설치된 스킬 디렉터리. 우리만 쓰던 이름이라 이름 매칭으로 안전하다.
LEGACY_SKILL_NAMES = ("notes-capture", "git-capture", "memory-capture", "notes", "calendar")


def _from_receipt() -> list[ArtifactSpec]:
    """영수증은 JSON 파일 — 우리가 이번에 쓴 것이라는 보장이 없다.

    더 새 버전이 추가한 핸들러 이름이나 필드가 빠진 항목이 들어 있을 수 있으므로
    해석 가능한 항목만 취한다. 건너뛴 것은 `_unknown_receipt_handlers` 가 경고로
    알린다 — 조용히 삼키면 "제거했다"고 출력하고 아무것도 안 지운 것과 같다.
    """
    out = []
    for e in receipt.read():
        if e.get("handler") not in HANDLERS:
            continue
        try:
            out.append(ArtifactSpec(id=e["id"], owner=e["owner"], handler=e["handler"],
                                    target=e["target"], path=Path(e["path"]),
                                    payload={}, markers=tuple(e.get("markers") or ())))
        except (KeyError, TypeError):
            continue
    return out


def _sweep(targets: list[str]) -> list[ArtifactSpec]:
    """영수증과 무관하게 알려진 위치를 훑는다."""
    # 심는 곳과 같은 함수로 위치를 정한다 — 스윕이 자체 경로 계산을 갖고 있으면
    # CODEX_HOME 같은 오버라이드 환경에서 심은 것을 못 찾는다.
    # 지연 임포트: manifest.build() 와 같은 이유(모듈 최상단에 두면 providers 쪽
    # 순환 임포트 위험 — manifest._home_env() 주석 참고).
    from notionmemory import providers

    roots = {t: manifest.skills_root(t) for t in targets}
    hook_files = {t: manifest.hook_file(t) for t in targets}
    names = list(skill_assets.skill_names()) + list(LEGACY_SKILL_NAMES)

    out = []
    for target in targets:
        for name in names:
            out.append(ArtifactSpec(
                id=f"{target}.skills.{name}", owner=name, handler="skill_mirror",
                target=target, path=roots[target] / name, payload={}, markers=(name,)))
        # 핸들러는 manifest.build() 와 동일하게 provider.hook_format 으로 정한다 —
        # 여기서 json_hook_block 을 하드코딩하면 toml 포맷 provider(kimi)의 훅 블록이
        # 영수증 없는 스윕 경로에서 detect() 실패로 조용히 안 지워진다(리뷰 Important).
        handler = ("toml_hook_block" if target in providers.names()
                   and providers.get(target).hook_format == "toml" else "json_hook_block")
        out.append(ArtifactSpec(
            id=f"{target}.hooks", owner="_core", handler=handler,
            target=target, path=hook_files[target], payload={},
            markers=manifest.HOOK_MARKERS))
    if "codex" in targets:
        # 명세를 다시 조립하지 않는다 — 매니페스트가 단일 진실이다(CLAUDE.md 규칙 1).
        out.append(manifest.codex_trust_spec())

    # git 훅은 하네스와 무관하다 — 영수증이 없어도 레지스트리를 통해 찾는다.
    out.append(ArtifactSpec(
        id="shared.git_hooks", owner="git", handler="git_hooks", target="shared",
        path=paths.config_path(), payload={}, markers=("notionmemory git",)))
    out.append(manifest.broker_spec())
    return out


def discover(targets: list[str]) -> list[ArtifactSpec]:
    """영수증 ∪ 스윕. 같은 id 는 한 번만."""
    seen: dict[str, ArtifactSpec] = {}
    for spec in _from_receipt() + _sweep(targets):
        if spec.target not in targets and spec.target != "shared":
            continue
        seen.setdefault(f"{spec.id}:{spec.path}", spec)
    return [s for s in seen.values() if HANDLERS[s.handler].detect(s)]


def _legacy_skill_dirs_are_removable(spec: ArtifactSpec) -> bool:
    """구 이름 디렉터리는 사이드카가 없어도 우리 것으로 본다(우리만 쓰던 이름)."""
    return Path(spec.path).name in LEGACY_SKILL_NAMES


def _unowned_same_name_dirs(targets: list[str]) -> list[Path]:
    """동명이지만 소유 표시가 없는 스킬 디렉터리 — 손대지 않고 알리기만 한다.

    마커를 안 남기던 구 `scripts/sync_skills.py` 는 canonical 디렉터리를 그대로
    복사만 했으므로(식별자 0), 여기 걸리는 것이 "구버전이 심은 우리 것"인지
    "사용자가 직접 만든 스킬"인지 파일 시스템으로는 구분할 수 없다. 지우는 쪽으로
    틀리면 사용자 데이터를 잃으므로 판단을 사람에게 넘긴다 — 다만 **말은 해야**
    한다. 이 경고가 없으면 업그레이드한 기계에서 teardown 이 이 디렉터리들에 대해
    한 줄도 출력하지 않은 채 "잔재 0"처럼 보인다(스펙 §5.3 의 약속).
    """
    out: list[Path] = []
    for spec in _sweep(targets):
        if spec.handler != "skill_mirror" or _legacy_skill_dirs_are_removable(spec):
            continue
        path = Path(spec.path)
        if not path.is_dir() or HANDLERS["skill_mirror"].detect(spec):
            continue
        if path not in out:
            out.append(path)
    return out


def _unknown_receipt_handlers() -> list[tuple[str, str]]:
    """영수증에 우리가 모르는 핸들러가 든 항목 — (id, handler).

    더 새 버전이 설치한 뒤 예전 체크아웃으로 teardown 을 돌리면 생긴다. 예전에는
    `HANDLERS[s.handler]` 가 KeyError 로 터져 **아무것도** 제거되지 않았다 —
    복구 경로에서 가장 나쁜 실패다. 이제는 건너뛰고 경고한다.
    """
    return [(str(e.get("id") or "?"), str(e.get("handler")))
            for e in receipt.read() if e.get("handler") not in HANDLERS]


def _still_there(path: Path | str) -> bool:
    """rmtree 뒤에도 남아 있는가. 깨진 심링크는 exists() 가 False 이므로 함께 본다."""
    p = Path(path)
    return p.exists() or p.is_symlink()


def _pending_git_queue_count() -> int:
    """flush 되지 않은 git 커밋 큐 항목 수. 상태 디렉터리를 지우면 이 기록도
    함께 사라진다 — teardown 이전에 사용자에게 경고해야 한다(리뷰 Important)."""
    return len(gc_queue.list_entries())


def _registered_template_count() -> int:
    """상태 디렉터리를 지우면 프로필도 함께 사라진다 — 몇 건인지는 알려준다.

    Notion 페이지·DB 는 건드리지 않으므로 경고가 아니라 정보다(CLAUDE.md 규칙 5).
    """
    from notionmemory.skills.templates import profile
    return len(profile.list_slugs())


def run(targets: list[str], *, purge_config: bool = False,
        purge_secrets: bool = False, dry_run: bool = False) -> list[str]:
    """미리보기(dry_run)와 실제 실행이 같은 결과를 서술해야 한다 — 확인 프롬프트가
    보여주는 목록이 실제로 일어날 일과 다르면 확인 게이트가 신뢰할 수 없어진다
    (리뷰 Important). 그래서 아래는 dry_run 여부와 무관하게 끝까지 훑되, 실제
    파괴적 동작(rmtree/unlink/keyring 호출)만 `if not dry_run`으로 감싼다.
    """
    from notionmemory.core import i18n, messages
    from notionmemory.core.config import Config
    lang = i18n.language(Config.load(str(paths.config_path())))

    def M(key, **fmt):
        return i18n.t(messages.CATALOG, key, lang, **fmt)

    lines: list[str] = []
    for art_id, handler in _unknown_receipt_handlers():
        lines.append(M("teardown.unknown_handler", id=art_id, handler=handler))
    found = discover(targets)

    # 구 이름 디렉터리는 detect()(사이드카 기준)가 놓치므로 따로 모은다.
    for spec in _sweep(targets):
        if spec.handler == "skill_mirror" and _legacy_skill_dirs_are_removable(spec) \
                and Path(spec.path).is_dir() and spec not in found:
            found.append(spec)

    for spec in found:
        if dry_run:
            lines.append(M("teardown.will_remove", id=spec.id, path=spec.path))
            continue
        if _legacy_skill_dirs_are_removable(spec):
            import shutil
            # ignore_errors=True 는 실패를 삼킨다 — 심링크(rmtree 가 거부한다)나
            # 권한 문제로 살아남은 디렉터리를 "제거" 라고 출력하면 안 된다.
            shutil.rmtree(spec.path, ignore_errors=True)
            if _still_there(spec.path):
                lines.append(M("teardown.remove_failed_legacy", id=spec.id, path=spec.path))
            else:
                lines.append(M("teardown.removed_legacy", id=spec.id, path=spec.path))
            continue
        # 한 항목의 실패가 나머지를 못 지우게 두면 안 된다 — 영수증에 모르는 핸들러가
        # 있을 때와 같은 부류의 사고다. teardown 은 복구 경로이고, 여기서 트레이스백으로
        # 끝나면 사용자에게 남는 건 "절반만 지워진 설치"다.
        try:
            removed = HANDLERS[spec.handler].remove(spec)
        except OSError as exc:
            lines.append(M("teardown.remove_failed", id=spec.id, path=spec.path,
                           err=exc.strerror or exc))
            continue
        if removed:
            lines.append(M("teardown.removed", id=spec.id, path=spec.path))

    for path in _unowned_same_name_dirs(targets):
        lines.append(M("teardown.keep_unowned", path=path, marker=OWNED_MARKER_FILE))

    pending = _pending_git_queue_count()
    if pending:
        lines.append(M("teardown.pending_git", n=pending))

    registered = _registered_template_count()
    if registered:
        # 차단성 경고가 아니라 정보 한 줄이다 — git 큐는 원본이 없는 데이터지만
        # 프로필은 전부 파생 데이터라 URL 만 있으면 재등록으로 복구된다.
        lines.append(M("teardown.registered_templates", n=registered))

    state = paths.state_dir()
    if state.is_dir():
        if dry_run:
            lines.append(M("teardown.will_remove_state", path=state))
        else:
            import shutil
            shutil.rmtree(state, ignore_errors=True)
            if _still_there(state):
                # 바로 위에서 "미전송 git 커밋 N건이 삭제됩니다" 라고 경고해 놓고
                # 삭제도 안 되고 제거됐다고 출력하면 두 번 거짓말이다.
                lines.append(M("teardown.remove_failed_state", path=state))
            else:
                lines.append(M("teardown.removed_state", path=state))

    cfg = paths.config_path()
    if purge_config:
        if cfg.exists():
            if dry_run:
                lines.append(M("teardown.will_remove_config", path=cfg))
            else:
                cfg.unlink()
                lines.append(M("teardown.removed_config", path=cfg))
    else:
        lines.append(M("teardown.keep_config"))

    if purge_secrets:
        if dry_run:
            lines.append(M("teardown.will_remove_secrets"))
        else:
            # 단일 진실: notion_auth 가 저장한 것과 같은 (service, account) 로 지운다.
            # 예전에 여기서 account 를 "token" 으로 하드코딩했는데 실제 저장은
            # PAT_ACCOUNT="personal-access-token" 이라, purge 가 조용히 아무것도
            # 못 지우고 "removed" 만 출력했다(라이브 e2e 가 잡음). 좌표를 재선언하지
            # 말고 canonical delete_pat() 에 위임한다.
            from notionmemory.core import notion_auth
            had_pat = bool(notion_auth.load_pat())
            notion_auth.delete_pat()
            lines.append(M("teardown.removed_secrets" if had_pat
                           else "teardown.remove_failed_secrets"))
    else:
        lines.append(M("teardown.keep_secrets"))

    lines.append(M("teardown.keep_notion"))
    return lines
