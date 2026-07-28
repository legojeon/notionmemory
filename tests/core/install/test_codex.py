"""Codex 신뢰 등록 — 키는 조립하지 않고 hooks/list 실측값만 쓴다."""
import json
import re
import threading

import pytest

from notionmemory.core.install import codex, manifest
from notionmemory.core.install.handlers import CodexTrust
from notionmemory.core.install.spec import ArtifactSpec

HOOKS_PATH = "/home/u/.codex/hooks.json"

SAMPLE = [
    {"key": f"{HOOKS_PATH}:session_start:0:0",
     "currentHash": "sha256:aaa", "trustStatus": "untrusted",
     "sourcePath": HOOKS_PATH, "source": "user",
     "command": "/bin/notionmemory hook session-start"},
    {"key": "/home/u/.codex/hooks.json:stop:1:0",
     "currentHash": "sha256:bbb", "trustStatus": "untrusted",
     "sourcePath": HOOKS_PATH, "source": "user",
     "command": "/other/tool.sh"},
]


def test_our_hooks_filters_by_marker_and_source_path():
    # 마커는 실제 호출부(runner)와 같은 것을 넘긴다 — 좁혀서 부르면 레거시 마커
    # 쪽 판정에 구멍이 있어도 테스트가 못 본다(이 파일의 원래 사각지대였다).
    ours = codex.our_hooks(SAMPLE, HOOKS_PATH, manifest.HOOK_MARKERS)
    assert [h["currentHash"] for h in ours] == ["sha256:aaa"]


def test_our_hooks_ignores_other_source_paths():
    foreign = dict(SAMPLE[0], sourcePath="/somewhere/else/hooks.json")
    assert codex.our_hooks([foreign], HOOKS_PATH, manifest.HOOK_MARKERS) == []


# ---------------------------------------------------------------------------
# 최종 리뷰 Critical — our_hooks 의 `marker in command` 부분일치. 다른 곳에서
# 세 번 고친 것과 같은 버그지만 여기서는 결과가 "남의 훅에 Codex 신뢰를 부여"다:
# 우리가 소유하지 않은 명령에 trusted_hash 를 써서 Codex 의 보안 관문을 대신
# 통과시킨다 — CLI 는 "우리가 설치한 항목만" 이라고 출력하면서.
# ---------------------------------------------------------------------------

FOREIGN_LEGACY_LOOKALIKE = {
    "key": f"{HOOKS_PATH}:session_start:2:0", "currentHash": "sha256:ccc",
    "trustStatus": "untrusted", "sourcePath": HOOKS_PATH, "source": "user",
    "command": "/Users/bob/backups/old_memory_hooks_project/run.sh"}

OUR_LEGACY_SCRIPT = {
    "key": f"{HOOKS_PATH}:session_start:3:0", "currentHash": "sha256:ddd",
    "trustStatus": "untrusted", "sourcePath": HOOKS_PATH, "source": "user",
    "command": "/old/venv/bin/python /old/scripts/memory_hooks/session_start.py"}


def test_our_hooks_does_not_claim_foreign_command_containing_marker():
    """`memory_hooks` 가 남의 경로 조각으로 우연히 든 사용자 자신의 훅."""
    assert codex.our_hooks([FOREIGN_LEGACY_LOOKALIKE], HOOKS_PATH,
                           manifest.HOOK_MARKERS) == []


def test_our_hooks_recognizes_real_legacy_hook_script():
    """반대로 진짜 구버전 훅 스크립트는 여전히 우리 것으로 인식해야 한다."""
    ours = codex.our_hooks([OUR_LEGACY_SCRIPT], HOOKS_PATH, manifest.HOOK_MARKERS)
    assert [h["currentHash"] for h in ours] == ["sha256:ddd"]


def test_install_does_not_grant_trust_to_foreign_hook(tmp_path, monkeypatch):
    """재현 시나리오: 같은 hooks.json 에 사용자 자신의 항목이 있고 그 command 에
    `memory_hooks` 가 경로 조각으로 들어 있다 — 신뢰 기록이 남으면 안 된다."""
    from notionmemory.core.install import runner
    hooks_path = str(tmp_path / ".codex" / "hooks.json")
    foreign = dict(FOREIGN_LEGACY_LOOKALIKE, sourcePath=hooks_path,
                   key=f"{hooks_path}:session_start:2:0")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(runner, "resolve_cli", lambda: "/fake/bin/notionmemory")
    monkeypatch.setattr(codex, "available", lambda: True)
    monkeypatch.setattr(codex, "hooks_list", lambda cwd="": [foreign])

    runner.install(["codex"], trust_codex=True)
    config = tmp_path / ".codex" / "config.toml"
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    assert "sha256:ccc" not in text
    assert "hooks.state" not in text


def test_codex_trust_writes_measured_key_and_hash(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('model = "gpt-5.6-terra"\n', encoding="utf-8")
    spec = ArtifactSpec(id="codex.trust", owner="_core", handler="codex_trust",
                        target="codex", path=config,
                        payload={"entries": [{"key": f"{HOOKS_PATH}:session_start:0:0",
                                              "currentHash": "sha256:aaa"}]},
                        markers=(HOOKS_PATH,))
    assert CodexTrust().install(spec) is True
    text = config.read_text(encoding="utf-8")
    assert f'[hooks.state."{HOOKS_PATH}:session_start:0:0"]' in text
    assert 'trusted_hash = "sha256:aaa"' in text
    assert 'model = "gpt-5.6-terra"' in text        # 기존 설정 보존
    assert CodexTrust().install(spec) is False      # 멱등


def test_codex_trust_remove_strips_only_our_entries(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        'model = "x"\n\n'
        f'[hooks.state."{HOOKS_PATH}:session_start:0:0"]\n'
        'trusted_hash = "sha256:aaa"\n\n'
        '[hooks.state."/other/hooks.json:stop:0:0"]\n'
        'trusted_hash = "sha256:zzz"\n', encoding="utf-8")
    spec = ArtifactSpec(id="codex.trust", owner="_core", handler="codex_trust",
                        target="codex", path=config, payload={"entries": []},
                        markers=(HOOKS_PATH,))
    assert CodexTrust().detect(spec) is True
    assert CodexTrust().remove(spec) is True
    text = config.read_text(encoding="utf-8")
    assert HOOKS_PATH not in text
    assert "/other/hooks.json" in text              # 남의 신뢰 항목 보존
    assert 'model = "x"' in text


def test_install_skips_codex_when_binary_absent(tmp_path, monkeypatch):
    from notionmemory.core.install import runner
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setattr(runner, "resolve_cli", lambda: "/fake/bin/notionmemory")
    monkeypatch.setattr(codex, "available", lambda: False)
    lines = runner.install(["codex"], trust_codex=True)
    assert any("codex" in ln and "skipping" in ln for ln in lines)


def test_install_without_consent_does_not_write_trust(tmp_path, monkeypatch):
    """동의 없이는 신뢰를 기록하지 않는다 — 훅 파일까지만 쓴다."""
    from notionmemory.core.install import runner
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setattr(runner, "resolve_cli", lambda: "/fake/bin/notionmemory")
    monkeypatch.setattr(codex, "available", lambda: True)
    monkeypatch.setattr(codex, "hooks_list", lambda cwd="": SAMPLE)
    runner.install(["codex"], trust_codex=False)
    config = tmp_path / ".codex" / "config.toml"
    assert not config.exists() or "hooks.state" not in config.read_text(encoding="utf-8")
    assert (tmp_path / ".codex" / "hooks.json").is_file()


# ---------------------------------------------------------------------------
# 리뷰 Critical #1 — 부분문자열 일치로 `hooks.json.bak` 같은 남의 키를 우리 것으로
# 오판해 지우던 버그. 구조적 비교(정확히 marker 이거나 `marker + ":"` 접두)로 고침.
# ---------------------------------------------------------------------------

def test_codex_trust_does_not_touch_prefix_collision_key(tmp_path):
    """우리 hooks.json 경로가 접두사인 남의 키(`hooks.json.bak:...`)는 install/remove
    양쪽에서 손대지 않는다."""
    config = tmp_path / "config.toml"
    foreign_key = f"{HOOKS_PATH}.bak:session_start:0:0"
    config.write_text(
        'model = "x"\n\n'
        f'[hooks.state."{foreign_key}"]\n'
        'trusted_hash = "sha256:zzz"\n', encoding="utf-8")
    spec = ArtifactSpec(id="codex.trust", owner="_core", handler="codex_trust",
                        target="codex", path=config,
                        payload={"entries": [{"key": f"{HOOKS_PATH}:session_start:0:0",
                                              "currentHash": "sha256:aaa"}]},
                        markers=(HOOKS_PATH,))
    assert CodexTrust().install(spec) is True
    text = config.read_text(encoding="utf-8")
    assert f'[hooks.state."{foreign_key}"]' in text
    assert 'trusted_hash = "sha256:zzz"' in text

    remove_spec = ArtifactSpec(id="codex.trust", owner="_core", handler="codex_trust",
                               target="codex", path=config, payload={"entries": []},
                               markers=(HOOKS_PATH,))
    assert CodexTrust().remove(remove_spec) is True
    text = config.read_text(encoding="utf-8")
    assert f'[hooks.state."{foreign_key}"]' in text          # 접두사 충돌 항목은 생존
    assert 'trusted_hash = "sha256:zzz"' in text
    assert f'[hooks.state."{HOOKS_PATH}:session_start:0:0"]' not in text  # 우리 것만 제거


# ---------------------------------------------------------------------------
# 리뷰 Important #2 — key/currentHash 를 TOML 로 이스케이프 없이 그대로 splice
# 하면 따옴표/백슬래시가 낀 값이 config.toml 전체를 깨뜨린다. 개행/제어문자는
# 아예 표현이 불가능하므로 걸러서 쓰지 않는다.
# ---------------------------------------------------------------------------

def test_codex_trust_key_with_quote_round_trips(tmp_path):
    config = tmp_path / "config.toml"
    key = f'{HOOKS_PATH}:se"ssion_start:0:0'
    spec = ArtifactSpec(id="codex.trust", owner="_core", handler="codex_trust",
                        target="codex", path=config,
                        payload={"entries": [{"key": key, "currentHash": 'sha256:a"aa'}]},
                        markers=(HOOKS_PATH,))
    assert CodexTrust().install(spec) is True
    text = config.read_text(encoding="utf-8")
    assert 'se\\"ssion_start' in text            # 따옴표가 이스케이프돼 저장됨
    assert 'sha256:a\\"aa' in text
    assert CodexTrust().detect(spec) is True     # 판정도 같은 이스케이프로 일치
    assert CodexTrust().remove(spec) is True
    assert HOOKS_PATH not in config.read_text(encoding="utf-8")


def test_codex_trust_rejects_key_with_newline(tmp_path):
    """개행이 든 key 는 TOML 로 안전히 못 담으므로 쓰지 않고 건너뛴다."""
    config = tmp_path / "config.toml"
    bad_key = f"{HOOKS_PATH}:session_start:0:0\nrogue = 1"
    spec = ArtifactSpec(id="codex.trust", owner="_core", handler="codex_trust",
                        target="codex", path=config,
                        payload={"entries": [{"key": bad_key, "currentHash": "sha256:aaa"}]},
                        markers=(HOOKS_PATH,))
    assert CodexTrust().install(spec) is False
    assert not config.exists()


def test_codex_trust_rejects_hash_with_control_char(tmp_path):
    config = tmp_path / "config.toml"
    spec = ArtifactSpec(id="codex.trust", owner="_core", handler="codex_trust",
                        target="codex", path=config,
                        payload={"entries": [{"key": f"{HOOKS_PATH}:session_start:0:0",
                                              "currentHash": "sha256:a\x00aa"}]},
                        markers=(HOOKS_PATH,))
    assert CodexTrust().install(spec) is False
    assert not config.exists()


def test_split_safe_separates_control_chars_from_clean_entries():
    entries = [
        {"key": "ok", "currentHash": "sha256:aaa"},
        {"key": "bad\n", "currentHash": "sha256:bbb"},
        {"key": "ok2", "currentHash": "bad\x00hash"},
    ]
    safe, unsafe = CodexTrust().split_safe(entries)
    assert [e["key"] for e in safe] == ["ok"]
    assert len(unsafe) == 2


# ---------------------------------------------------------------------------
# 리뷰 Important #4 — CRLF 파일을 통째로 LF 로 바꿔치기하던 버그. 파일이 쓰던
# 줄바꿈을 그대로 유지해야 하고, 기존 블록이 없을 때도 딴 줄 \r 가 남으면 안 된다.
# ---------------------------------------------------------------------------

def test_codex_trust_preserves_crlf_line_endings(tmp_path):
    config = tmp_path / "config.toml"
    config.write_bytes(b'model = "x"\r\n\r\n[other]\r\nkey = "v"\r\n')
    spec = ArtifactSpec(id="codex.trust", owner="_core", handler="codex_trust",
                        target="codex", path=config,
                        payload={"entries": [{"key": f"{HOOKS_PATH}:session_start:0:0",
                                              "currentHash": "sha256:aaa"}]},
                        markers=(HOOKS_PATH,))
    assert CodexTrust().install(spec) is True
    raw = config.read_bytes()
    text = raw.decode("utf-8")
    assert b'model = "x"\r\n' in raw
    assert b'[other]\r\n' in raw
    # 새로 쓴 블록도 CRLF — 그리고 문서 전체에 짝 없는 \r 나 \n 이 없다(순수 CRLF).
    assert not re.search(r"\r(?!\n)", text)
    assert not re.search(r"(?<!\r)\n", text)


def test_codex_trust_crlf_no_dangling_cr_without_prior_block(tmp_path):
    """CRLF 파일에 우리 블록이 아직 없을 때도 추가된 블록 앞에 짝 없는 \\r 가
    남으면 안 된다(리뷰가 지적한 서브버그)."""
    config = tmp_path / "config.toml"
    config.write_bytes(b'model = "x"\r\n')
    spec = ArtifactSpec(id="codex.trust", owner="_core", handler="codex_trust",
                        target="codex", path=config,
                        payload={"entries": [{"key": f"{HOOKS_PATH}:session_start:0:0",
                                              "currentHash": "sha256:aaa"}]},
                        markers=(HOOKS_PATH,))
    assert CodexTrust().install(spec) is True
    text = config.read_bytes().decode("utf-8")
    assert not re.search(r"\r(?!\n)", text)
    assert not re.search(r"(?<!\r)\n", text)


# ---------------------------------------------------------------------------
# 리뷰 Important #3 (원안) — hooks_list() 는 app-server 가 준 모양이 이상해도
# (비-dict, 누락된 id==2, JSON 이 아닌 줄) 절대 raise 하지 않고 빈 리스트로
# 낮아져야 한다.
#
# 리뷰 Critical (2026-07-21 실기 재현) — `subprocess.run(input=...)` 은 stdin 을
# 쓰자마자 닫아버려서 app-server 가 EOF 로 보고 응답 없이 종료했다(0.1초,
# returncode 0, stdout 0줄) — 즉 실제 바이너리에서 hooks_list() 는 항상 빈
# 리스트를 돌려주는 조용한 실패였고, 기존 테스트는 hooks_list 자체를
# monkeypatch 했으므로 이 버그를 절대 잡을 수 없었다. Popen 으로 stdin 을
# 열어둔 채 응답을 기다리도록 고쳤고, 아래 테스트들은 실제 subprocess.run 이
# 아니라 subprocess.Popen 을 몽키패치해 이 경로를 검증한다.
#
# 진짜 codex 바이너리는 어떤 테스트도 호출하지 않는다.
# ---------------------------------------------------------------------------

class _FakeStdin:
    """proc.stdin 스탠드인 — write/flush/close 만 있으면 된다."""

    def __init__(self):
        self.written = []
        self.closed = False

    def write(self, s: str) -> None:
        self.written.append(s)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _BlockingStdout:
    """id==2 응답이 절대 오지 않는 상황(hang)을 흉내낸다 — 데드라인 테스트용.
    daemon 리더 스레드에서만 도니 프로세스 종료를 막지 않는다."""

    def __iter__(self):
        return self

    def __next__(self):
        threading.Event().wait()          # 영원히 블록
        raise StopIteration                # pragma: no cover — 도달 안 함


class _FakeProc:
    """subprocess.Popen 스탠드인. `lines` 를 스트리밍하거나(정상/EOF 조기 종료)
    `block_forever=True` 로 영원히 블록(데드라인 경로)한다."""

    def __init__(self, lines: list[str] | None = None, block_forever: bool = False,
                spawn_ok: bool = True):
        self.stdin = _FakeStdin()
        self._lines = lines or []
        self._block_forever = block_forever
        self.terminated = False
        self.killed = False
        self.waited = False
        self._alive = True

    @property
    def stdout(self):
        if self._block_forever:
            return _BlockingStdout()
        return iter(self._lines)

    def poll(self):
        return None if self._alive else 0

    def terminate(self) -> None:
        self.terminated = True
        self._alive = False

    def kill(self) -> None:
        self.killed = True
        self._alive = False

    def wait(self, timeout: float | None = None) -> int:
        self.waited = True
        return 0


def test_hooks_list_parses_well_formed_response_after_unrelated_lines(monkeypatch):
    init_resp = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n"
    garbage = "not json at all\n"
    list_resp = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"data": [
        {"hooks": [{"key": "k1", "currentHash": "h1"}]},
    ]}}) + "\n"
    proc = _FakeProc(lines=[init_resp, garbage, list_resp])
    monkeypatch.setattr(codex.subprocess, "Popen", lambda *a, **k: proc)
    assert codex.hooks_list(cwd="/x") == [{"key": "k1", "currentHash": "h1"}]
    assert proc.terminated is True                 # 성공해도 자식은 정리한다


def test_hooks_list_ignores_non_dict_shapes_within_response(monkeypatch):
    """id==2 응답 하나 안에서 data/group/hook 각 단계가 기대와 다른 모양이어도
    (raise 하지 않고) 그 조각만 건너뛰고 유효한 항목만 모은다.

    노이즈 줄(bare scalar/array)도 실제 프로토콜에는 없어야 정상이지만, id==2 가
    아닌 어떤 JSON 줄이 와도 무시하고 계속 읽는다는 것까지 함께 확인한다. id==2
    는 JSON-RPC 상 요청 하나에 응답 하나이므로 실측 응답은 항상 단일 메시지다 —
    그래서 이 테스트는 (예전처럼 id==2 메시지를 여러 개 보내는 대신) 하나의
    id==2 메시지 안에 여러 모양의 data 원소를 함께 담는다.
    """
    scalar_line = json.dumps(42) + "\n"            # bare scalar — id==2 아님, 무시
    array_line = json.dumps([1, 2, 3]) + "\n"      # bare array — id==2 아님, 무시
    resp = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"data": [
        1, 2,                                      # data 원소가 dict 아님 — 건너뜀
        {"hooks": "oops"},                         # hooks 가 list 아님 — 건너뜀
        {"hooks": [1, "x"]},                       # hook 원소가 dict 아님 — 건너뜀
        {"hooks": [{"key": "ok"}]},                # 유효
    ]}}) + "\n"
    proc = _FakeProc(lines=[scalar_line, array_line, resp])
    monkeypatch.setattr(codex.subprocess, "Popen", lambda *a, **k: proc)
    assert codex.hooks_list() == [{"key": "ok"}]
    assert proc.terminated is True


def test_hooks_list_returns_empty_when_id2_result_shape_is_wrong(monkeypatch):
    """id==2 메시지 자체는 왔지만 result/data 가 통째로 기대와 다른 모양이면
    (raise 하지 않고) 그 응답을 빈 리스트로 낮춘다 — 더 안 읽고 바로 반환한다,
    JSON-RPC 상 id==2 응답은 하나뿐이므로 다음 줄을 더 기다릴 이유가 없다."""
    resp = json.dumps({"jsonrpc": "2.0", "id": 2, "result": "oops"}) + "\n"
    proc = _FakeProc(lines=[resp])
    monkeypatch.setattr(codex.subprocess, "Popen", lambda *a, **k: proc)
    assert codex.hooks_list() == []
    assert proc.terminated is True


def test_hooks_list_returns_empty_when_id2_never_arrives(monkeypatch):
    """데드라인 경로 — id==2 응답이 영영 안 오면 타임아웃 후 빈 리스트를 돌려주고
    자식을 정리한다."""
    monkeypatch.setattr(codex, "TIMEOUT_S", 0.05)
    proc = _FakeProc(block_forever=True)
    monkeypatch.setattr(codex.subprocess, "Popen", lambda *a, **k: proc)
    assert codex.hooks_list() == []
    assert proc.terminated is True


def test_hooks_list_returns_empty_when_stdout_closes_early(monkeypatch):
    """id==2 가 오기 전에 stdout 이 닫히면(EOF) 타임아웃까지 기다리지 않고 즉시
    빈 리스트를 돌려주고 자식을 정리한다."""
    only_init = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n"
    proc = _FakeProc(lines=[only_init])          # 반복자가 id==2 없이 그냥 끝남
    monkeypatch.setattr(codex.subprocess, "Popen", lambda *a, **k: proc)
    assert codex.hooks_list() == []
    assert proc.terminated is True


def test_hooks_list_returns_empty_on_spawn_failure(monkeypatch):
    """codex 바이너리가 없거나 spawn 이 실패해도 raise 하지 않는다."""
    def _raise(*a, **k):
        raise FileNotFoundError("codex not found")
    monkeypatch.setattr(codex.subprocess, "Popen", _raise)
    assert codex.hooks_list() == []
