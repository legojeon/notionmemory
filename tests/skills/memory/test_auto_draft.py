"""Second Brain v2 phase 2a — CLI 캡처 특권: `--auto` 는 Draft, 수동은 Active.
Task 5 fix round 1: Strength도 같은 특권을 반영한다 — 수동 저장(사용자가 명시적으로
"기억해"라고 한 것)은 정의상 고신호이므로 8(SessionStart top_memories 게이트 ≥8을
바로 넘김), --auto 초안은 7(consolidation이 실제 값을 매길 때까지의 플레이스홀더 —
Draft라 애초에 top_memories 대상이 아니다). 이게 없으면 수동 저장이 Active-7로
영구 고정돼 SessionStart에서 다시는 안 보이는 회귀가 난다(consolidation은 Draft만
승격하고 Active 행은 건드리지 않으며, Strength를 나중에 매길 CLI도 없다).

`_cmd_remember` 가 `MemoryStore.remember` 를 부를 때 넘기는 `status`/`strength`
kwarg 만 확인한다(계약 테스트) — remember 를 monkeypatch 해 실 Notion 호출은 없다.
"""
from __future__ import annotations

from notionmemory import cli


def run_cli(argv):
    return cli.main(argv)


def _cfg(tmp_path, body: str = "skills: {}\n"):
    p = tmp_path / "config.yaml"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_auto_capture_writes_draft(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    seen = {}
    monkeypatch.setattr(
        "notionmemory.skills.memory.store.MemoryStore.remember",
        lambda self, content, **kw: seen.update(kw) or {"mem_id": "mem_x", "concepts": []})
    rc = run_cli(["remember", "x", "--type", "fact", "--concepts", "a", "--auto",
                  "--config", _cfg(tmp_path)])
    assert rc == 0
    assert seen["status"] == "Draft"
    assert seen["strength"] == 7  # 플레이스홀더 — consolidation이 실제 값을 매길 때까지


def test_manual_capture_writes_active(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "NotionSession", lambda **kw: object())
    seen = {}
    monkeypatch.setattr(
        "notionmemory.skills.memory.store.MemoryStore.remember",
        lambda self, content, **kw: seen.update(kw) or {"mem_id": "mem_x", "concepts": []})
    rc = run_cli(["remember", "x", "--type", "fact", "--concepts", "a",
                  "--config", _cfg(tmp_path)])
    assert rc == 0
    assert seen["status"] == "Active"
    assert seen["strength"] == 8  # 명시적 저장 = 고신호 — SessionStart 게이트(≥8)를 바로 넘김
