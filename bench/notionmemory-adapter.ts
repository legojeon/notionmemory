// notionmemory adapter — ingests sessions via `notionmemory remember` into a
// SANDBOX Second Brain DB (config passed via NOTIONMEMORY_CONFIG, never the real
// one) and queries via `notionmemory recall`. Honest-mode: when recall falls back
// to "recent N" (no lexical match), we return [] — fallback rows are not matches.
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { Adapter, RankedDoc, Session } from "../types.js";

const run = promisify(execFile);

const CLI =
  process.env.NOTIONMEMORY_CLI ??
  "/Users/legojeon/Documents/Projects/notionmemory/venv/bin/notionmemory";
const CFG = process.env.NOTIONMEMORY_CONFIG ?? "";
// per-init unique project — longmemeval runs init() per QUESTION into the same
// sandbox DB, so recall isolation between questions comes from the project filter.
let initCounter = 0;

interface NmState {
  memToSession: Map<string, string>;
  project: string;
}

export const notionmemoryAdapter: Adapter<NmState> = {
  name: "notionmemory-lexical",
  async init(sessions: Session[]) {
    if (!CFG) throw new Error("NOTIONMEMORY_CONFIG must point at the sandbox config");
    const project = `bench-${Date.now().toString(36)}-${initCounter++}`;
    const memToSession = new Map<string, string>();
    for (const s of sessions) {
      const { stdout } = await run(CLI, [
        "remember", s.content,
        "--type", "fact",
        "--project", project,
        "--source", "claude",
        "--config", CFG,
      ], { maxBuffer: 16 * 1024 * 1024 });
      const m = stdout.match(/Saved (\S+) with/);
      if (!m) throw new Error(`could not parse mem_id from: ${stdout}`);
      memToSession.set(m[1], s.id);
    }
    console.log(`  ingested ${sessions.length} sessions (project=${project})`);
    return { memToSession, project };
  },

  async query(q: string, state: NmState, k: number): Promise<RankedDoc[]> {
    const { stdout } = await run(CLI, [
      "recall", q,
      "--project", state.project,
      "--top", String(k),
      "--config", CFG,
    ], { maxBuffer: 16 * 1024 * 1024 });
    if (/결과 없음|저장된 memory 없음/.test(stdout)) return []; // fallback ≠ match
    const out: RankedDoc[] = [];
    for (const line of stdout.split("\n")) {
      const m = line.match(/^\[\w+\] (mem_\S+) · /);
      if (!m) continue;
      const sessionId = state.memToSession.get(m[1]);
      if (sessionId) out.push({ sessionId, score: k - out.length });
    }
    return out.slice(0, k);
  },
};
