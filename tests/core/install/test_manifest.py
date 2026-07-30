"""HOOK_EVENTS — Stop 훅 등록 (Second Brain v2 phase 2a task 3).

Stop 은 consolidation 큐잉 전용(비블로킹)이라 SessionStart/PreCompact 와 달리
컨텍스트 주입이 필요 없다 — 그래서 이전에는 등록하지 않았지만(주석 참조), 이제는
enqueue-only 훅이 생겼으므로 등록한다. teardown 커버는 매니페스트를 통해서만
이뤄진다(HOOK_MARKERS) — `tests/test_artifact_contract.py`가 이를 강제한다.
"""
from notionmemory.core.install import manifest


def test_manifest_registers_stop_hook():
    ev = manifest.HOOK_EVENTS("/usr/bin/notionmemory", "claude")
    assert "Stop" in ev
    assert "session-stop" in ev["Stop"][0]["hooks"][0]["command"]


def test_stop_hook_command_gets_harness_flag_for_codex():
    ev = manifest.HOOK_EVENTS("/usr/bin/notionmemory", "codex")
    cmd = ev["Stop"][0]["hooks"][0]["command"]
    assert cmd == "/usr/bin/notionmemory hook session-stop --harness codex"


def test_stop_hook_command_omits_harness_flag_for_claude():
    ev = manifest.HOOK_EVENTS("/usr/bin/notionmemory", "claude")
    cmd = ev["Stop"][0]["hooks"][0]["command"]
    assert cmd == "/usr/bin/notionmemory hook session-stop"


def test_stop_hook_is_teardown_covered_by_hook_markers():
    """`build()`의 hooks ArtifactSpec 은 HOOK_MARKERS 를 쓴다 — Stop 이벤트를
    포함해도 별도 마커 없이 기존 훅 마커로 teardown 이 걷어낸다."""
    specs = manifest.build(["claude"], "/x/notionmemory")
    hooks_spec = next(s for s in specs if s.id == "claude.hooks")
    assert "Stop" in hooks_spec.payload["events"]
    assert hooks_spec.markers == manifest.HOOK_MARKERS
