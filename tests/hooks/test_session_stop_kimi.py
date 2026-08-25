import json
from notionmemory.hooks import session_stop


def test_kimi_stop_resolves_wire_and_enqueues(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr("notionmemory.hooks.session_stop.capture_mode", lambda: "auto")
    monkeypatch.setattr("notionmemory.hooks.common.consolidate_guard", lambda: False)
    monkeypatch.setattr("notionmemory.hooks.session_stop.consolidate_guard", lambda: False)
    monkeypatch.setattr("notionmemory.skills.memory.transcripts.find_kimi_wire",
                        lambda sid, cwd="": f"/wire/{sid}.jsonl")

    def fake_enqueue(project, cwd, ts, session=None):
        captured["session"] = session
    monkeypatch.setattr("notionmemory.skills.memory.consolidation_queue.enqueue",
                        fake_enqueue)
    monkeypatch.setattr("sys.stdin", type("S", (), {
        "read": staticmethod(lambda: json.dumps({"session_id": "s1", "cwd": str(tmp_path)}))})())

    rc = session_stop.main(harness="kimi")
    assert rc == 0
    assert captured["session"]["harness"] == "kimi"
    assert captured["session"]["transcript_path"] == "/wire/s1.jsonl"
