"""install 실행기 — 매니페스트를 순회하며 핸들러에 위임하고 영수증을 남긴다."""
from __future__ import annotations

import shutil
from dataclasses import replace

from notionmemory.core import paths
from notionmemory.core.install import manifest, receipt
from notionmemory.core.install.handlers import (
    HANDLERS, OWNED_MARKER_FILE, OwnershipConflict)


def resolve_cli() -> str:
    """훅에 박을 notionmemory 절대경로. 훅이 도는 셸의 PATH 를 신뢰할 수 없다."""
    found = shutil.which("notionmemory")
    if not found:
        raise RuntimeError(
            "notionmemory 를 PATH 에서 찾을 수 없습니다. "
            "`uv tool install .` 또는 `pip install -e .` 로 먼저 설치하세요.")
    return found


def install(targets: list[str], trust_codex: bool = False,
            skip_skills: bool = False) -> list[str]:
    from notionmemory.core.install import codex
    from notionmemory.core import i18n, messages
    from notionmemory.core.config import Config
    lang = i18n.language(Config.load(str(paths.config_path())))

    def M(key, **fmt):
        return i18n.t(messages.CATALOG, key, lang, **fmt)

    lines: list[str] = []
    migrated = paths.migrate_config()
    if migrated:
        lines.append(migrated)

    if "codex" in targets and not codex.available():
        targets = [t for t in targets if t != "codex"]
        lines.append(M("install.codex_absent"))

    specs = manifest.build(targets, resolve_cli())
    done = []
    for spec in specs:
        if spec.id == "codex.trust":
            # 두 단계 아티팩트 — payload(신뢰 항목)는 hooks.json 을 쓴 뒤
            # hooks/list 로 실측해야 정해진다. 아래 신뢰 단계가 이 명세를 복제해
            # 채워 넣는다. 여기서 빈 payload 로 돌리면 "변경없음: codex.trust" 라는
            # 오해할 줄만 남는다(동의 없이도 뭔가 한 것처럼 보인다).
            continue
        if skip_skills and spec.handler == "skill_mirror" and spec.target == "codex":
            # 플러그인이 스킬을 소유하므로 미러하지 않는다(이중 방지).
            # 영수증에도 넣지 않아야 teardown 이 없는 것을 지우려 하지 않는다.
            continue
        try:
            changed = HANDLERS[spec.handler].install(spec)
        except OwnershipConflict as conflict:
            # §4.4 부분 실패 — 이 아티팩트만 건너뛰고 나머지는 계속 심는다.
            # 영수증에도 넣지 않는다: 심지 않은 것을 teardown 이 지우면 안 된다.
            lines.append(M("install.skip_conflict", id=spec.id, path=conflict.path,
                           marker=OWNED_MARKER_FILE))
            continue
        done.append(spec)
        lines.append(M("install.installed" if changed else "install.unchanged",
                       id=spec.id, path=spec.path))

    # 신뢰 등록은 hooks.json 을 쓴 뒤에만 의미가 있으므로 마지막에 한다.
    if "codex" in targets and trust_codex:
        hooks_path = next(s.path for s in specs if s.id == "codex.hooks")
        measured = codex.our_hooks(codex.hooks_list(), str(hooks_path),
                                   manifest.HOOK_MARKERS)
        if not measured:
            lines.append(M("install.trust_notfound"))
        else:
            trust_handler = HANDLERS["codex_trust"]
            safe, unsafe = trust_handler.split_safe(measured)
            if unsafe:
                lines.append(M("install.trust_unsafe", n=len(unsafe)))
            if safe:
                # 매니페스트의 명세를 복제해 payload 만 채운다 — 경로·마커·핸들러를
                # 여기서 다시 적으면 매니페스트와 갈라진다(CLAUDE.md 규칙 1).
                base = next(s for s in specs if s.id == "codex.trust")
                trust = replace(base, payload={"entries": safe})
                changed = trust_handler.install(trust)
                done.append(trust)
                lines.append(M("install.trust_registered" if changed
                               else "install.trust_unchanged",
                               n=len(safe), path=trust.path))
    elif "codex" in targets:
        lines.append(M("install.trust_absent"))

    receipt.write(done)
    lines.append(M("install.receipt", path=paths.receipt_path()))
    return lines
