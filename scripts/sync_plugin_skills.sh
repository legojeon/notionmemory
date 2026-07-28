#!/usr/bin/env bash
# agent_skills(편집 원본) → plugins/notionmemory/skills(Codex 플러그인 사본) 동기화.
# codex plugin add 가 심링크를 안 따라 실파일 사본이 필요하다. test_plugin_manifests 가 byte-identical 강제.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
src="$root/notionmemory/agent_skills"
dst="$root/plugins/notionmemory/skills"
rm -rf "$dst"; mkdir -p "$dst"
for d in "$src"/*/; do
  name="$(basename "$d")"
  [ -f "$d/SKILL.md" ] || continue
  mkdir -p "$dst/$name"
  cp "$d/SKILL.md" "$dst/$name/SKILL.md"
done
echo "synced $(ls "$dst" | wc -l | tr -d ' ') skills -> $dst"
