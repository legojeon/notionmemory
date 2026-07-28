"""post-commit 훅 설치/제거 — 마커 블록, 멱등, 기존 훅 체이닝.

셸 블록은 queue.py 의 slug/포맷과 짝이다(sha256 8자리, `key value` + body).
훅은 어떤 경우에도 커밋을 실패시키지 않는다(서브셸 + `|| true`).
"""
from __future__ import annotations

from pathlib import Path

from notionmemory.core.config import Config, save_skill_options

MARKER_BEGIN = "# >>> notionmemory git >>>"
MARKER_END = "# <<< notionmemory git <<<"

# git-capture -> git 리네임 이전에 설치된 훅이 남긴 마커. is_installed()/_strip_block()이
# 이 쌍도 인식해야 구 설치를 감지·제거·재설치(멱등)할 수 있다.
LEGACY_MARKERS = [
    ("# >>> notionmemory git-capture >>>", "# <<< notionmemory git-capture <<<"),
]

ALL_MARKERS = [(MARKER_BEGIN, MARKER_END)] + LEGACY_MARKERS

HOOK_BLOCK = MARKER_BEGIN + """
(
  repo="$(git rev-parse --show-toplevel 2>/dev/null)" && [ -n "$repo" ] || exit 0
  chash="$(git rev-parse HEAD 2>/dev/null)" && [ -n "$chash" ] || exit 0
  qdir="${NOTIONMEMORY_GITQUEUE_DIR:-$HOME/.local/state/notionmemory/gitqueue}"
  slug="$(basename "$repo")-$(printf %s "$repo" | shasum -a 256 | cut -c1-8)"
  mkdir -p "$qdir/$slug" 2>/dev/null || exit 0
  {
    printf 'repo %s\\n' "$repo"
    printf 'branch %s\\n' "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
    printf 'ts %s\\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'subject %s\\n' "$(git log -1 --format=%s)"
    printf 'files %s\\n' "$(git diff-tree --no-commit-id --name-only -r --root HEAD | paste -sd, -)"
    printf 'body\\n'
    git log -1 --format=%b
  } > "$qdir/$slug/$chash" 2>/dev/null
) || true
""" + MARKER_END


def hook_path(repo: Path) -> Path:
    return Path(repo) / ".git" / "hooks" / "post-commit"


def is_installed(repo: Path) -> bool:
    hp = hook_path(repo)
    try:
        text = hp.read_text(encoding="utf-8")
    except OSError:
        return False
    if not hp.is_file():
        return False
    return any(begin in text for begin, _ in ALL_MARKERS)


def _strip_one(text: str, begin: str, end: str) -> str:
    if begin not in text:
        return text
    pre, _, rest = text.partition(begin)
    _, _, post = rest.partition(end)
    return (pre.rstrip("\n") + "\n" + post.lstrip("\n")).strip("\n") + "\n"


def _strip_block(text: str) -> str:
    """신 마커와 레거시(구) 마커 블록을 모두 제거한다(설치 이력이 섞여 있어도 멱등)."""
    for begin, end in ALL_MARKERS:
        while begin in text:
            text = _strip_one(text, begin, end)
    return text


def _registry(config_path: str) -> tuple[list[str], list[str]]:
    opts = Config.load(config_path).skill_options("git")
    return list(opts.get("repos") or []), list(opts.get("exclude") or [])


def install(repo: Path, config_path: str = "") -> bool:
    repo = Path(repo).resolve()
    hp = hook_path(repo)
    if not hp.parent.is_dir():
        raise RuntimeError(f"git 리포가 아닙니다: {repo}")
    base = _strip_block(hp.read_text(encoding="utf-8")) if hp.exists() else "#!/bin/sh\n"
    new = base.rstrip("\n") + "\n\n" + HOOK_BLOCK + "\n"
    changed = not hp.exists() or hp.read_text(encoding="utf-8") != new
    if changed:
        hp.write_text(new, encoding="utf-8")
    hp.chmod(hp.stat().st_mode | 0o755)
    if config_path:
        repos, exclude = _registry(config_path)
        if str(repo) not in repos or str(repo) in exclude:
            save_skill_options(config_path, "git", {
                "repos": sorted(set(repos) | {str(repo)}),
                "exclude": [e for e in exclude if e != str(repo)]})
    return changed


def uninstall(repo: Path, config_path: str = "") -> bool:
    repo = Path(repo).resolve()
    hp = hook_path(repo)
    changed = False
    if hp.is_file():
        text = hp.read_text(encoding="utf-8")
        stripped = _strip_block(text)
        if stripped != text:
            if stripped.strip() in ("", "#!/bin/sh"):
                hp.unlink()
            else:
                hp.write_text(stripped, encoding="utf-8")
            changed = True
    if config_path:
        repos, exclude = _registry(config_path)
        save_skill_options(config_path, "git", {
            "repos": [r for r in repos if r != str(repo)],
            "exclude": sorted(set(exclude) | {str(repo)})})
    return changed


def status(config_path: str) -> list[dict]:
    repos, _ = _registry(config_path)
    return [{"repo": r, "exists": Path(r).is_dir(),
             "installed": is_installed(Path(r))} for r in repos]
