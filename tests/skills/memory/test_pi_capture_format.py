import json
from notionmemory.skills.memory import transcripts as T

# Exactly what index.ts marshalTranscript() writes: {type, message:{content:[{type:text,text}]}}
SHIM_LINES = [
    {"type": "user", "message": {"content": [{"type": "text", "text": "add pi support"}]}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done, wired the shim."}]}},
]


def test_parse_claude_consumes_shim_jsonl(tmp_path):
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in SHIM_LINES) + "\n", encoding="utf-8")
    text, consumed = T.parse_claude(str(p))
    assert "[USER] add pi support" in text
    assert "[ASSISTANT] Done, wired the shim." in text
    assert consumed == p.stat().st_size
