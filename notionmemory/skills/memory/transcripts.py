"""트랜스크립트 → 대화 발췌 + 워터마크 원장 (스펙 §2).

user 메시지는 의도·결정을 담으므로 통째(2,000자 캡), assistant 는 텍스트 블록 앞
600자만, 도구 호출·출력은 전부 제외한다(토큰 낭비 + 민감정보 최소화). Stop 은 매 턴
발화해 진행 중 세션도 큐에 들어오므로, 발굴한 바이트 오프셋을 원장(mined.json)에
남겨 같은 내용의 이중 발굴을 막는다 — 크기가 안 변했으면 통째 스킵, 자랐으면 그
이후만 읽는다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from notionmemory.core import paths
from notionmemory.core.projects import resolve_project

PER_MSG_USER_CAP = 2000
PER_MSG_ASSISTANT_CAP = 600
PER_SESSION_CAP = 12000
TOTAL_CAP = 48000
LEDGER_EXPIRY_DAYS = 30


def ledger_path() -> Path:
    return paths.state_dir() / "memory" / "mined.json"


def load_ledger() -> dict:
    """원장 로드 — 통째로 손상됐으면(JSON 파싱 실패 등) 빈 원장(=전부 재발굴 후보).

    엔트리 하나가 dict 가 아니면(예: 수동 편집/디스크 오류로 문자열이 들어감) 그
    엔트리만 조용히 버리고 나머지는 그대로 쓴다(M4) — `collect_excerpts` 가
    `.get("bytes")` 를 호출할 때 dict 아닌 값에서 AttributeError 가 나 그 프로젝트
    전체를 per-project except 밖으로 새게 하는 대신, 손상된 세션 하나만 "원장에
    없던 것"(=처음부터 재발굴)으로 저하시킨다."""
    try:
        raw = json.loads(ledger_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {sid: ent for sid, ent in raw.items() if isinstance(ent, dict)}


def save_ledger(led: dict, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=LEDGER_EXPIRY_DAYS)
    kept = {}
    for sid, ent in led.items():
        if not isinstance(ent, dict):
            continue  # 손상된 엔트리 — save 시점에도 다시 거른다(load_ledger 를 안 거친
                      # 인메모리 dict 를 직접 넘기는 호출자를 위한 방어)
        try:
            ts = datetime.fromisoformat(str(ent.get("ts", "")))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ts >= cutoff:
            kept[sid] = ent
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # 원자 교체(1.0.2 선례, mem_index.save 와 동일 규율) — write_text 직행이면 프로세스가
    # 쓰는 도중 죽었을 때 반쯤 쓰인 JSON이 남아 다음 load_ledger 가 통째로 실패한다.
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _text_blocks(content, cap: int) -> list[str]:
    """message.content(str 또는 블록 리스트)에서 텍스트만 — 도구/씽킹 블록 제외."""
    if isinstance(content, str):
        return [content[:cap]] if content.strip() else []
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text" and str(b.get("text", "")).strip():
                out.append(str(b["text"])[:cap])
    return out


def parse_claude(path: str, since_bytes: int = 0) -> tuple[str, int]:
    lines_out: list[str] = []
    with open(path, "rb") as f:
        f.seek(since_bytes)
        data = f.read()
        consumed = since_bytes + len(data)
    for raw in data.decode("utf-8", errors="replace").splitlines():
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("isSidechain"):
            continue
        kind = e.get("type")
        msg = e.get("message") or {}
        if kind == "user":
            for t in _text_blocks(msg.get("content"), PER_MSG_USER_CAP):
                lines_out.append(f"[USER] {t}")
        elif kind == "assistant":
            for t in _text_blocks(msg.get("content"), PER_MSG_ASSISTANT_CAP):
                lines_out.append(f"[ASSISTANT] {t}")
    return "\n".join(lines_out)[:PER_SESSION_CAP], consumed


def parse_codex(path: str, since_bytes: int = 0, expect_cwd: str = "") -> tuple[str, int] | None:
    """서브에이전트 스레드/cwd 불일치는 None(세션 통째 스킵). 메타(1행)는 오프셋과
    무관하게 항상 다시 읽는다 — 스킵 판정이 거기 있다."""
    try:
        with open(path, "rb") as f:
            first = f.readline()
            meta = json.loads(first.decode("utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    payload = (meta or {}).get("payload") or {}
    if payload.get("thread_source") == "subagent" or "subagent" in str(payload.get("source") or ""):
        return None
    if expect_cwd and payload.get("cwd") and payload["cwd"] != expect_cwd:
        return None
    lines_out: list[str] = []
    with open(path, "rb") as f:
        f.seek(max(since_bytes, len(first)))
        data = f.read()
        consumed = max(since_bytes, len(first)) + len(data)
    for raw in data.decode("utf-8", errors="replace").splitlines():
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("type") != "event_msg":
            continue
        p = e.get("payload") or {}
        if p.get("type") == "user_message" and str(p.get("message", "")).strip():
            lines_out.append(f"[USER] {str(p['message'])[:PER_MSG_USER_CAP]}")
        elif p.get("type") == "agent_message" and str(p.get("message", "")).strip():
            lines_out.append(f"[ASSISTANT] {str(p['message'])[:PER_MSG_ASSISTANT_CAP]}")
    return "\n".join(lines_out)[:PER_SESSION_CAP], consumed


def _kimi_home() -> Path:
    override = os.environ.get("KIMI_CODE_HOME")
    return Path(override).expanduser() if override else Path.home() / ".kimi-code"


def parse_kimi(path: str, since_bytes: int = 0) -> tuple[str, int]:
    lines_out: list[str] = []
    with open(path, "rb") as f:
        f.seek(since_bytes)
        data = f.read()
        consumed = since_bytes + len(data)
    for raw in data.decode("utf-8", errors="replace").splitlines():
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        kind = e.get("type")
        if kind == "turn.prompt" and (e.get("origin") or {}).get("kind") == "user":
            for t in _text_blocks(e.get("input"), PER_MSG_USER_CAP):
                lines_out.append(f"[USER] {t}")
        elif kind == "context.append_message":
            msg = e.get("message") or {}
            if msg.get("role") == "assistant":
                for t in _text_blocks(msg.get("content"), PER_MSG_ASSISTANT_CAP):
                    lines_out.append(f"[ASSISTANT] {t}")
    return "\n".join(lines_out)[:PER_SESSION_CAP], consumed


def find_kimi_wire(session_id: str, cwd: str = "") -> str:
    if not session_id:
        return ""
    index = _kimi_home() / "session_index.jsonl"
    try:
        text = index.read_text(encoding="utf-8")
    except OSError:
        return ""
    # Guard against the known missing-newline bug (issue #1925): split on "}{" too.
    for raw in text.replace("}{", "}\n{").splitlines():
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("sessionId") == session_id \
                and not rec.get("deleted"):
            wire = Path(str(rec.get("sessionDir", ""))) / "agents" / "main" / "wire.jsonl"
            return str(wire) if wire.is_file() else ""
    return ""


def find_codex_rollout(session_id: str) -> str:
    root = Path.home() / ".codex" / "sessions"
    if not session_id or not root.is_dir():
        return ""
    hits = sorted(root.glob(f"**/rollout-*-{session_id}.jsonl"))
    return str(hits[-1]) if hits else ""


def _codex_meta_cwd(path: str) -> str:
    """codex rollout 파일 첫 줄(meta)에서 cwd 만 뽑는다 — project-level 비교(I2)용.

    `parse_codex` 자신도 내부적으로 이 meta 를 읽어 subagent 스킵을 판정하지만,
    project 비교는 그보다 위(`collect_excerpts`)에서 한다: session_meta.cwd 를 그대로
    (raw 문자열) 비교하면 같은 리포의 서브디렉터리에서 시작한 세션이 다른 프로젝트로
    오판된다 — `resolve_project()` 로 정규화한 뒤 비교해야 한다."""
    try:
        with open(path, "rb") as f:
            first = f.readline()
        meta = json.loads(first.decode("utf-8", errors="replace"))
    except (OSError, ValueError):
        return ""
    return str(((meta or {}).get("payload") or {}).get("cwd") or "")


def collect_excerpts(sessions: list[dict], ledger: dict,
                     expect_project: str = "") -> tuple[list[dict], list[str]]:
    """`expect_project` 가 주어지면(consolidate 가 프로젝트명을 넘긴다, I2) codex
    세션의 session_meta.cwd 를 `resolve_project()` 로 정규화해 비교한다 — 불일치면
    (다른 리포에서 시작된 codex 세션) 건너뛴다. 빈 `expect_project` 나 meta 에 cwd 가
    없는 세션은 체크하지 않는다(기존 하위호환)."""
    out, notes, total = [], [], 0
    ordered = sorted(sessions, key=lambda s: str(s.get("ts", "")), reverse=True)
    for s in ordered:
        sid, path = str(s.get("session_id", "")), str(s.get("transcript_path", ""))
        if not sid or not path:
            continue
        try:
            size = Path(path).stat().st_size
        except OSError:
            notes.append(f"transcript missing, skipped: {sid}")
            continue
        raw_entry = ledger.get(sid)
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        try:
            since = int(entry.get("bytes") or 0)
        except (TypeError, ValueError):
            since = 0  # 손상된 bytes 값(M4) — 원장에 없던 것처럼 처음부터 재발굴
        if since >= size:
            continue  # 크기 불변 — 이미 발굴한 범위
        if s.get("harness") == "codex":
            if expect_project:
                meta_cwd = _codex_meta_cwd(path)
                if meta_cwd and resolve_project(meta_cwd) != expect_project:
                    notes.append(f"session skipped (subagent/cwd): {sid}")
                    continue
            parsed = parse_codex(path, since_bytes=since)
        elif s.get("harness") == "kimi":
            parsed = parse_kimi(path, since_bytes=since)
        else:
            parsed = parse_claude(path, since_bytes=since)
        if parsed is None:
            notes.append(f"session skipped (subagent/cwd): {sid}")
            continue
        text, consumed = parsed
        if not text.strip():
            continue
        truncated = False
        if total + len(text) > TOTAL_CAP:
            text = text[: TOTAL_CAP - total]
            truncated = True
            notes.append(f"total cap {TOTAL_CAP} reached; older sessions dropped")
            if not text:
                break
        total += len(text)
        excerpt = {"session_id": sid, "harness": str(s.get("harness") or "claude"),
                  "text": text, "consumed_bytes": consumed}
        if truncated:
            # 이 세션은 TOTAL_CAP 에 걸려 뒷부분이 잘렸다 — `consumed_bytes` 는 파일
            # 오프셋(정상 파싱 범위)이지만 LLM 은 잘린 `text` 만 본다. 소비자(consolidate)가
            # 이 오프셋을 원장에 그대로 기록해버리면 LLM 이 못 본 뒷부분이 "이미
            # 발굴됨"으로 표시되어 영원히 유실된다 — 그래서 잘렸다는 사실을 여기서
            # 명시해 소비자가 원장 갱신을 건너뛸 수 있게 한다.
            excerpt["truncated"] = True
        out.append(excerpt)
        if total >= TOTAL_CAP:
            break
    return out, notes
