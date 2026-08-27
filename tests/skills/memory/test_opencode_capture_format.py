import json
from notionmemory.skills.memory import transcripts as T

# Exactly what plugin.ts marshal() writes.
SHIM_LINES = [
    {"type": "user", "message": {"content": [{"type": "text", "text": "add opencode support"}]}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Wired the plugin."}]}},
]


def test_parse_claude_consumes_opencode_shim_jsonl(tmp_path):
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in SHIM_LINES) + "\n", encoding="utf-8")
    text, consumed = T.parse_claude(str(p))
    assert "[USER] add opencode support" in text
    assert "[ASSISTANT] Wired the plugin." in text
    assert consumed == p.stat().st_size
