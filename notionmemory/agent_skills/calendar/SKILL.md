---
name: calendar
description: List, add, update, and cancel my events in the Notion Calendar DB. Use when the user says things like "what's on tomorrow/this week", "schedule a meeting/add an event", or "move/cancel an event". Searching past decisions or memories is the memory skill.
---

# calendar — list / add / update / cancel

Command to run (the `notionmemory` command is registered on PATH at install time — run it as-is from any project):

```bash
notionmemory calendar list [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--days N]
notionmemory calendar add "<title>" --start "YYYY-MM-DD HH:MM" [--end "YYYY-MM-DD HH:MM"] [--location "<location>"] [--link <url>] [--notes "<notes>"] [--source claude|codex]
notionmemory calendar update <event_id> [--title "..."] [--start "..."] [--end "..."] [--location "..."] [--link <url>] [--status Scheduled|Done|Canceled]
notionmemory calendar cancel <event_id>
notionmemory calendar setup
```

## Conventions

1. Relative time expressions ("tomorrow at 3pm", "next Monday") must be **converted by the agent to `YYYY-MM-DD HH:MM` based on the current date** before being passed in. A date with no time produces an all-day event.
2. Before update/cancel, always run `list` first to find the target, show it to the user, and get **explicit confirmation**.
3. After add/update, echo the printed event_id back to the user.
4. Indicate the saving actor: `--source claude` for a Claude Code session, `--source codex` for Codex.
5. **Do not copy event text verbatim into the Second Brain.** Only save decisions or facts that arose from an event via the memory skill, linking the Notion page URL that `add` printed via memory's `--link`.
6. `cancel` records Status=Canceled and then sends the page to the Notion trash (it also disappears from the calendar app, recoverable within 30 days) — tell the user this happened.
7. If the CLI prints Notion Calendar app connection instructions (on first DB creation), relay them to the user verbatim. If the user asks "it's not showing up in the app / how do I connect it", run `calendar setup` to show the instructions — app setup has no API, so it can't be applied automatically.

## Where to write — different from reading

Reading can merge multiple sources, but writing must **pick exactly one**. When
`notionmemory calendar add` returns exit 2 with a list of candidates, that means "where to
write hasn't been decided." **Don't pick arbitrarily — ask the user.**

```
Where should I add this?
  1. Calendar DB (built-in)
  2. Tasks DB in the my-planner template
→ just this time / going forward
```

Translate the answer into a command:

| User's answer | What to run |
|---|---|
| Just this time · Calendar DB | `notionmemory calendar add ... --here` |
| Just this time · template | Check properties with `notionmemory templates show <slug>` → `notionmemory templates add <slug> <db-key> --set ...` |
| Going forward · Calendar DB | `notionmemory calendar target calendar`, then `calendar add` again |
| Going forward · template | `notionmemory calendar target template:<slug>/<db-key>` |

**Only use `calendar target` when the user explicitly says "going forward."** Promoting a
one-off answer to a permanent default means the user won't be able to trace "why does this
go here?" weeks later.

If the write target is set to a template, `calendar add` will tell you which command to run
and refuse — calendar does **not** write to another template's database. Follow the guidance
it gives and use the `templates` commands instead. Always confirm property names with
`templates show <slug>` — never guess them.

## Connection & onboarding

Before a calendar operation (especially the first one in a session), check the connection:
`notionmemory status` (whole-picture) or `notionmemory calendar connection` (this skill only).

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
- **Connected but not bound** (`calendar connection` shows "not bound"): present a menu —
  1) create a new Calendar DB: `notionmemory calendar connect --new`
  2) connect an existing one: `notionmemory calendar connect --url <url>`
  3) skip for now.
  `connect --url` adopts an existing DB: it adds any missing columns the calendar schema
  needs, but **refuses on a hard type conflict** (e.g. an existing property with the same
  name but an incompatible type) rather than guessing. Report the resulting DB link and any
  columns that were added. If it refuses, relay the reason verbatim and re-offer the menu —
  don't guess a fix.

## Find content with library

Finding things **by content** — "where did I file this / how did I do X before" — is not
this skill's job but `library`'s: `notionmemory library search "<query>"`. It searches
across your Second Brain, registered templates, and general documents, attaching the
source to every hit. Don't conclude "nothing here" from a single source.
(Date/status **filter** queries are still this skill's job — library only searches text content.)
