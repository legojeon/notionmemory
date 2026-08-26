// notionmemory/providers/pi/bundle/index.ts
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

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((b) => b && typeof b === "object" && (b as any).type === "text")
    .map((b) => String((b as any).text ?? ""))
    .join("\n")
    .trim();
}

// Marshal pi's conversation into Claude-compatible JSONL that notionmemory's
// parse_claude consumes unchanged: one {type, message:{content:[{type:"text",text}]}} per line.
function marshalTranscript(entries: any[]): string {
  const lines: string[] = [];
  for (const e of entries) {
    const role = e?.message?.role;
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

  // Recall: relay the prompt to `notionmemory hook user-prompt`, inject its stdout,
  // plus the one-line tool-availability guidance.
  pi.on("before_agent_start", async (event: any) => {
    const payload = JSON.stringify({ prompt: event.prompt ?? "", cwd: process.cwd() });
    const r = await pi.exec(cli, ["hook", "user-prompt", "--harness", "pi"], { input: payload });
    const hint = (r?.stdout ?? "").trim();
    const additions = [TOOL_GUIDANCE, hint].filter(Boolean).join("\n\n");
    return { systemPrompt: [event.systemPrompt, additions].filter(Boolean).join("\n\n") };
  });

  // Capture: marshal the conversation to Claude-JSONL, hand its path to `notionmemory hook session-stop`.
  pi.on("session_shutdown", async (_event: any, ctx: any) => {
    try {
      const entries = ctx.sessionManager.getBranch();
      const dir = mkdtempSync(join(tmpdir(), "notionmemory-pi-"));
      const file = join(dir, "transcript.jsonl");
      writeFileSync(file, marshalTranscript(entries), "utf-8");
      const payload = JSON.stringify({ session_id: ctx.sessionId ?? "", transcript_path: file, cwd: process.cwd() });
      await pi.exec(cli, ["hook", "session-stop", "--harness", "pi"], { input: payload });
      await pi.exec(cli, ["hook", "session-end", "--harness", "pi"], { input: payload });
    } catch {
      // capture must never break session teardown
    }
  });
}
