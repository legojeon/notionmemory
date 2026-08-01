"""transcripts.py — 하네스별 트랜스크립트 → 대화 발췌 + 워터마크 원장."""
import json
from pathlib import Path

import pytest

from notionmemory.core import paths
from notionmemory.skills.memory import transcripts as tr


def _claude_line(role, content, sidechain=False):
    return json.dumps({"type": role, "isSidechain": sidechain,
                       "cwd": "/proj", "message": {"role": role, "content": content}},
                      ensure_ascii=False)


def _write(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_claude_parse_keeps_user_and_assistant_text_only(tmp_path):
    p = _write(tmp_path, "s.jsonl", [
        _claude_line("user", "결정: BM25 로 간다"),
        _claude_line("assistant", [{"type": "thinking", "thinking": "숨김"},
                                   {"type": "text", "text": "네 BM25 적용하겠습니다"},
                                   {"type": "tool_use", "name": "Bash", "input": {}}]),
        _claude_line("user", [{"type": "tool_result", "content": "거대한 도구 출력"}]),
        _claude_line("user", "사이드체인은 빠져야", sidechain=True),
    ])
    text, consumed = tr.parse_claude(str(p), since_bytes=0)
    assert "결정: BM25 로 간다" in text
    assert "BM25 적용하겠습니다" in text
    assert "숨김" not in text and "거대한 도구 출력" not in text
    assert "사이드체인" not in text
    assert consumed == p.stat().st_size


def test_claude_parse_resumes_from_offset(tmp_path):
    p = _write(tmp_path, "s.jsonl", [_claude_line("user", "첫 턴")])
    _, consumed = tr.parse_claude(str(p), since_bytes=0)
    with p.open("a", encoding="utf-8") as f:
        f.write(_claude_line("user", "둘째 턴") + "\n")
    text2, consumed2 = tr.parse_claude(str(p), since_bytes=consumed)
    assert "첫 턴" not in text2 and "둘째 턴" in text2
    assert consumed2 == p.stat().st_size


def _codex_lines(cwd="/proj", thread_source="user", msgs=()):
    out = [json.dumps({"type": "session_meta",
                       "payload": {"cwd": cwd, "thread_source": thread_source}})]
    for kind, m in msgs:
        out.append(json.dumps({"type": "event_msg",
                               "payload": {"type": kind, "message": m}}, ensure_ascii=False))
    return out


def test_codex_parse_skips_subagent_and_wrong_cwd(tmp_path):
    sub = _write(tmp_path, "sub.jsonl",
                 _codex_lines(thread_source="subagent", msgs=[("user_message", "서브")]))
    assert tr.parse_codex(str(sub), since_bytes=0, expect_cwd="/proj") is None
    wrong = _write(tmp_path, "wrong.jsonl",
                   _codex_lines(cwd="/other", msgs=[("user_message", "딴 프로젝트")]))
    assert tr.parse_codex(str(wrong), since_bytes=0, expect_cwd="/proj") is None
    ok = _write(tmp_path, "ok.jsonl",
                _codex_lines(msgs=[("user_message", "코덱스 결정"), ("agent_message", "답")]))
    text, consumed = tr.parse_codex(str(ok), since_bytes=0, expect_cwd="/proj")
    assert "코덱스 결정" in text and consumed == ok.stat().st_size


def test_assistant_blocks_capped_at_600_user_at_2000(tmp_path):
    p = _write(tmp_path, "s.jsonl", [
        _claude_line("user", "u" * 5000),
        _claude_line("assistant", [{"type": "text", "text": "a" * 5000}]),
    ])
    text, _ = tr.parse_claude(str(p), since_bytes=0)
    assert text.count("u") == 2000 and text.count("a") == 600


def test_collect_excerpts_respects_ledger_and_total_cap(tmp_path, monkeypatch):
    big = _write(tmp_path, "big.jsonl",
                 [_claude_line("user", f"턴{i} " + "x" * 1900) for i in range(40)])
    sessions = [{"session_id": "s1", "transcript_path": str(big),
                 "harness": "claude", "ts": "2026-08-01T00:00:00Z"}]
    ex, notes = tr.collect_excerpts(sessions, ledger={})
    assert ex and len(ex[0]["text"]) <= tr.PER_SESSION_CAP
    # 원장에 소비량이 기록돼 있으면 그 이후만 — 크기 불변이면 통째 스킵
    ledger = {"s1": {"bytes": big.stat().st_size, "ts": "2026-08-01T00:00:00Z"}}
    ex2, _ = tr.collect_excerpts(sessions, ledger=ledger)
    assert ex2 == []


def test_collect_excerpts_skips_missing_file(tmp_path):
    sessions = [{"session_id": "gone", "transcript_path": str(tmp_path / "nope.jsonl"),
                 "harness": "claude", "ts": "2026-08-01T00:00:00Z"}]
    ex, notes = tr.collect_excerpts(sessions, ledger={})
    assert ex == [] and any("gone" in n for n in notes)


def test_collect_excerpts_marks_truncated_only_for_capped_session(tmp_path, monkeypatch):
    """TOTAL_CAP 에 걸려 text 가 잘리는 세션만 `truncated: True` — consumed_bytes 는
    (파싱은 끝까지 됐으니) 잘림과 무관하게 여전히 파일 전체 오프셋이다. 소비자
    (consolidate)가 이 플래그로 원장 갱신 여부를 가른다(fix round 1, finding 2)."""
    monkeypatch.setattr(tr, "TOTAL_CAP", 40)
    a = _write(tmp_path, "a.jsonl", [_claude_line("user", "a" * 20)])   # text 27자, 캡 안 걸림
    b = _write(tmp_path, "b.jsonl", [_claude_line("user", "b" * 20)])   # text 27자, 남는 캡 13자
    sessions = [
        {"session_id": "a", "transcript_path": str(a), "harness": "claude",
         "ts": "2026-08-01T01:00:00Z"},
        {"session_id": "b", "transcript_path": str(b), "harness": "claude",
         "ts": "2026-08-01T00:00:00Z"},
    ]
    ex, notes = tr.collect_excerpts(sessions, ledger={})
    by_id = {e["session_id"]: e for e in ex}
    assert "truncated" not in by_id["a"]
    assert by_id["b"]["truncated"] is True
    assert len(by_id["b"]["text"]) < len(by_id["a"]["text"])  # 실제로 잘렸다
    # consumed_bytes 는 파일 전체 오프셋 그대로 — 잘린 text 길이와는 무관.
    assert by_id["b"]["consumed_bytes"] == b.stat().st_size
    assert any("total cap" in n for n in notes)


def test_ledger_roundtrip_and_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(tr.paths, "state_dir", lambda: tmp_path)
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    old = (now - timedelta(days=31)).isoformat()
    tr.save_ledger({"old": {"bytes": 10, "ts": old},
                    "new": {"bytes": 20, "ts": now.isoformat()}}, now=now)
    led = tr.load_ledger()
    assert "new" in led and "old" not in led


# ── I2: collect_excerpts 의 codex project-level cwd 가드(expect_project) ──────

def test_collect_excerpts_subdirectory_cwd_of_same_project_is_not_skipped(tmp_path, monkeypatch):
    """session_meta.cwd 가 같은 프로젝트의 서브디렉터리여도(raw cwd 문자열 자체는
    다르다) `resolve_project()` 로 정규화한 뒤 비교해 같은 project 로 인정되고
    스킵되지 않는다 — "naive fix"(job['cwd'] 를 그대로 raw 비교)가 틀렸던 지점."""
    ok = _write(tmp_path, "ok.jsonl",
               _codex_lines(cwd="/Users/x/myrepo/sub",
                           msgs=[("user_message", "서브디렉터리 결정")]))
    monkeypatch.setattr(tr, "resolve_project",
                        lambda cwd: "myrepo" if "myrepo" in cwd else "other")
    sessions = [{"session_id": "s1", "transcript_path": str(ok), "harness": "codex",
                "ts": "2026-08-01T00:00:00Z"}]

    ex, notes = tr.collect_excerpts(sessions, ledger={}, expect_project="myrepo")

    assert ex and "서브디렉터리 결정" in ex[0]["text"]
    assert not any("subagent/cwd" in n for n in notes)


def test_collect_excerpts_skips_codex_session_from_other_project(tmp_path, monkeypatch):
    wrong = _write(tmp_path, "wrong.jsonl",
                  _codex_lines(cwd="/Users/x/otherrepo",
                              msgs=[("user_message", "딴 프로젝트")]))
    monkeypatch.setattr(tr, "resolve_project",
                        lambda cwd: "otherrepo" if "other" in cwd else "myrepo")
    sessions = [{"session_id": "s1", "transcript_path": str(wrong), "harness": "codex",
                "ts": "2026-08-01T00:00:00Z"}]

    ex, notes = tr.collect_excerpts(sessions, ledger={}, expect_project="myrepo")

    assert ex == []
    assert any("subagent/cwd" in n for n in notes)


def test_collect_excerpts_no_project_check_when_expect_project_empty(tmp_path):
    """`expect_project` 를 안 넘기면(하위호환, 기본값 "") 프로젝트 체크 자체가 없다."""
    wrong = _write(tmp_path, "wrong.jsonl",
                  _codex_lines(cwd="/Users/x/otherrepo",
                              msgs=[("user_message", "체크 안 함")]))
    sessions = [{"session_id": "s1", "transcript_path": str(wrong), "harness": "codex",
                "ts": "2026-08-01T00:00:00Z"}]

    ex, notes = tr.collect_excerpts(sessions, ledger={})

    assert ex and "체크 안 함" in ex[0]["text"]


# ── M4: 손상된 원장 엔트리는 AttributeError 로 새지 않고 "부재"로 저하한다 ──

def test_collect_excerpts_treats_corrupt_ledger_entry_as_absent(tmp_path):
    p = _write(tmp_path, "s.jsonl", [_claude_line("user", "재발굴 대상")])
    sessions = [{"session_id": "s1", "transcript_path": str(p), "harness": "claude",
                "ts": "2026-08-01T00:00:00Z"}]

    ex, notes = tr.collect_excerpts(sessions, ledger={"s1": "not-a-dict"})

    assert ex and "재발굴 대상" in ex[0]["text"]   # 손상된 엔트리 → 원장에 없던 것처럼 재발굴


def test_load_ledger_drops_non_dict_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(tr.paths, "state_dir", lambda: tmp_path)
    tr.ledger_path().parent.mkdir(parents=True, exist_ok=True)
    tr.ledger_path().write_text(
        json.dumps({"s1": "corrupt-string-value", "s2": {"bytes": 5, "ts": "t"}}),
        encoding="utf-8")

    led = tr.load_ledger()

    assert led == {"s2": {"bytes": 5, "ts": "t"}}


def test_save_ledger_writes_atomically(tmp_path, monkeypatch):
    """M4 — tmp 파일 + os.replace(1.0.2 선례). 중간에 죽어도 반쯤 쓰인 JSON 이
    최종 경로에 남지 않는다는 걸 os.replace 호출 자체를 관측해 확인한다."""
    monkeypatch.setattr(tr.paths, "state_dir", lambda: tmp_path)
    from datetime import datetime, timezone
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    calls = []
    real_replace = tr.os.replace

    def spy_replace(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(tr.os, "replace", spy_replace)

    tr.save_ledger({"s1": {"bytes": 10, "ts": now.isoformat()}}, now=now)

    assert len(calls) == 1
    tmp_src, dst = calls[0]
    assert dst == str(tr.ledger_path())
    assert tmp_src.endswith(".json.tmp")
    assert not Path(tmp_src).exists()          # 교체 후 tmp 잔존 없음
    assert tr.ledger_path().is_file()
