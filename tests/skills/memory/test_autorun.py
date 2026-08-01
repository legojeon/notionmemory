"""autorun — 훅에서 detached 로 `memory consolidate --auto` 를 스폰하는 게이트 체인.

게이트 순서(전부 통과해야 스폰): 재귀 env 미설정 → capture_mode==auto →
consolidate_mode==auto → memory 바인딩됨(C1, network 0 로컬 프로브) → 큐 비어있지
않음 → 락 파일 미존재(pre-check 만, 실제 획득/해제는 `--auto` 실행 자신이 한다 —
두 스폰이 떠도 한쪽만 진행)."""
from __future__ import annotations

import os

import pytest

from notionmemory.skills.memory import autorun


def test_maybe_spawn_requires_all_gates(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(autorun.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(autorun, "consolidate_mode", lambda: "auto")
    monkeypatch.setattr(autorun, "capture_mode", lambda: "auto")
    monkeypatch.setattr(autorun, "_memory_bound", lambda: True)
    monkeypatch.setattr(autorun.shutil, "which", lambda name: None)
    monkeypatch.setattr(autorun.queue, "list_jobs", lambda: [{"id": "j"}])
    assert autorun.maybe_spawn("notionmemory") is True
    (a, k) = calls[0]
    assert a[0] == ["notionmemory", "memory", "consolidate", "--auto"]
    assert k["start_new_session"] is True
    assert k["env"]["NOTIONMEMORY_CONSOLIDATE"] == "1"


def test_maybe_spawn_prefers_which_notionmemory_over_cli_path(tmp_path, monkeypatch):
    """M5 — PATH 상에서 찾은 실제 설치 위치를 argv[0] 보다 우선한다."""
    calls = []
    monkeypatch.setattr(autorun.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(autorun, "consolidate_mode", lambda: "auto")
    monkeypatch.setattr(autorun, "capture_mode", lambda: "auto")
    monkeypatch.setattr(autorun, "_memory_bound", lambda: True)
    monkeypatch.setattr(autorun.shutil, "which", lambda name: "/usr/local/bin/notionmemory")
    monkeypatch.setattr(autorun.queue, "list_jobs", lambda: [{"id": "j"}])
    assert autorun.maybe_spawn("/some/argv0/path") is True
    (a, _k) = calls[0]
    assert a[0][0] == "/usr/local/bin/notionmemory"


def test_maybe_spawn_noop_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(autorun.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("must not spawn"))
    monkeypatch.setattr(autorun, "_memory_bound", lambda: True)
    monkeypatch.setattr(autorun.queue, "list_jobs", lambda: [])
    assert autorun.maybe_spawn("nm") is False                      # 큐 빔
    monkeypatch.setattr(autorun.queue, "list_jobs", lambda: [{"id": "j"}])
    monkeypatch.setattr(autorun, "consolidate_mode", lambda: "nudge")
    assert autorun.maybe_spawn("nm") is False                      # nudge 모드
    monkeypatch.setattr(autorun, "consolidate_mode", lambda: "auto")
    monkeypatch.setattr(autorun, "capture_mode", lambda: "off")
    assert autorun.maybe_spawn("nm") is False                      # capture off
    monkeypatch.setattr(autorun, "capture_mode", lambda: "auto")
    monkeypatch.setenv("NOTIONMEMORY_CONSOLIDATE", "1")
    assert autorun.maybe_spawn("nm") is False                      # 재귀 가드


# ── C1: memory 미바인딩이면 스폰하지 않는다(고아 Second Brain DB 생성 방지) ──

def test_maybe_spawn_returns_false_when_memory_unbound(tmp_path, monkeypatch):
    monkeypatch.setattr(autorun.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("must not spawn — memory unbound"))
    monkeypatch.setattr(autorun, "consolidate_mode", lambda: "auto")
    monkeypatch.setattr(autorun, "capture_mode", lambda: "auto")
    monkeypatch.setattr(autorun.queue, "list_jobs", lambda: [{"id": "j"}])
    monkeypatch.setattr(autorun, "_memory_bound", lambda: False)
    assert autorun.maybe_spawn("nm") is False


def test_memory_bound_uses_local_probe_and_swallows_errors(tmp_path, monkeypatch):
    """`_memory_bound()` 자체는 `status.probe(verify=False)`(network 0)만 본다 —
    Config.load/probe 어느 쪽이 던져도 False 로 fail-closed."""
    monkeypatch.setattr(autorun.paths, "config_path", lambda: tmp_path / "nope.yaml")
    assert autorun._memory_bound() is False    # 존재하지 않는 config → 빈 Config → 미바인딩

    from notionmemory.core import status as status_mod

    def boom(config, verify=True):
        raise RuntimeError("boom")

    monkeypatch.setattr(status_mod, "probe", boom)
    assert autorun._memory_bound() is False

    def bound_true(config, verify=True):
        return {"memory": {"bound": True}}

    monkeypatch.setattr(status_mod, "probe", bound_true)
    assert autorun._memory_bound() is True


def test_lock_exclusive_and_stale_steal(tmp_path, monkeypatch):
    monkeypatch.setattr(autorun.paths, "state_dir", lambda: tmp_path)
    assert autorun.acquire_lock() is True
    assert autorun.acquire_lock() is False                         # 경합 패배
    old = autorun.lock_path()
    os.utime(old, (1, 1))                                          # stale 로 만들기
    assert autorun.acquire_lock() is True                          # 훔침
    autorun.release_lock()


def test_release_removes_own_lock(tmp_path, monkeypatch):
    """정상 경로: acquire → release 는 여전히 락 파일을 지운다."""
    monkeypatch.setattr(autorun.paths, "state_dir", lambda: tmp_path)
    assert autorun.acquire_lock() is True
    autorun.release_lock()
    assert not autorun.lock_path().exists()


def test_release_after_stale_steal_does_not_remove_new_owners_lock(tmp_path, monkeypatch):
    """fix round 1 finding 2: 락에 소유 pid 가 없으면, 오래 걸린 첫 실행이
    LOCK_STALE_SECONDS 를 넘겨 두 번째 스폰이 훔친 뒤 첫 실행의 finally-release 가
    두 번째 실행의 락을 지워 상호배제가 깨진다. pid 소유권 체크로, 자기 락이
    아니면 release_lock 이 no-op 이어야 한다."""
    monkeypatch.setattr(autorun.paths, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(autorun.os, "getpid", lambda: 111)
    assert autorun.acquire_lock() is True                          # "프로세스 1" 이 획득
    os.utime(autorun.lock_path(), (1, 1))                          # stale 로 만들기
    monkeypatch.setattr(autorun.os, "getpid", lambda: 222)
    assert autorun.acquire_lock() is True                          # "프로세스 2" 가 훔침
    monkeypatch.setattr(autorun.os, "getpid", lambda: 111)
    autorun.release_lock()                                         # 프로세스 1 의 뒤늦은 해제
    assert autorun.lock_path().exists()                            # 프로세스 2 의 락은 살아남음
    monkeypatch.setattr(autorun.os, "getpid", lambda: 222)
    autorun.release_lock()                                         # 진짜 소유자가 해제
    assert not autorun.lock_path().exists()


def test_file_log_truncates(tmp_path, monkeypatch):
    monkeypatch.setattr(autorun.paths, "state_dir", lambda: tmp_path)
    for _ in range(3000):
        autorun.file_log("x" * 100)
    assert autorun.log_path().stat().st_size <= autorun.LOG_MAX_BYTES


def test_file_log_truncation_keeps_decodable_utf8_on_line_boundary(tmp_path, monkeypatch):
    """M7 — 바이트 단위 tail 슬라이스가 멀티바이트 UTF-8 문자나 줄 중간에서 잘리면
    안 된다. 한글(멀티바이트) 메시지를 로그 상한을 넘도록 반복해서 쓴 뒤, 최종
    파일이 통째로 유효한 UTF-8 로 디코딩되고 첫 줄이 `[`(타임스탬프 시작)로
    시작해야 한다(줄 중간에서 시작하면 안 됨)."""
    monkeypatch.setattr(autorun.paths, "state_dir", lambda: tmp_path)
    for _ in range(3000):
        autorun.file_log("한글 로그 메시지 " * 10)
    data = autorun.log_path().read_bytes()
    text = data.decode("utf-8")  # 던지면 실패 — 문자 경계가 깨진 것
    assert text.startswith("[")  # 줄 경계에서 시작(타임스탬프 대괄호)


def test_maybe_spawn_logs_and_returns_false_on_popen_failure(tmp_path, monkeypatch):
    """M5 — Popen 이 던지면(예: 실행파일 없음) file_log 에 원인이 남고 False."""
    monkeypatch.setattr(autorun.paths, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(autorun, "consolidate_mode", lambda: "auto")
    monkeypatch.setattr(autorun, "capture_mode", lambda: "auto")
    monkeypatch.setattr(autorun, "_memory_bound", lambda: True)
    monkeypatch.setattr(autorun.queue, "list_jobs", lambda: [{"id": "j"}])
    monkeypatch.setattr(autorun.shutil, "which", lambda name: None)

    def boom(*a, **k):
        raise OSError("no such file")

    monkeypatch.setattr(autorun.subprocess, "Popen", boom)

    assert autorun.maybe_spawn("/path/to/notionmemory") is False
    log_text = autorun.log_path().read_text(encoding="utf-8")
    assert "spawn 실패" in log_text
    assert "no such file" in log_text
