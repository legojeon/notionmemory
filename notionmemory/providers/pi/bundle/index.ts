// notionmemory/providers/pi/bundle/index.ts
//
// pi extension shim: a thin adapter that relays pi lifecycle events to the
// `notionmemory hook …` CLI. No memory/Notion logic lives here.
//
// Verified against @earendil-works/pi-coding-agent 0.74.2 type defs:
//  - before_agent_start handler returning { systemPrompt } replaces/chains the
//    turn's system prompt (BeforeAgentStartEventResult.systemPrompt).
//  - pi.exec(command, args, opts?) has NO stdin channel (ExecOptions = {signal,
//    timeout, cwd}), so payloads are passed via a temp file + `--input-file`,
//    which the CLI redirects onto the hook's stdin.
//  - ctx.sessionManager.getBranch()/getSessionId() (ReadonlySessionManager).
//  - session entries are SessionMessageEntry { type:"message", message:AgentMessage }.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";

// The install step (bundle_mirror) writes notionmemory.json next to this file with the
// absolute CLI path resolved at install time — pi's runtime PATH is not trusted.
function cliPath(): string {
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    return JSON.parse(readFileSync(join(here, "notionmemory.json"), "utf-8")).cli;
  } catch {
    return "notionmemory";
  }
}

// Write a JSON payload to a fresh temp file and return its path. pi's exec has no
// stdin channel, so hooks receive their payload via `--input-file`.
function writePayload(payload: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), "notionmemory-pi-"));
  const file = join(dir, "payload.json");
  writeFileSync(file, JSON.stringify(payload), "utf-8");
  return file;
}

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((b) => b && typeof b === "object" && (b as any).type === "text")
    .map((b) => String((b as any).text ?? ""))
    .join("\n")
    .trim();
}

// Marshal pi's session entries into Claude-compatible JSONL that notionmemory's
// parse_claude consumes unchanged: one {type, message:{content:[{type:"text",text}]}}
// per line. Only SessionMessageEntry (type==="message") carries a message.
function marshalTranscript(entries: any[]): string {
  const lines: string[] = [];
  for (const e of entries) {
    if (!e || e.type !== "message" || !e.message) continue;
    const role = e.message.role;
    if (role !== "user" && role !== "assistant") continue;
    const text = textOf(e.message.content);
    if (!text) continue;
    lines.push(JSON.stringify({ type: role, message: { content: [{ type: "text", text }] } }));
  }
  return lines.join("\n") + "\n";
}

// pi has no confirmed SKILL.md dir, so notionmemory's action surface is delivered by
// injection (spec §"Instruction delivery", default). Keep it one short line — the agent
// pulls detail on demand. Live-verify may upgrade this to a skill mirror if pi supports one.
const TOOL_GUIDANCE =
  "notionmemory (Notion second brain) is available via CLI: " +
  "`notionmemory recall <query>` to search memory, " +
  "`notionmemory templates`/`notionmemory library` for Notion content. Run with --help.";

export default function (pi: ExtensionAPI) {
  const cli = cliPath();

  async function runHook(name: string, payload: unknown): Promise<string> {
    const file = writePayload(payload);
    const r = await pi.exec(cli, ["hook", name, "--harness", "pi", "--input-file", file]);
    return (r?.stdout ?? "").trim();
  }

  // Recall: relay the prompt to `notionmemory hook user-prompt`, inject its stdout,
  // plus the one-line tool-availability guidance.
  pi.on("before_agent_start", async (event: any) => {
    let hint = "";
    try {
      hint = await runHook("user-prompt", { prompt: event.prompt ?? "", cwd: process.cwd() });
    } catch {
      // recall is best-effort; never block the turn
    }
    const additions = [TOOL_GUIDANCE, hint].filter(Boolean).join("\n\n");
    return { systemPrompt: [event.systemPrompt, additions].filter(Boolean).join("\n\n") };
  });

  // Capture: marshal the conversation to Claude-JSONL, hand its path to the CLI hooks.
  pi.on("session_shutdown", async (_event: any, ctx: any) => {
    try {
      const entries = ctx.sessionManager.getBranch();
      const dir = mkdtempSync(join(tmpdir(), "notionmemory-pi-"));
      const transcript = join(dir, "transcript.jsonl");
      writeFileSync(transcript, marshalTranscript(entries), "utf-8");
      const sid = ctx.sessionManager.getSessionId ? ctx.sessionManager.getSessionId() : "";
      const payload = { session_id: sid ?? "", transcript_path: transcript, cwd: process.cwd() };
      await runHook("session-stop", payload);
      await runHook("session-end", payload);
    } catch {
      // capture must never break session teardown
    }
  });
}
