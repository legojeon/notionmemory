import json
from notionmemory.skills.memory import transcripts as T

WIRE_LINES = [
    {"type": "metadata", "protocol_version": "1.4", "created_at": 1712345678000},
    {"type": "turn.prompt", "origin": {"kind": "user"},
     "input": [{"type": "text", "text": "fix the login bug"}], "time": 1712345678.1},
    {"type": "context.append_message",
     "message": {"role": "user", "content": [{"type": "text", "text": "fix the login bug"}]},
     "time": 1712345678.2},
    # A real kimi-code (0.40.1) wire streams the assistant reply as loop events,
    # NOT an append_message(role=assistant). Think parts are dropped; consecutive
    # text parts within a step join into one [ASSISTANT] line.
    {"type": "context.append_loop_event",
     "event": {"type": "step.begin", "step": 1}, "time": 1712345678.5},
    {"type": "context.append_loop_event",
     "event": {"type": "content.part", "part": {"type": "think", "think": "secret reasoning"}},
     "time": 1712345678.6},
    {"type": "context.append_loop_event",
     "event": {"type": "content.part", "part": {"type": "text", "text": "Here is "}},
     "time": 1712345678.7},
    {"type": "context.append_loop_event",
     "event": {"type": "content.part", "part": {"type": "text", "text": "the fix."}},
     "time": 1712345678.8},
    {"type": "context.append_loop_event",
     "event": {"type": "step.end", "step": 1, "finishReason": "end_turn"},
     "time": 1712345679.0},
    {"type": "llm.request", "time": 1712345679.1},  # observability — ignored
]


def _write_wire(tmp_path):
    p = tmp_path / "wire.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in WIRE_LINES) + "\n", encoding="utf-8")
    return p


def test_parse_kimi_extracts_user_and_assistant(tmp_path):
    p = _write_wire(tmp_path)
    text, consumed = T.parse_kimi(str(p))
    assert "[USER] fix the login bug" in text
    assert "[ASSISTANT] Here is the fix." in text
    assert "secret reasoning" not in text        # think blocks excluded
    assert "llm.request" not in text
    assert consumed == p.stat().st_size


def test_parse_kimi_joins_streamed_text_parts(tmp_path):
    # The two "Here is " + "the fix." content.part texts must become ONE line,
    # not two separate [ASSISTANT] entries.
    p = _write_wire(tmp_path)
    text, _ = T.parse_kimi(str(p))
    assert text.count("[ASSISTANT]") == 1


def test_parse_kimi_assistant_append_message_fallback(tmp_path):
    # Defensive fallback: if a build ever emits role=assistant append_message,
    # we still capture it.
    lines = [
        {"type": "turn.prompt", "origin": {"kind": "user"},
         "input": [{"type": "text", "text": "hi"}]},
        {"type": "context.append_message",
         "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "legacy reply"}]}},
    ]
    p = tmp_path / "wire.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    text, _ = T.parse_kimi(str(p))
    assert "[ASSISTANT] legacy reply" in text


def test_parse_kimi_deduplicates_prompt_source(tmp_path):
    # user text appears in both turn.prompt and a role:user append_message.
    # We take turn.prompt(origin.kind==user) for prompts; the role:user
    # append_message must NOT double-emit.
    p = _write_wire(tmp_path)
    text, _ = T.parse_kimi(str(p))
    assert text.count("[USER] fix the login bug") == 1


def test_find_kimi_wire_via_index(tmp_path, monkeypatch):
    home = tmp_path / ".kimi-code"
    sess_dir = home / "sessions" / "wd_proj_abc123" / "sess-1"
    (sess_dir / "agents" / "main").mkdir(parents=True)
    wire = sess_dir / "agents" / "main" / "wire.jsonl"
    wire.write_text("{}\n", encoding="utf-8")
    (home / "session_index.jsonl").write_text(
        json.dumps({"sessionId": "sess-1", "sessionDir": str(sess_dir),
                    "workDir": "/proj"}) + "\n", encoding="utf-8")
    monkeypatch.setenv("KIMI_CODE_HOME", str(home))
    assert T.find_kimi_wire("sess-1") == str(wire)


def test_find_kimi_wire_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path / ".kimi-code"))
    assert T.find_kimi_wire("nope") == ""
