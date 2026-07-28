"""Codex app-server 질의 — 훅 신뢰 키·해시를 실측한다.

신뢰 키는 `<hooks.json 절대경로>:<snake_case 이벤트>:<그룹>:<핸들러>` 형태이고 끝의
인덱스는 사용자가 자기 훅을 추가하면 밀린다. 이벤트 이름도 hooks.json 의 PascalCase 와
달리 snake_case 다. 그래서 키를 조립하지 않고 hooks/list 가 준 값을 그대로 쓴다.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time

TIMEOUT_S = 30


def available() -> bool:
    return bool(shutil.which("codex"))


def hooks_list(cwd: str = "") -> list[dict]:
    """app-server 에 initialize → hooks/list 를 보내고 hook 항목들을 돌려준다.

    `subprocess.run(input=...)` 는 stdin 을 쓰고 바로 닫아버린다 — app-server 는
    그걸 EOF 로 보고 응답 없이 종료해버려서(실측: 0.1초, returncode 0, stdout 0줄)
    항상 빈 리스트로 낮아지는 조용한 실패였다(2026-07-21 실기 재현). 그래서
    `Popen` 으로 stdin 을 응답이 올 때까지 열어둔 채로 쓴다.

    이 함수의 계약은 "실패하면 빈 리스트로 낮아진다, 절대 raise 하지 않는다" 다 —
    바이너리 부재, spawn 실패, 타임아웃, 깨진/비-dict 줄, 응답이 영영 안 오는 경우
    모두 포함한다. 자식 프로세스는 성공/타임아웃/예외 어느 경로로 빠지든 항상
    정리한다(고아 app-server 프로세스를 남기지 않는다).
    """
    req = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"clientInfo": {"name": "notionmemory", "version": "1",
                                   "title": "notionmemory"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "hooks/list",
         "params": {"cwds": [cwd or os.getcwd()]}},
    ]
    payload = "".join(json.dumps(r) + "\n" for r in req)
    try:
        proc = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, bufsize=1)
    except (OSError, subprocess.SubprocessError):
        return []
    try:
        try:
            proc.stdin.write(payload)
            proc.stdin.flush()
        except (OSError, ValueError):
            return []
        return _await_id2(proc, TIMEOUT_S)
    finally:
        _terminate(proc)


def _await_id2(proc: subprocess.Popen, timeout_s: float) -> list[dict]:
    """id==2 응답 줄이 올 때까지 stdout 을 읽는다 — 데드라인까지.

    파이프 읽기 자체에는 타임아웃이 없으므로(POSIX 파일 읽기는 블로킹) 별도
    스레드에서 읽어 큐에 넣고, 메인 쪽은 큐를 데드라인까지만 기다린다. 스레드는
    daemon 이라 데드라인을 넘겨도 인터프리터 종료를 막지 않는다 — 자식 프로세스
    정리는 호출자의 `_terminate` 가 담당한다.
    """
    q: "queue.Queue[str | None]" = queue.Queue()

    def _pump() -> None:
        try:
            for line in proc.stdout:
                q.put(line)
        except (OSError, ValueError):
            pass
        finally:
            q.put(None)          # EOF 표식 — stdout 이 응답 전에 닫힌 경우 포함

    threading.Thread(target=_pump, daemon=True).start()
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return []
        try:
            line = q.get(timeout=remaining)
        except queue.Empty:
            return []
        if line is None:
            return []            # stdout 이 id==2 응답 전에 닫혔다
        entries = _parse_id2_line(line)
        if entries is not None:
            return entries


def _parse_id2_line(line: str) -> list[dict] | None:
    """`line` 이 id==2 응답이면 hook 항목 리스트(빈 리스트 가능)를, 아니면(다른
    id·비-JSON·비-dict) None 을 돌려준다 — None 은 "이 줄은 아니니 계속 읽어라"."""
    try:
        msg = json.loads(line)
    except ValueError:
        return None
    if not isinstance(msg, dict) or msg.get("id") != 2:
        return None
    entries: list[dict] = []
    result = msg.get("result")
    if not isinstance(result, dict):
        return entries
    data = result.get("data")
    if not isinstance(data, list):
        return entries
    for group in data:
        if not isinstance(group, dict):
            continue
        hooks = group.get("hooks")
        if not isinstance(hooks, list):
            continue
        entries.extend(h for h in hooks if isinstance(h, dict))
    return entries


def _terminate(proc: subprocess.Popen) -> None:
    """자식을 항상 정리한다 — 고아 app-server 프로세스를 남기지 않는다."""
    try:
        if proc.stdin is not None:
            proc.stdin.close()
    except (OSError, ValueError):
        pass
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        proc.kill()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def our_hooks(entries: list[dict], hooks_path: str,
              markers: tuple[str, ...]) -> list[dict]:
    """우리 hooks.json 이 출처이고 명령이 우리 것인 항목만.

    판정은 `handlers.hook_command_is_ours` 하나로 한다 — 여기서 틀리면 결과가
    "우리 것이 아닌 명령에 Codex 신뢰(trusted_hash)를 부여"이고, 그건 사용자
    시스템의 보안 관문을 우리가 대신 열어주는 일이다. 예전 `marker in command`
    부분일치는 `/Users/bob/backups/old_memory_hooks_project/run.sh` 같은 남의
    명령을 우리 것으로 오판했다(최종 리뷰 Critical).
    """
    from notionmemory.core.install.handlers import hook_command_is_ours
    out = []
    for e in entries:
        if str(e.get("sourcePath") or "") != str(hooks_path):
            continue
        if hook_command_is_ours(e.get("command"), markers):
            out.append(e)
    return out
