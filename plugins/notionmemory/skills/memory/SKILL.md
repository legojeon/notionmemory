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
- **Setup sequence** when several things are unconfigured at once, do them in this order:
  PAT (settings dashboard) → memory → calendar → library (ask "want me to index it for
  search?" → `notionmemory library refresh`) → templates (usage note only, no setup needed).

## Find content with library

Finding things **by content** — "where did I file this / how did I do X before" — is not
this skill's job but `library`'s: `notionmemory library search "<query>"`. It searches
across your Second Brain, registered templates, and general documents, attaching the
source to every hit. Don't conclude "nothing here" from a single source.
(Date/status **filter** queries are still this skill's job — library only searches text content.)
