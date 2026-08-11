---
name: onboard
description: First-time (and resumable) setup for notionmemory. Use when the user asks to set up / onboard / get started with notionmemory, when a SessionStart note offers guided onboarding, or when a core connection (Notion PAT or memory) is missing. Walks language → Notion → memory → library → templates as structured choices, skipping whatever is already configured.
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

Read which of these are already set: Notion (PAT connected), memory (bound),
library (scanned). **Skip every step that's already done** — never re-ask a
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

## 1. Language (ask first)

Ask which language notionmemory should **write memories in** (the content that lands in
the user's Notion). Present it as a structured choice (skip if the user has clearly set
one already):

1. **English**
2. **한국어 (Korean)**
3. **中文 (Chinese)**
4. **日本語 (Japanese)**

When presenting the choice, state the UI caveat plainly: notionmemory's own UI strings
(dashboard, CLI output, setup nudges) exist in **English and Korean only** — picking
English or Korean sets the UI to match, while picking Chinese or Japanese stores
memories in that language with the UI shown in English.

Then record it: `notionmemory language en|ko|zh|ja`. This sets only the storage language
(and the UI language where a catalog exists); you keep replying to the user in whatever
language they write.

## 2. Notion PAT (if `status` shows not connected)

The raw PAT/token is a secret and **must never be pasted into chat** — there is no PAT-entry CLI.

- Tell the user to open the settings dashboard and paste the token there: start it if
  needed (`notionmemory serve`, then open `http://localhost:8765`) — or they can invoke
  the `settings` skill. Point them at the Notion connection field. If you mention where to
  create the token, use exactly `https://app.notion.com/developers/tokens` (an internal
  integration / "connection"; the token starts with `ntn_`).
- Three settings matter when they create it — **the workspace is the critical one**:
  - **Workspace (most important): make sure they pick the workspace that holds the pages
    they want notionmemory to use.** The token is locked to that single workspace, and the
    wrong choice is the hardest mistake to notice later.
  - **Notion API** capability stays checked (read/write content); "Workers" is irrelevant.
  - **Expiration**: warn them to set it deliberately — the token *expires* on the date they
    choose, and once it lapses they must create a brand-new token and reconnect. Tell them to
    pick the longest window offered rather than a short one. (When it does lapse, you'll
    surface a clear 401 reconnect message.)
- **Call out the step people miss**: the token alone can read/write nothing until the user
  **shares the pages/DBs with that integration**. On each top-level page or database they
  want notionmemory to use, they open the page's `•••` menu → **Connections** (or "Add
  connections") and add the integration; sub-pages inherit, so sharing a parent covers its
  children. Say this explicitly — otherwise memory/library connect but see nothing.
- Wait for them to say they're done, then re-check:

```bash
notionmemory status
```

- Only proceed once it reports Notion **connected** (this live-verifies the token). Don't
  attempt any DB setup before this passes. If it still shows not connected, relay that and
  let them retry in the dashboard.

## 3. memory (if `status` shows not bound)

Present a choice — create / connect / skip:

1. **Create a new Second Brain**: `notionmemory memory connect --new`
2. **Connect an existing one** (ask for the Notion URL): `notionmemory memory connect --url <url>`
3. **Skip for now**

`memory connect --url` is **strict** — it only accepts a real notionmemory Second Brain
(matching schema), so it's safe against pointing at an unrelated database. Report the
resulting DB link on success. If it refuses, relay the reason verbatim and re-offer the
choice — don't guess a fix. On skip, move on without setting anything.

## 4. library (if `status` shows not scanned)

Offer a scan — yes / no:

- **Yes**: `notionmemory library refresh` (scans pages shared with the integration so
  `library search` works).
- **No**: skip — they can run it later.

## 5. templates (usage note only — no setup)

No connection needed. In one or two lines, tell the user that — going forward — they can
just **ask you in plain language** to register a Notion page/DB as a template or to author
content into one ("register this page as a template", "fill in the weekly report"), and you
run it for them; the settings dashboard is where per-template prompts are managed. Frame it
as talking to you, not as commands to type. Then finish — don't force any setup.

## Done

Briefly summarize what's now set up and what was skipped, and mention they can re-run
onboarding anytime by asking you to set up the skipped parts.
