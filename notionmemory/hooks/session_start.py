#!/usr/bin/env python3
"""SessionStart 훅 — 현 프로젝트의 memory 를 recall 해 세션 컨텍스트로 주입.

Claude Code / Codex 공용. 어떤 실패도 조용히 무시한다(세션 시작을 막지 않음).
등록은 `notionmemory install` 이 수행한다(매니페스트의 훅 아티팩트 → JsonHookBlock).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from notionmemory.core import paths
from notionmemory.hooks.common import capture_mode

# 훅이 안내 문구에 넣는 명령 이름 — 사용자가 그대로 따라 칠 수 있어야 하므로 맨 이름을 쓴다.
# subprocess 호출(resolve_cli())과는 별개다 — 저건 실행 경로, 이건 사람이 읽는 문구.
CLI = "notionmemory"
TIMEOUT_S = 12
# recall이 저장된 memory가 하나도 없을 때만 찍는 문구. 이 마커가 있으면 실제
# memory 내용 줄은 전혀 없다는 뜻이므로 세션 컨텍스트에 노이즈를 주입하지 않는다.
NO_RESULTS_MARKER = "(저장된 memory 없음)"


def _lang() -> str:
    """config 의 language 로 훅 문구 언어를 정한다(기본 en). 실패해도 en 폴백."""
    try:
        from notionmemory.core import i18n
        from notionmemory.core.config import Config
        return i18n.language(Config.load(str(paths.config_path())))
    except Exception:
        return "en"


def _m(key: str, **fmt) -> str:
    from notionmemory.core import i18n, messages
    return i18n.t(messages.CATALOG, key, _lang(), **fmt)


def resolve_cli() -> str:
    """recall 을 되부를 notionmemory 실행파일 경로.

    이 프로세스 자체가 notionmemory CLI 다 — install 이 훅 명령에 박아둔 절대경로로
    실행되면 sys.argv[0] 이 곧 그 경로다("생성 컨텍스트는 경로를 해석한다"는 이
    마일스톤의 규칙은 이 자식 프로세스 호출에도 적용된다). 실측: bare "notionmemory"
    가 PATH 에 없는 머신에서 이 훅이 recall 없이 조용히 완료됐다 — 훅은 절대경로로
    실행되므로 살아남지만, 그 안에서 다시 부르는 recall 은 PATH 조회에 실패해
    FileNotFoundError 로 삼켜졌다. argv[0] 이 경로처럼 안 보이면 PATH 조회로,
    그마저 실패하면 맨 이름으로 폴백한다(최소한 실패가 예측 가능하도록).
    """
    argv0 = sys.argv[0] if sys.argv else ""
    if argv0 and (os.path.isabs(argv0) or os.sep in argv0):
        return argv0
    return shutil.which(CLI) or CLI


def resolve_toplevel(cwd: str) -> str:
    """git toplevel 절대경로, git 리포가 아니거나 실패하면 ""."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=cwd or None,
            capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:
        return ""


def resolve_project(cwd: str) -> str:
    """git toplevel basename, 실패 시 cwd basename."""
    top = resolve_toplevel(cwd)
    if top:
        return Path(top).name
    return Path(cwd or ".").resolve().name


def git_queue_reminder(toplevel: str) -> str:
    """이 리포의 미처리 커밋 큐 안내. 없으면 "".

    `toplevel` 은 main() 이 이미 구한 값을 받는다 — 여기서 다시 `git rev-parse` 를
    돌면 세션 시작마다 서브프로세스가 하나 더 는다.

    save_reminder(Stop/PreCompact)에서 옮겨왔다. Stop 에는 컨텍스트 주입 채널이 없어
    이 안내가 에이전트에게 전달된 적이 없고(사람에게만 `warning:` 으로 보였다), 그래서
    큐가 42건까지 쌓였다. SessionStart 는 주입이 실증된 유일한 채널이고, 턴 **시작**
    시점이라 에이전트가 실제로 처리할 여지가 있다.
    """
    top = toplevel
    if not top or capture_mode() != "auto":
        return ""
    try:
        from notionmemory.skills.git import queue
        entries = queue.list_entries(top)
        if not entries:
            return ""
        return _m("hook.git_queue", n=len(entries), cli=CLI, project=Path(top).name)
    except Exception:
        return ""


def maybe_install_git_hook(toplevel: str) -> str:
    """install_policy 에 따라 훅을 결정적으로 설치. 반환값 = 세션 주입 문구("" = 없음)."""
    if not toplevel:
        return ""
    try:
        import yaml
        raw = yaml.safe_load(paths.config_path().read_text(encoding="utf-8")) or {}
        opts = (raw.get("skills") or {}).get("git") or {}
        raw_policy = opts.get("install_policy")
        # YAML 1.1은 bare off/on/yes/no 를 bool로 파싱하므로(off → False),
        # `raw_policy or "auto"` 로 곧장 접으면 off가 auto로 되돌아간다 — False를 먼저 걸러낸다.
        policy = "off" if raw_policy is False else str(raw_policy or "auto")
        if policy == "off" or toplevel in (opts.get("exclude") or []):
            return ""
        from notionmemory.skills.git import hooks
        if hooks.is_installed(Path(toplevel)):
            return ""
        if policy == "ask":
            return _m("hook.git_hook_ask", toplevel=toplevel, cli=CLI)
        hooks.install(Path(toplevel), str(paths.config_path()))
        return _m("hook.git_hook_installed", toplevel=toplevel, cli=CLI)
    except Exception:
        return ""


def templates_injection() -> str:
    """등록된 템플릿 한 줄. 네트워크를 찍지 않고 프로필 파일만 읽는다.

    이 줄이 없으면 라우팅 규칙(SKILL.md)이 볼 목록이 없어 내장 스킬만 조회하고
    등록 템플릿을 조용히 누락한다 — 사용자는 그 일이 일어났다는 사실조차 모른다.
    """
    try:
        from notionmemory.skills.templates import profile
        return profile.injection_line(profile.load_all())
    except Exception:
        return ""


def library_injection() -> str:
    """library 색인 나이 한 줄. 네트워크 0 — 로컬 색인 파일만 읽는다.

    빈 색인은 무출력이 아니라 **신호**를 낸다(memory 의 suppress-when-empty 와 반대):
    설치 후 첫 세션에 에이전트가 이걸 보고 refresh 를 돌려 색인을 만든다(스펙 §4·§6).
    접두사를 고정한다 — 첫 글자가 '[' 나 '{' 이면 Claude Code 2.1.215+ 가 훅을 실패 처리한다.
    """
    try:
        from notionmemory.skills.library import index
        idx = index.load()
        if not index.was_refreshed(idx):
            return _m("hook.library_empty")
        n = index.count(idx)
        if not n:
            # refresh 는 돌았는데 공유 페이지가 0개 — 넛지하지 않는다(빈 워크스페이스를 매
            # 세션 닦달하지 않기 위해; templates/memory 의 suppress-when-empty 와 같은 침묵).
            return ""
        wm = index.watermark(idx) or _m("hook.watermark_unknown")
        return _m("hook.library_count", n=n, watermark=wm)
    except Exception:
        return ""


def main(harness: str = "claude") -> int:
    """`harness` 는 CLI 의 `hook --harness` 값 그대로 받는다.

    두 하네스 모두 SessionStart 에서는 평문 stdout 을 받아들인다고 실기로 확인됐다
    (원 조사 프로브). 그래서 이 훅은 harness 값에 따라 출력 형태를 바꾸지 않는다 —
    Codex 용 `hookSpecificOutput.additionalContext` 구조로 바꾸는 것도 가능하지만,
    두 하네스에서 이미 동작하는 평문을 유지하는 쪽이 더 단순해 그걸 택했다
    (Stop/PreCompact 는 반대로 이벤트별 상이함이 실기로 확인돼 save_reminder 가
    harness 를 실제로 분기한다).
    """
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        cwd = str(payload.get("cwd") or "")
        top = resolve_toplevel(cwd)
    except Exception:
        return 0
    # 세 조각은 서로 독립이다 — 각각 따로 감싼다. 한 덩어리로 감쌌더니 recall 이
    # 던지는 순간(예: notionmemory 가 PATH 에 없어 FileNotFoundError) 뒤의 git 훅
    # 안내와 큐 안내까지 통째로 사라졌다. 아무 출력 없이 훅은 성공으로 끝나므로
    # 원인을 추적할 방법이 없다 — 이 프로젝트가 반복해서 밟은 무음 실패다.
    try:
        project = Path(top).name if top else Path(cwd or ".").resolve().name
        run = subprocess.run([resolve_cli(), "recall", "--project", project],
                             capture_output=True, text=True, timeout=TIMEOUT_S)
        out = run.stdout.strip()
        if run.returncode == 0 and out and NO_RESULTS_MARKER not in out:
            # 주의: 첫 글자가 '['/'{' 이면 Claude Code(2.1.215+)가 stdout을 JSON으로
            # 스니핑하다 파싱 실패로 훅을 실패 처리한다 — 평문임이 명확한 접두사 유지.
            print(f"notionmemory recall — project={project}:\n{out}")
    except Exception:
        pass
    try:
        note = maybe_install_git_hook(top)
        if note:
            print(note)
        line = templates_injection()
        if line:
            print(line)
        lib = library_injection()
        if lib:
            print(lib)
    except Exception:
        pass
    try:
        queue_note = git_queue_reminder(top)
        if queue_note:
            print(queue_note)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
