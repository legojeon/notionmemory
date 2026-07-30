---
name: onboard
description: First-time (and resumable) setup for notionmemory. Use when the user asks to set up / onboard / get started with notionmemory, when a SessionStart note offers guided onboarding, or when a core connection (Notion PAT, memory, or calendar) is missing. Walks Notion → memory → calendar → library → templates as structured choices, skipping whatever is already configured.
---

# onboard — guided setup

You (the agent) drive this in chat. It is **not** the settings dashboard — the dashboard
only stores the Notion token; every setup decision happens here as a structured choice.
The flow is **state-aware and idempotent**: probe first, skip anything already done, and
only present choices for what's missing. Safe to run again anytime the user asks.

## 0. Probe state first

```bash
notionmemory status
```

Read which of these are already set: Notion (PAT connected), memory (bound), calendar
(bound), library (scanned). **Skip every step that's already done** — never re-ask a
bound DB or a connected PAT. Then walk the missing ones in the sequence below.

## Present each decision as a structured choice

For every choice step below, present the options as a **structured multiple-choice
question**, not free-form chat:

- **In Claude Code**: use the `AskUserQuestion` tool so the options render as a real
  selectable menu.
- **In Codex or any harness without that tool**: fall back to a clear **numbered menu**
  in chat (`1) … 2) … 3) …`) and act on the number the user picks. (Codex has no
  equivalent structured-question tool today, so the numbered menu is the real path there.)

The PAT step is an instruction, not a choice — no menu there.

## 1. Notion PAT (if `status` shows not connected)

The raw PAT/token is a secret and **must never be pasted into chat** — there is no PAT-entry CLI.

- Tell the user to open the settings dashboard and paste the token there: start it if
  needed (`notionmemory serve`, then open `http://localhost:8765`) — or they can invoke
  the `settings` skill. Point them at the Notion connection field.
- Wait for them to say they're done, then re-check:

```bash
notionmemory status
```

- Only proceed once it reports Notion **connected** (this live-verifies the token). Don't
  attempt any DB setup before this passes. If it still shows not connected, relay that and
  let them retry in the dashboard.

## 2. memory (if `status` shows not bound)

Present a choice — create / connect / skip:

1. **Create a new Second Brain**: `notionmemory memory connect --new`
2. **Connect an existing one** (ask for the Notion URL): `notionmemory memory connect --url <url>`
3. **Skip for now**

`memory connect --url` is **strict** — it only accepts a real notionmemory Second Brain
(matching schema), so it's safe against pointing at an unrelated database. Report the
resulting DB link on success. If it refuses, relay the reason verbatim and re-offer the
choice — don't guess a fix. On skip, move on without setting anything.

## 3. calendar (if `status` shows not bound)

Same create / connect / skip choice:

1. **Create a new Calendar DB**: `notionmemory calendar connect --new`
2. **Connect an existing one**: `notionmemory calendar connect --url <url>`
3. **Skip for now**

`calendar connect --url` adopts an existing DB: it adds any missing columns the calendar
schema needs, but **refuses on a hard type conflict** rather than guessing. Report the DB
link and any added columns. If it refuses, relay the reason and re-offer.

## 4. library (if `status` shows not scanned)

Offer a scan — yes / no:

- **Yes**: `notionmemory library refresh` (scans pages shared with the integration so
  `library search` works).
- **No**: skip — they can run it later.

## 5. templates (usage note only — no setup)

No connection needed. In one or two lines, tell the user templates let them register and
author Notion pages (`notionmemory templates ...`, or the settings dashboard to manage
per-template prompts) — then finish. Don't force any setup.

## Done

Briefly summarize what's now set up and what was skipped, and mention they can re-run
onboarding anytime by asking you to set up the skipped parts.
