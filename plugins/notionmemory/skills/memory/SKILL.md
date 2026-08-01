---
name: memory
description: Saves, searches, and deletes long-term memories in a Notion Second Brain. Use when the user says "remember this / save this / note that", when you've learned a decision, pattern, or preference with lasting value, or when past context would help ("did we ever" do this before).
---

# memory — remember / recall / forget

Executable commands (the `notionmemory` command is registered on PATH at install time — run it as-is from any project):

```bash
notionmemory remember "<content>" --type <t> --concepts "a,b,c" [--files "x.py,y.ts"] [--project <p>] [--source claude|codex] [--related <mem_id>] [--link <notion_page_url>] [--supersedes <mem_id>] [--auto]
notionmemory recall "<query>" [--type <t>] [--project <p>] [--top N]
notionmemory recall --get <mem_id>
notionmemory forget <mem_id>
```

## remember conventions

1. Preserve the user's own wording in content — no reinterpreting or over-summarizing.
2. concepts should be **2-5 items, lowercase, specific**: `jwt-refresh-rotation` correct / `auth` wrong.
3. If there are referenced file paths, record them in `--files` (real paths only, never guess).
4. Choose `--type`: pattern (a recurring code pattern) / preference (a user preference) / architecture (a structural decision) / bug (a bug and its fix) / workflow (a work procedure) / fact (anything else).
5. Indicate who is saving: `--source claude` for a Claude Code session, `--source codex` for Codex.
6. **When the agent decides on its own to save something, always attach `--auto`.** Saves the user explicitly requested go without `--auto`. If it exits 2 ("auto-save is off"), give up on saving and move on quietly.
7. When replacing an existing memory, use `--supersedes <mem_id>` (the original is preserved as Superseded); use `--related <mem_id>` for related memories and `--link <url>` for a related Notion page.
8. After saving, echo the printed mem_id and concepts back to the user verbatim — those are the future search terms.
9. **Status differs by who decided.** A `--auto` save (your own judgment) lands as **Draft**
   — it's still recallable, but not yet "final"; a later `memory consolidate` pass reviews
   Drafts, refines/summarizes them, assigns a real Strength, drops junk, and merges
   duplicates. A save **without** `--auto` (the user explicitly asked you to remember
   something) lands as **Active** immediately and is treated as important right away — no
   consolidation needed for it.

## consolidation (Draft → Active)

Auto-captured memories start life as Drafts and need a later pass to become durable,
Strength-ranked Active memories (or get dropped/merged). That pass is
`notionmemory memory consolidate [--project <p>]` — it calls an LLM to review a
project's Drafts, then writes the results back to Notion (promote to Active with a
Strength 1-10, drop low-value ones to Forgotten, merge duplicates into Superseded) and
updates that project's rollup brief.

- **This command must run non-nested** — in the user's own terminal or a cron job, not
  from inside an agent session (it needs its own agent-runtime call, and nesting one
  agent session inside another isn't supported). If the user wants it run now, tell them
  to run it themselves in a plain terminal rather than running it via a tool call.
- **Consolidation now runs automatically.** SessionEnd and SessionStart hooks spawn it as
  a detached background process (default `skills.memory.consolidate_mode: auto`), so you
  no longer need to relay a "drafts pending" nudge to the user — it's already being
  handled outside the conversation. Don't manually run it via a tool call either way (see
  the non-nested rule above). If the user asks about consolidation status, check the log
  at the state dir's `memory/consolidate.log`, or point them to `notionmemory memory
  consolidate` for a manual run (useful if they've switched to
  `skills.memory.consolidate_mode: nudge`, or for troubleshooting).
- Consolidation also **mines memories directly from session transcripts** — it reviews
  recent session content (not just Drafts) and, when it finds something durable, saves it
  straight as an **Active** memory with a real **Strength**, no Draft stage. These show up
  with `Source` set to the harness whose sessions were mined (per pass, `claude`/`codex`) —
  not necessarily the harness that ran *this* session. The transcript is re-read locally;
  the excerpt is sent to the **configured agent runtime**
  (`integrations.agent.backend`, claude preferred over codex by default — pin it if the
  user wants a specific CLI/account) to do the mining, which can differ from the harness
  that actually ran the session. Only the distilled memory content reaches Notion.
- SessionStart also injects this project's brief (a rolled-up summary consolidation
  maintains) and its top high-Strength Active memories, when available — treat those as
  free background context, not something you need to `recall` again.
- **Long raw content boundary**: the Excerpt field that search matches against only
  shows roughly the first 6000 characters of a memory's content — anything past that is
  invisible to search. Don't dump a long raw transcript or file into a single `remember`
  call expecting it to stay searchable; consolidation's job is to distill that kind of
  Draft down into a dense, verbatim-preserving summary with real concepts, which is the
  designed path for making long input searchable.

## Per-message hints (local index)

A local memory index (built by `notionmemory memory reindex`, and auto-refreshed at the
end of `memory consolidate`) backs a lightweight per-message check: on some turns, the
session context may contain a line like `relevant memory — "<title>" (recall for
detail): notionmemory recall --get <mem_id>`. That's a hint, not an authoritative
injection — it's best-effort local lexical matching (no embeddings), fires per message,
and can be absent or imperfect.

- **Treat it as a pointer, not an answer.** If the hinted title actually looks relevant
  to what the user just asked, run the given `recall --get <mem_id>` (or a normal
  `recall`) to pull the full memory before using it. Never surface the hint's title/id
  to the user as if it were the retrieved content.
- **If it's not relevant, ignore it silently.** Don't mention an irrelevant hint to the
  user or force it into the conversation.
- If session context instead says the memory index is empty (e.g. "local search index
  is empty — run `notionmemory memory reindex` to fill it"), **just run `notionmemory
  memory reindex` yourself** — it's a quick local rebuild from Notion, so do it rather
  than handing the user a command to type (mention in one line that you refreshed the
  memory index). This note only appears when memory is bound. `recall` itself now ranks
  candidates from this same local index first and live-verifies the top matches in at most
  two batched round-trips before ever falling back to a full live query; `remember` writes
  through to the index right after a successful save, so a memory you just saved is
  visible to `recall` immediately. `memory reindex` (run manually, or automatically at
  the end of `memory consolidate`) is the full rebuild that keeps the index's aggregate
  stats correct over time — not the only thing keeping it usable.

## recall conventions

- Use the user's own wording as the query as-is. Narrow with `--project`/`--type` when a project or topic is mentioned.
- **Never fabricate results**: report exactly what comes back, and if it falls back to "no results," say so plainly and suggest 2-3 alternative search terms. Never make things up.
- Use `recall --get <mem_id>` when the full content is needed.

## forget conventions

- Before deleting, always use recall to find the target, show it to the user, and get **explicit confirmation**.
- Tell the user this sets Status=Forgotten (not a hard delete).

## Anti-patterns

WRONG: `--concepts "stuff, code, notes"` — unfindable later.
RIGHT: `--concepts "jwt-refresh-rotation, token-revocation"` — specific and searchable.

WRONG: recall returns nothing, so you answer with a guess like "it was probably discussed last week."
RIGHT: "No matching memories. Should I try searching for `refresh token` or `session expiry` instead?"

## Checklist

- content preserves the user's own wording.
- concepts: 2-5 items, lowercase, specific.
- `--auto` is attached when the agent decided to save on its own.
- recall results were reported exactly as returned.

## Connection & onboarding

Before a memory operation (especially the first one in a session), check the connection:
`notionmemory status` (whole-picture) or `notionmemory memory connection` (this skill only).

If several things are unset at once, the `onboard` skill runs the full guided sequence
(PAT → memory → calendar → library → templates) as structured choices — invoke it
instead of walking each skill by hand. This section is the per-skill connect detail
`onboard` (and you) rely on.

- **No PAT (Notion not connected)**: don't try to fix this yourself. Guide the user to the
  settings dashboard (the `settings` skill, or `notionmemory serve` → `http://localhost:8765`)
  to connect Notion there. **The raw PAT/token must never be pasted into chat** — there is no
  PAT-entry CLI, and asking for it defeats the point of the dashboard. After the user says
  they're done, re-run `notionmemory status` — it live-verifies the connection — and only
  proceed once it reports connected. Don't attempt DB setup before this passes.
- **Connected but not bound** (`memory connection` shows "not bound"): present a menu —
  1) create a new Second Brain DB: `notionmemory memory connect --new`
  2) connect an existing one: `notionmemory memory connect --url <url>`
  3) skip for now.
  `connect --url` is **strict** for memory — it only succeeds against a real notionmemory
  Second Brain DB (matching schema), so it's safe against pointing at an unrelated database.
  Report the resulting DB link from a successful connect. If it refuses, relay the reason
  verbatim and re-offer the menu — don't guess a fix.

## Find content with library

Finding things **by content** — "where did I file this / how did I do X before" — is not
this skill's job but `library`'s: `notionmemory library search "<query>"`. It searches
across your Second Brain, registered templates, and general documents, attaching the
source to every hit. Don't conclude "nothing here" from a single source.
(Date/status **filter** queries are still this skill's job — library only searches text content.)
