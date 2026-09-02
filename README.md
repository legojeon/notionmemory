<p align="center">
  <img src="assets/banner.svg" alt="notionmemory — Turn Notion into a second brain for your coding agents" width="100%">
</p>

<p align="center">
  <a href="https://pypi.org/project/notionmemory/"><img src="https://img.shields.io/pypi/v/notionmemory.svg" alt="PyPI version"></a>
  <img src="https://img.shields.io/pypi/pyversions/notionmemory.svg" alt="Python versions">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/Notion-second%20brain-191919?logo=notion&logoColor=white" alt="Notion second brain">
</p>

<p align="center"><b>English</b> | <a href="docs/README.ko.md">한국어</a></p>

<p align="center">
  <a href="#why-notionmemory">Why</a> ·
  <a href="#install">Install</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#examples">Examples</a> ·
  <a href="#benchmarks">Benchmarks</a> ·
  <a href="#agents">Agents</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#uninstall">Uninstall</a>
</p>

**notionmemory** turns your own Notion workspace into a shared, long-term brain for coding
agents (Claude Code, Codex, Kimi Code, pi, opencode). It ships a set of installable **skills** — long-term memory,
**your own page-types** (you show the agent how you build a page, and it authors new ones that
way), and content search — plus session hooks that surface the right context automatically.
Everything lives in **your** Notion; there's no separate database or server.

You don't run its commands by hand. **You talk to your agent in plain language** — "remember
that", "where did I file this?", "make more pages like the ones I build"
— and the agent runs notionmemory for you under the hood.

<p align="center">
  <img src="assets/flow.svg" width="100%"
       alt="Claude Code and Codex talk to notionmemory, which captures and recalls in your Notion">
</p>

## Why notionmemory

I built this for myself. Tools like [**agentmemory**](https://github.com/rohitg00/agentmemory)
and [claude-mem](https://github.com/thedotmack/claude-mem) keep memories in a **local vector
database** — fast and private, but two things kept getting in my way:

- **I couldn't see what was stored.** A vector DB is a black box — I couldn't open it, read what
  the agent "remembered," or fix a wrong entry. In Notion it's just pages, so I read and edit the
  memory myself.
- **It didn't follow me.** I develop across a server and a laptop, and memory that lives on one
  machine doesn't sync to the other. Notion is already **cloud** — the same brain everywhere.

I also wanted my agent beyond code: my **study notes** already live in Notion.
Keeping memory there too gives my agent (and me) one place to reach from anywhere, instead of a
hidden sidecar database. So notionmemory uses **Notion as the cloud** — visible, editable,
shared, and already where the rest of my life is.

## Install

### 1. Install the backend (user scope)

Install into your **user scope** — never `sudo` / system-wide. notionmemory places skills,
session hooks, and local state under your home (`~/.claude`, `~/.codex`,
`~/.config/notionmemory`, `~/.local/state/notionmemory`), so it must run as your own user.

```bash
pipx install notionmemory        # recommended — isolated, on your PATH, user-scoped
# or: uv tool install notionmemory
# or: pip install --user notionmemory
```

### 2. Add it to your agent

Installing for **both agents is supported** — that's the point: Claude Code and Codex share the
same brain. Just use **one install method per agent** (plugin *or* `notionmemory install`);
doing both on the same agent installs its skills twice.

**Claude Code (plugin)**

```bash
/plugin marketplace add legojeon/notionmemory
/plugin install notionmemory@notionmemory
```

> ⚠️ The plugin installs the skills **and** the session hooks. Do **not** also run
> `notionmemory install --claude` — that double-installs them.

**Codex (plugin + hooks)**

```bash
codex plugin marketplace add legojeon/notionmemory
codex plugin add notionmemory@notionmemory
notionmemory install --codex --skip-skills --trust-codex-hooks
```

> ⚠️ `--trust-codex-hooks` is required — without it Codex silently never fires the hooks.

**No plugin (one command, both agents)**

```bash
pipx install notionmemory && notionmemory install
```

> Codex users still need `notionmemory install --codex --trust-codex-hooks` before Codex
> hooks fire.

**Kimi Code / pi / opencode (one command each)**

```bash
pipx install notionmemory
notionmemory install --kimi        # or: --pi   /   --opencode
```

> No marketplace step for these three — one command installs the skills plus each agent's
> integration (pi & opencode get a small plugin bundle; Kimi Code gets `config.toml` hooks).
> `notionmemory teardown` removes all of it.

### 3. Run onboarding

Once installed, **just ask your agent to onboard you** — it runs the `notionmemory:onboard`
skill (and offers it automatically on your first session). It walks you through **connecting
Notion** — including sharing your pages with the integration — and setting up memory
and search as guided choices, skipping anything already done. The only thing it hands to you is
pasting the Notion token, because a secret must never go through chat — so mind these when you
create it at [app.notion.com/developers/tokens](https://app.notion.com/developers/tokens):

- **Workspace (most important):** choose the workspace that holds your pages — the token is
  locked to that one workspace.
- **Capability:** keep **Notion API** checked (read/write content); "Workers" isn't needed.
- **Expiration:** pick the **longest window offered** — when it lapses the token stops working
  and you'll have to create a new one and reconnect.

## Quick start

The core of it runs by itself: **as you code and work, your agent automatically keeps context
through your Notion memory.** Every session starts pre-loaded with the project brief and your
most important memories, a per-message hint surfaces a relevant memory the moment one matches,
and decisions worth keeping are captured along the way — so a new session (or a different
agent) picks up right where the last one left off.

On top of that, you just talk — the agent runs the right skill, and you never type notionmemory
commands. For example:

**Remember & recall**
> *"Remember we moved auth to JWT refresh-token rotation."*
> *"Did we decide how to handle rate limiting?"*

**Search your Notion**
> *"Where's my deployment runbook?"*

**Author in your Notion**
> *"Remember how I build my weekly reports — keep the tone brief."* (paste a page you made)
> *"Draft this week's in that shape, and drop in figure 3 from this PDF."*

You never see the CLI — and the memory keeps working between these moments, not just when
you ask.

## Examples

The **templates** skill turns any Notion database or page you own into something the agent
CRUDs and authors into by name — and an optional **attached prompt** tells it *how*. A few
things built this way: a reading list that files papers by property, an idea bank that
researches each idea before saving it, a portfolio that reads your actual repo, and a
lecture-note blueprint that turns raw slides into structured notes. Each with its base
template and the real prompt behind it:

**→ [See the examples](docs/EXAMPLES.md)**

## Benchmarks

Retrieval quality measured with [agentmemory's open eval harness](https://github.com/rohitg00/agentmemory/tree/main/eval)
(hand-labeled P@K/R@K, no LLM judge) against a **live, sandboxed Notion database** — real
`remember` ingests, real `recall` queries. Reproduce with [`bench/`](bench/README.md).

| Corpus | Adapter | R@5 | R@10 | P@5 | MRR |
| --- | --- | --- | --- | --- | --- |
| coding-agent-life-v1 — 15 dev sessions, 15 queries | grep (full-text baseline) | 0.967 | 0.967 | 0.227 | 0.824 |
| | **notionmemory** | **1.000** | **1.000** | **0.240** | **0.889** |
| LongMemEval-S (ICLR 2025), stratified sample — 6 questions, raw ~9KB chat sessions | grep (full-text baseline) | 1.000 | 1.000 | 0.333 | 0.917 |
| | **notionmemory** | **1.000** | **1.000** | **0.333** | **0.833** |

P@5 looks low by construction: most questions have 1–2 gold documents, so the ceiling is
0.2–0.4 — read it against that ceiling, not against 1.0.

No embeddings and no vector database behind those numbers: a lexical **BM25** ranking over a
tiny local index (titles, concepts, content), live-verified against Notion, with the agent
doing the semantic judging on top. Honest caveats: both corpora are small (15 + 6 hand-graded
questions — the LongMemEval sample is 1 question per type, not the full 500), latency per
recall is a live Notion round-trip (~1s), and the raw-transcript corpus is an off-label
stress test — notionmemory's designed diet is distilled memories, which score at least as well.
(The live table samples LongMemEval; the full 500 questions are covered offline below.)

On the **full 500-question** LongMemEval-S (offline, over the shipped index code — the
component that determines `recall`'s ordering; same `recall_any@K` per-question-index
protocol as [agentmemory's run](https://github.com/rohitg00/agentmemory/blob/main/benchmark/LONGMEMEVAL.md),
reproduce with `bench/lme_full500.py`), compared with results other systems report:

| | **notionmemory**<br>(BM25, no embeddings) | agentmemory<br>(BM25 + vector) | agentmemory<br>(BM25 only) | MemPalace<br>(vector-only) | oracleagentmemory | Letta / MemGPT | Mem0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Benchmark** | LongMemEval-S | LongMemEval-S | LongMemEval-S | LongMemEval-S | LongMemEval | *LoCoMo (different)* | *LoCoMo (different)* |
| **Sample** | full 500 | full 500 | full 500 | full run | full run | — | — |
| **R@5** | **0.946** | 0.952 | 0.862 | ~0.966 | 0.944 | 0.832 | 0.685 |
| **R@10** | **0.976** | 0.986 | 0.946 | ~0.976 | — | — | — |
| **MRR** | **0.893** | 0.882 | 0.715 | — | — | — | — |
| **Measured by** | us, offline index run | agentmemory | agentmemory | vendor (self-reported) | vendor (self-reported) | vendor (self-reported) | vendor (self-reported) |

Zero embeddings lands 8pp above agentmemory's BM25-only and within 0.6pp of their
BM25+vector hybrid (with a higher MRR) — the gap embeddings buy them is mostly closed by
field-weighted BM25 plus the agent doing semantic judging at read time. Honest caveats:
our row is an offline run of the shipped ranking code, not the live end-to-end path (that's
the 6-question table above); non-agentmemory rows are vendor claims on their own harnesses,
and the LoCoMo rows aren't even the same benchmark. Ballpark, not a leaderboard.

## Agents

notionmemory is **agent-driven** — the CLI is only the mechanism the agent calls. You interact
in natural language; the agent picks the right skill and runs it. It works with any agent that
runs shell hooks and a CLI — five are supported today:

<table>
<tr>
<td align="center"><strong>Claude Code</strong><br/><sub>plugin · skills + hooks</sub></td>
<td align="center"><strong>Codex</strong><br/><sub>plugin + trusted hooks</sub></td>
<td align="center"><strong>Kimi Code</strong><br/><sub>config.toml hooks</sub></td>
<td align="center"><strong>pi</strong><br/><sub>bundle plugin</sub></td>
<td align="center"><strong>opencode</strong><br/><sub>bundle plugin</sub></td>
</tr>
</table>

However it's installed, you use them the same — **talk in natural language** and the agent runs
notionmemory for you. See [Install](#install) for each agent's one-time setup.

**Skills** the agent can reach:

- **onboard** — first-time guided setup (Notion + memory + search)
- **memory** — save/recall long-term decisions & patterns in a Notion Second Brain
- **templates** — teach the agent *how you build a page*. Point it at a Notion page/DB you made and attach a prompt — the structure, the tone, which sections to research and fill, even just a memo to yourself — and it authors new entries in Notion that follow **your** workflow, not a canned template
- **library** — content search across your Notion pages
- **settings** — a local web dashboard for connections & configuration
- **git** — optional post-commit capture of your commits into memory

## How it works

Your agent talks to your Notion through the notionmemory **CLI**, which calls the **Notion REST
API**. There's no separate database and no long-running server. What makes it a *memory* rather
than a dumb store is the lifecycle — capture cheaply, **consolidate with importance scoring**,
then recall the *important* things at the right moment:

<p align="center">
  <img src="assets/lifecycle.svg" width="100%"
       alt="Memory lifecycle: capture as draft, consolidate with importance scoring (Strength 1–10), recall the top memories at the right time — all in your Notion">
</p>

### What gets stored, and how

- **Memory** is a Notion "Second Brain" database. When you explicitly say *"remember this"* it
  lands **Active** right away. When the agent decides on its own to save something, it lands as
  a **Draft** — recallable, but not yet promoted.
- Every memory carries a **Strength (1–10)** — an importance score used to rank recall and to
  decide what's worth surfacing at session start.
- A **consolidation** pass reviews the Drafts: summarize and refine them, assign a real Strength,
  drop noise (→ *Forgotten*), merge duplicates (→ *Superseded*), and keep a rolled-up per-project
  **brief** — so the database stays curated instead of a raw dump. It also mines new memories
  straight out of your session transcripts. This runs **automatically** in the background
  (a session-end/start hook), or you can run `notionmemory memory consolidate` yourself.
- To do the summarizing, the pass sends session excerpts to **your configured agent CLI** — so it
  **spends that account's usage** in the background, and **Notion only ever receives the distilled
  memory**. Set `skills.memory.consolidate_mode: nudge` in `~/.config/notionmemory/config.yaml`
  to turn the automatic pass off (manual/cron only); the backend and model
  (`integrations.agent.backend` / `.model`) live in the same file — edit it directly or ask your
  agent.

### When it reads

- **At session start**, the agent is fed this project's brief plus its top **high-Strength**
  memories — gated by importance, not a raw recency dump.
- **Per message**, a zero-network local index may add a one-line *"relevant memory"* hint; the
  agent deep-reads it with `recall` only if it's actually relevant, and ignores it otherwise.
- **On demand**, `library search` finds pointers by title/heading across your whole Notion, and
  the agent **live-reads** the winners — content is always read fresh, never cached.

### Search without embeddings

There is still no vector database and no embedding model. Memory search runs on **BM25** —
the classic lexical ranking (rare terms weigh more, long entries don't dominate) — over a
tiny local index of titles, concepts, and content. The index holds only precomputed word
statistics plus a 200-character excerpt per memory — **your memory bodies are never
duplicated on disk** — so it stays small and per-message lookups stay in milliseconds.
On top of that:

- `recall` **ranks locally, then live-verifies** the winners against Notion in one batched
  query — you get index speed with live truth (vanished pages self-heal out of the index).
- `remember` **writes through** to the index, so a memory you just saved is instantly
  searchable — no waiting for a reindex.
- Content search across your Notion pages (`library`) keeps an even simpler word-boundary
  match over titles and headings — that index never stores your page bodies.

Either way, the ranking only has to produce *candidates*: **the agent itself supplies the
semantics.** It reads the top hits live and judges what's actually relevant — the judgment a
vector similarity score approximates, an LLM does directly. Nothing to embed, sync, or go
stale.

### How memory updates

- New information **supersedes** the old (`--supersedes`) — the original is kept as *Superseded*,
  not deleted. `forget` sets Status=*Forgotten*; nothing is ever hard-deleted.
- Consolidation re-scores and merges over time, so importance and the project brief stay current.
- Pages you delete in Notion **self-heal** out of the local search index the moment they're read
  (a live 404 prunes the stale pointer), with an occasional full prune to sweep the rest.

### Why a CLI + API, not an MCP server

Two reasons: *where* it runs, and *what* it can do.

- The session hooks (SessionStart / Stop / UserPromptSubmit) run as **plain shell commands** —
  they need a CLI, not a live MCP connection held open inside an agent session.
- The same CLI runs **headless and in cron** (e.g. consolidation), not only inside an
  MCP-capable chat.
- One skill set + CLI behaves **identically across every supported agent**; MCP support and
  semantics vary by agent.
- **Fewer moving parts:** no server process to run, your token stays in the OS keyring, and the
  only local state is a thin search index.
- **It writes real content, not just text.** Going straight to the REST API lets notionmemory
  turn markdown into Notion blocks, create and edit pages and databases, and **upload images
  into a page via Notion's Direct Upload** — so the agent can drop a figure it cropped from a
  PDF right into your notes. The reading and cropping are the agent's own tools; notionmemory
  owns the Notion write, which a read-oriented MCP flow doesn't cover.

**When MCP is the better fit:** to reach a client with no shell — Claude Desktop, Gemini, a web
or mobile chat — or from any device with nothing installed, that's MCP's turf, and one server
works across every MCP client with no per-agent code. notionmemory trades that reach for what a
CLI does best: automatic capture at session boundaries, headless consolidation, and writing real
content into your pages. Different tools for different jobs.

The **settings dashboard** stores your Notion connection and skill options — just ask your agent
to *"open notionmemory settings"* (the `settings` skill), or run `notionmemory serve` yourself.
The token lives in your OS keyring, never in a file.

## Uninstall

Full removal is a few steps because different tools own different pieces. Run
`notionmemory teardown` **first** (while the CLI still exists) and remove the backend **last**
(a running `pipx uninstall` of itself is unreliable). `teardown` removes only what notionmemory
installed — skills, session/git hooks, local state — and **never touches your Notion pages**; it
keeps your config and keyring token unless you add `--purge-config --purge-secrets`.

**Claude Code (plugin):**

```bash
notionmemory teardown --purge-config --purge-secrets   # config, keyring token, local state
claude plugin uninstall notionmemory@notionmemory      # skills + hooks
claude plugin marketplace remove notionmemory          # marketplace source
pipx uninstall notionmemory                            # backend — run last
```

**Codex (plugin):**

```bash
notionmemory teardown --purge-config --purge-secrets
codex plugin remove notionmemory@notionmemory          # or uninstall it from `codex /plugins`
codex plugin marketplace remove notionmemory
pipx uninstall notionmemory
```

**No-plugin install** (you set it up with `notionmemory install`) — teardown already removes the
skills and hooks:

```bash
notionmemory teardown --purge-config --purge-secrets
pipx uninstall notionmemory
```

Drop `--purge-config --purge-secrets` to keep your config and saved token for a later reinstall.
If you installed the backend with `uv`/`pip` instead of `pipx`, uninstall it with
`uv tool uninstall notionmemory` / `pip uninstall notionmemory`. **Notion databases and pages are
never deleted.**

## License

MIT — see [LICENSE](LICENSE).
