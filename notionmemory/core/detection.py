"""CLI 감지 유틸 — PATH 하이드레이션 + which + --version 검증, TTL 캐시.

orca의 hydrate-shell-path / isCommandAvailable 패턴의 최소 구현.
status()가 대시보드 렌더마다 호출되므로 모든 서브프로세스 결과는 TTL 캐시.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass

_TTL = 60.0
_probe_cache: dict[str, tuple[float, "Probe"]] = {}
_run_cache: dict[str, tuple[float, tuple[int, str]]] = {}
_shell_path: str | None = None


@dataclass
class Probe:
    ok: bool
    path: str = ""
    version: str = ""
    error: str = ""
    # 안정 키 — ko 오버레이가 `tui(lang, error_key, error)`로 error 를 재조회할 수 있게
    # 한다(messages.UI_KO). exit code/exc 를 담은 두 케이스는 포맷 인자를 여기서 못
    # 채우므로 의도적으로 UI_KO 항목이 없다 — 그 경우 tui() 는 error(영어)로 폴백한다.
    error_key: str = ""


def clear_cache() -> None:
    global _shell_path
    _probe_cache.clear()
    _run_cache.clear()
    _shell_path = None


def login_shell_path() -> str:
    """로그인 셸의 PATH를 1회 조회해 현재 PATH와 병합(중복 제거). 실패 시 현재 PATH."""
    global _shell_path
    if _shell_path is not None:
        return _shell_path
    current = os.environ.get("PATH", "")
    shell = os.environ.get("SHELL", "/bin/sh")
    try:
        out = subprocess.run([shell, "-lc", "echo $PATH"],
                             capture_output=True, text=True, timeout=5.0)
        login = out.stdout.strip().splitlines()[-1] if out.returncode == 0 and out.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError):
        login = ""
    if login:
        entries = dict.fromkeys(login.split(os.pathsep) + current.split(os.pathsep))
        _shell_path = os.pathsep.join(e for e in entries if e)
    else:
        _shell_path = current
    return _shell_path


def probe_cli(cmd: str, *, refresh: bool = False) -> Probe:
    """which + `<cmd> --version` 실행 검증. 결과는 TTL 캐시."""
    now = time.monotonic()
    hit = _probe_cache.get(cmd)
    if hit and not refresh and now - hit[0] < _TTL:
        return hit[1]
    found = shutil.which(cmd, path=login_shell_path())
    if not found:
        probe = Probe(ok=False, error="not on PATH", error_key="detect.not_on_path")
    else:
        try:
            out = subprocess.run([found, "--version"],
                                 capture_output=True, text=True, timeout=5.0)
            text = (out.stdout or out.stderr).strip()
            first = text.splitlines()[0] if text else ""
            if out.returncode == 0:
                probe = Probe(ok=True, path=found, version=first)
            else:
                probe = Probe(ok=False, path=found, error=f"run failed (exit {out.returncode})",
                              error_key="detect.run_failed")
        except subprocess.TimeoutExpired:
            probe = Probe(ok=False, path=found, error="run timed out", error_key="detect.timeout")
        except OSError as exc:
            probe = Probe(ok=False, path=found, error=f"cannot run: {exc}",
                          error_key="detect.cannot_run")
    _probe_cache[cmd] = (now, probe)
    return probe


def run_cli(argv: list[str], timeout: float = 5.0, *,
            cache_key: str | None = None, refresh: bool = False) -> tuple[int, str]:
    """임의 CLI 실행 → (returncode, 합쳐진 출력). cache_key 지정 시 TTL 캐시."""
    now = time.monotonic()
    if cache_key and not refresh:
        hit = _run_cache.get(cache_key)
        if hit and now - hit[0] < _TTL:
            return hit[1]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        result = (out.returncode, (out.stdout + out.stderr).strip())
    except subprocess.TimeoutExpired:
        result = (124, "run timed out")
    except OSError as exc:
        result = (127, str(exc))
    if cache_key:
        _run_cache[cache_key] = (now, result)
    return result


def dotfolder(name: str) -> bool:
    """~/.<name> 디렉토리 존재 여부 (CLI 설치 감지의 보조 신호)."""
    return os.path.isdir(os.path.expanduser(f"~/.{name}"))
