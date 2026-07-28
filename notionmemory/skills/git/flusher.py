"""git headless 플러시 — 큐를 의미 단위로 요약해 Second Brain 에 저장.

주 경로는 세션 Stop 훅(에이전트가 직접 요약)이고, 이 모듈은 세션 밖 커밋을 위한
보조 경로다. 실패 시 큐를 보존한다(다음 플러시가 재시도).
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import requests

from notionmemory.core.agent_runtime import AgentRuntimeError, build_runtime
from notionmemory.core.config import Config
from notionmemory.core.notion_client import NotionSession
from notionmemory.skills.git import queue
from notionmemory.skills.memory.notion_db import ALL_TYPES
from notionmemory.skills.memory.store import MemoryStore

DIFF_CAP = 4000  # 커밋당 git show 첨부 상한(문자)

SYSTEM = (
    "너는 git 커밋들을 장기 기억으로 요약하는 도우미다. 커밋 목록(+diff)을 읽고 "
    "의미 단위로 묶어 JSON 배열만 출력하라. 설명·코드펜스 금지. 각 원소: "
    '{"content": "첫 줄=제목, 이후 무엇을 왜 바꿨는지 요약(끝에 커밋 해시 나열)", '
    f'"type": "{"|".join(ALL_TYPES)}" 중 하나, '
    '"concepts": ["소문자", "2~5개"], "hashes": ["묶인 커밋 전체 해시"]}. '
    "사소한 커밋들은 하나로 묶고, 서로 다른 주제는 원소를 나눠라. "
    "커밋들 중 장기 기억으로 남길 가치가 있는 내용이 하나도 없다면(예: 전부 사소하거나 "
    "작업 중(WIP)인 경우) 다른 설명 없이 빈 배열 `[]`만 출력하라.")


def _git(repo: str, *args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", repo, *args], capture_output=True,
                             text=True, timeout=10)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _gh_url(repo: str) -> str:
    try:
        out = subprocess.run(["gh", "repo", "view", "--json", "url", "-q", ".url"],
                             cwd=repo, capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip().startswith("http"):
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def repo_web_url(repo: str) -> str:
    url = _gh_url(repo)
    if url:
        return url
    remote = _git(repo, "remote", "get-url", "origin").strip()
    m = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", remote)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    if remote.startswith("http"):
        return remote.removesuffix(".git")
    return ""


def _build_prompt(repo: str, group: list[dict]) -> str:
    parts = [f"리포: {repo} (프로젝트: {Path(repo).name})", "커밋 목록:"]
    for e in group:
        parts.append(f"- {e['hash']} [{e['branch']}] {e['subject']}")
        if e["body"]:
            parts.append(f"  본문: {e['body'][:500]}")
        if e["files"]:
            parts.append(f"  파일: {', '.join(e['files'][:20])}")
        diff = _git(repo, "show", "--stat", "--patch", e["hash"])
        if diff:
            parts.append("  diff:\n" + diff[:DIFF_CAP])
    return "\n".join(parts)


def _parse_units(text: str) -> list[dict]:
    cleaned = re.sub(r"^```[a-z]*\n?|\n?```$", "", text.strip())
    units = json.loads(cleaned)
    if not isinstance(units, list):
        raise ValueError("JSON 배열이 아님")
    return [u for u in units if isinstance(u, dict) and (u.get("content") or "").strip()]


def flush(config: Config, log, repo: str = "") -> int:
    entries = queue.list_entries(repo or None)
    if not entries:
        log("git 큐가 비어 있습니다")
        return 0
    try:
        runtime = build_runtime(config)
    except AgentRuntimeError as e:
        log(f"플러시 불가 — {e} (큐 보존)")
        return 2
    try:
        store = MemoryStore(NotionSession(), config)
    except RuntimeError as e:      # 토큰 부재 등 — 저장 불가, 큐 보존
        log(f"Notion 세션 불가 — {e} (큐 보존)")
        return 2
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_repo[e["repo"]].append(e)
    failures = 0
    for repo_path, group in by_repo.items():
        try:
            units = _parse_units(runtime.generate(SYSTEM, _build_prompt(repo_path, group)))
        except (AgentRuntimeError, ValueError, json.JSONDecodeError) as exc:
            log(f"요약 실패({repo_path}) — 큐 보존: {exc}")
            failures += 1
            continue
        base_url = repo_web_url(repo_path)
        files_by_hash = {e["hash"]: e["files"] for e in group}
        try:
            for u in units:
                hashes = [h for h in (u.get("hashes") or []) if h in files_by_hash]
                files = sorted({f for h in hashes for f in files_by_hash[h]}) or \
                    sorted({f for fs in files_by_hash.values() for f in fs})
                mem_type = u["type"] if u.get("type") in ALL_TYPES else "fact"
                url = f"{base_url}/commit/{hashes[0]}" if base_url and hashes else ""
                store.remember(
                    u["content"], mem_type=mem_type,
                    concepts=[str(c) for c in (u.get("concepts") or [])][:5],
                    project=Path(repo_path).name, files=files[:20],
                    source="git", url=url)
        except (requests.RequestException, RuntimeError) as exc:
            log(f"Notion 저장 실패 — 큐 보존: {exc}")
            return 2
        queue.ack([e["hash"] for e in group])
        if units:
            log(f"{repo_path}: 커밋 {len(group)}건 → 기억 {len(units)}건 저장")
        else:
            log(f"{repo_path}: 커밋 {len(group)}건 — 기억할 항목 없음으로 판단, 큐 정리")
    return 1 if failures else 0
