// notionmemory/providers/opencode/bundle/plugin.ts
//
// OpenCode plugin shim: a thin relay to the `notionmemory hook …` CLI. No memory/Notion
// logic here. Verified against @opencode-ai/plugin / @opencode-ai/sdk 1.18.23:
//  - experimental.chat.system.transform (input {sessionID?, model}, output {system: string[]})
//    is the only system-prompt injection point; inject by pushing onto output.system.
//    It has NO prompt, so recall is guidance-only (spec option A).
//  - event handler receives Event; EventSessionIdle = {type:"session.idle", properties:{sessionID}}.
//  - client.session.messages({path:{id}}) lists a session's messages ({info:{role}, parts:[{type:"text",text}]}).
//  - payloads reach the CLI via a temp file + `--input-file` (reusing pi's channel).
import type { Plugin } from "@opencode-ai/plugin";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";

const TOOL_GUIDANCE =
  "notionmemory (Notion second brain) is available via CLI: " +
  "`notionmemory recall <query>` to search memory, " +
  "`notionmemory templates`/`notionmemory library` for Notion content. Run with --help.";

function cliPath(): string {
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    return JSON.parse(readFileSync(join(here, "notionmemory.json"), "utf-8")).cli;
  } catch {
    return "notionmemory";
  }
}

function textOf(parts: any[]): string {
  if (!Array.isArray(parts)) return "";
  return parts
    .filter((p) => p && p.type === "text" && typeof p.text === "string")
    .map((p) => p.text)
    .join("\n")
    .trim();
}

// Marshal opencode session messages into Claude-compatible JSONL (what parse_claude consumes):
// one {type, message:{content:[{type:"text",text}]}} per user/assistant message.
function marshal(items: any[]): string {
  const lines: string[] = [];
  for (const it of items || []) {
    const role = it?.info?.role;
    if (role !== "user" && role !== "assistant") continue;
    const text = textOf(it?.parts);
    if (!text) continue;
    lines.push(JSON.stringify({ type: role, message: { content: [{ type: "text", text }] } }));
  }
  return lines.join("\n") + "\n";
}

export const Plugin: Plugin = async ({ client, $ }) => {
  const cli = cliPath();
  return {
    // Recall (guidance-only, option A): push the usage guidance onto the system prompt.
    "experimental.chat.system.transform": async (_input, output) => {
      try { output.system.push(TOOL_GUIDANCE); } catch { /* best-effort */ }
    },
    // Capture: on session idle, fetch messages, marshal to Claude-JSONL, hand to the CLI.
    event: async ({ event }: any) => {
      if (!event || event.type !== "session.idle") return;
      try {
        const sid = event.properties?.sessionID;
        if (!sid) return;
        const res = await client.session.messages({ path: { id: sid } });
        const items = (res as any)?.data ?? [];
        const dir = mkdtempSync(join(tmpdir(), "notionmemory-oc-"));
        const transcript = join(dir, "transcript.jsonl");
        writeFileSync(transcript, marshal(items), "utf-8");
        const payload = join(dir, "payload.json");
        writeFileSync(payload, JSON.stringify({ session_id: sid, transcript_path: transcript, cwd: process.cwd() }), "utf-8");
        await $`${cli} hook session-stop --harness opencode --input-file ${payload}`.quiet().nothrow();
        await $`${cli} hook session-end --harness opencode --input-file ${payload}`.quiet().nothrow();
      } catch { /* capture must never break the session */ }
    },
  };
};
