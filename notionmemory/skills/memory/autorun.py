"""memory consolidation 자동 스폰 — 훅(Task 5)이 세션 안에서 부르되, 실제
`memory consolidate --auto` 는 detached 백그라운드 프로세스로 뜬다(세션을
블로킹하지 않기 위해 — LLM 패스 1회가 초 단위로 걸릴 수 있다).

게이트 순서(전부 통과해야 스폰, 하나라도 걸리면 조용히 False):
1. 재귀 가드 env(`NOTIONMEMORY_CONSOLIDATE`) — 이미 consolidate 안에서 실행 중이면
   훅이 다시 스폰하지 않는다(무한 재귀 방지, `mem_consolidate.run` 도 자체적으로
   같은 env 를 설정하지만 belt-and-suspenders 로 스포너 쪽에서도 확인한다).
2. `capture_mode() != "auto"` — 사용자가 memory 캡처 자체를 껐으면 consolidate 도 안 돈다.
3. `consolidate_mode() != "auto"` — capture 는 켰지만 consolidate 만 수동/넛지로
   둔 사용자를 위한 별도 스위치.
4. memory 가 바인딩돼 있지 않으면 스폰하지 않는다(C1) — PAT 만 연결되고 memory DB 를
   아직 안 만들었거나(또는 바인딩된 DB 가 휴지통에 가 있는) 상태에서 무인 스폰이
   `consolidate.run()` → `SecondBrainDB.ensure(create=True)` 를 거쳐 조용히 새 Second
   Brain DB 를 만들어버리는 사고를 여기서 1차로 막는다(2차 방어선은 `consolidate.run`
   자체의 `auto=True` no-create 경로 — defense in depth). session_start 훅의
   `memory_index_injection`과 같은 로컬-전용 프로브 패턴(network 0).
5. 큐가 비어있음 — 처리할 잡이 없으면 스폰할 이유가 없다.
6. 락 파일 존재 — **pre-check 만**이다(원자적 획득이 아니다). 실제 락 획득/해제는
   `--auto` CLI 경로(`acquire_lock`/`release_lock`) 자신이 한다 — 두 훅이 거의
   동시에 이 pre-check 를 통과해 둘 다 스폰될 수 있지만, 그중 하나만 락을 얻어
   실제로 진행하고 나머지는 `acquire_lock() is False` 로 즉시 조용히 종료한다
   (cli.py `return 0`). 락 파일 자체를 여기서 만들지 않는 이유: 스폰된 자식
   프로세스가 죽거나 exec 되기 전에 부모가 죽으면 락이 영원히 잡힌 채 남는 사고를
   피하려면, 락의 생애주기는 락을 실제로 쓰는 프로세스(자식) 안에서 열고 닫혀야
   한다."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import datetime, timezone

from notionmemory.core import paths
from notionmemory.hooks.common import capture_mode
from notionmemory.skills.memory import consolidation_queue as queue

LOCK_STALE_SECONDS = 1800
LOG_MAX_BYTES = 200_000
_LOG_KEEP_BYTES = 100_000


def consolidate_mode() -> str:
    """`skills.memory.consolidate_mode`. `hooks.common.capture_mode` 와 같은
    yaml-직접 읽기 패턴 — 읽지 못하면(파일 없음/파싱 실패 등) 기본값 auto."""
    try:
        import yaml
        raw = yaml.safe_load(paths.config_path().read_text(encoding="utf-8")) or {}
        return str(((raw.get("skills") or {}).get("memory") or {})
                   .get("consolidate_mode") or "auto")
    except Exception:
        return "auto"


def _memory_bound() -> bool:
    """memory 가 실제로 바인딩돼 있는지 로컬로만 확인한다(network 0, C1).

    session_start 훅의 `memory_index_injection`/`onboarding_injection` 과 똑같은
    패턴 — `status.probe(verify=False)` 는 저장된 data_source_id 유무만 보고 Notion
    에 왕복하지 않는다. 어떤 예외든 삼키고 False(=스폰 안 함)로 fail-closed 한다 —
    "확인 못 했으니 일단 만든다"가 아니라 "확인 못 했으니 안 만든다" 쪽이 이 함수의
    존재 이유(고아 DB 방지)에 맞다."""
    try:
        from notionmemory.core import status as status_mod
        from notionmemory.core.config import Config
        st = status_mod.probe(Config.load(str(paths.config_path())), verify=False)
        return bool(st["memory"]["bound"])
    except Exception:
        return False


def lock_path():
    return paths.state_dir() / "memory" / "consolidate.lock"


def log_path():
    return paths.state_dir() / "memory" / "consolidate.log"


def _create_lock(path) -> bool:
    """`O_CREAT|O_EXCL` 원자적 생성 + 자기 pid 를 내용으로 남긴다(소유자 식별 —
    `release_lock` 이 남의 락을 지우지 않게 하려면 "누가 만들었나"를 파일 자체에
    적어둬야 한다)."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def acquire_lock() -> bool:
    """mtime 이 `LOCK_STALE_SECONDS` 보다 오래된 락은(죽은 프로세스가 남긴 것으로
    간주) 지우고 한 번만 재시도한다."""
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if _create_lock(path):
        return True
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        age = 0
    if age <= LOCK_STALE_SECONDS:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return _create_lock(path)


def release_lock() -> None:
    """자기 pid 가 적힌 락만 지운다. 실행이 `LOCK_STALE_SECONDS` 를 넘겨 다른
    스폰이 이미 락을 훔친 뒤라면, 여기서 무조건 unlink 하면 그 두 번째 실행의
    락을 지워버려 상호배제가 깨진다(2차 사고). 완전한 동시실행 방지는 아니지만
    (그건 원래 stale-steal 설계의 한계) 최소한 "남의 락을 지우는" 사고는 막는다 —
    중복 발굴이 생겨도 큐/드래프트 dedup 이 흡수한다."""
    path = lock_path()
    try:
        owner = path.read_text(encoding="utf-8").strip()
    except OSError:
        return
    if owner != str(os.getpid()):
        return
    try:
        path.unlink()
    except OSError:
        pass


def file_log(msg: str) -> None:
    """`--auto` 경로는 stdout 이 없다(DEVNULL 로 스폰됨) — 상태 로그 파일에
    타임스탬프를 찍어 append 한다. 200KB 를 넘으면 뒤 100KB 만 남겨 무한정 자라지
    않게 한다(회전 라이브러리 없이 단순 tail)."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] {msg}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size > LOG_MAX_BYTES:
        try:
            data = path.read_bytes()
        except OSError:
            return
        tail = data[-_LOG_KEEP_BYTES:]
        # M7 — 바이트 단위 슬라이스라 줄 중간(과 그 안의 멀티바이트 UTF-8 문자 중간)
        # 에서 잘릴 수 있다. 첫 개행(0x0A)까지(포함)를 버려 그 뒤부터는 항상 줄
        # 경계에서 시작하게 한다 — 0x0A 는 UTF-8 연속 바이트로 절대 등장하지 않으므로
        # 이 한 번의 slice 로 줄 경계와 문자 경계를 동시에 보장한다. 개행이 아예
        # 없으면(한 줄이 keep 윈도우보다 긴 극단값) 자를 경계가 없으니 그대로 둔다.
        nl = tail.find(b"\n")
        if nl != -1:
            tail = tail[nl + 1:]
        path.write_bytes(tail)


def maybe_spawn(cli_path: str) -> bool:
    """게이트 체인을 통과하면 detached `memory consolidate --auto` 를 스폰한다.
    절대 예외를 올리지 않는다 — 훅(Task 5) 안에서 호출되므로 여기서 실패해도
    세션이 죽으면 안 된다."""
    try:
        if os.environ.get("NOTIONMEMORY_CONSOLIDATE"):
            return False
        if capture_mode() != "auto":
            return False
        if consolidate_mode() != "auto":
            return False
        if not _memory_bound():
            return False
        if not queue.list_jobs():
            return False
        if lock_path().exists():
            return False
        # M5 — PATH 상의 실제 설치 위치를 우선한다(cli_path 는 훅을 실행한 인터프리터의
        # argv[0] 이라 venv/심볼릭링크 사정에 따라 신뢰 못 할 수 있다); 못 찾으면
        # 기존처럼 cli_path 로 폴백한다.
        exe = shutil.which("notionmemory") or cli_path
        try:
            subprocess.Popen(
                [exe, "memory", "consolidate", "--auto"],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={**os.environ, "NOTIONMEMORY_CONSOLIDATE": "1"},
            )
        except Exception as exc:
            # M5 — 스폰 실패는 훅에서 아무 흔적도 안 남기면(세션 stdout 이 아니라
            # DEVNULL 이니 어차피 안 보이지만) 진단할 방법이 없다. file_log 는 이미
            # `--auto` 경로의 유일한 관측 창구다(cli.py 의 실행-중 예외 로깅과 동일
            # 규율) — 스폰 자체가 안 뜬 경우도 같은 창구에 남긴다.
            file_log(f"spawn 실패: {exc!r} (cli_path={cli_path})")
            return False
        return True
    except Exception:
        return False
