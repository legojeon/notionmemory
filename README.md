# notionmemory

Turn Notion into a second-brain hub for coding agents (Claude Code, Codex).
notionmemory ships a set of installable **skills** — long-term memory, calendar,
templates, and library recall — plus session hooks that surface the right context
automatically.

> Skills and CLI onboarding output are available in English (default) and Korean
> (`config language: en|ko`). A longer Korean guide is at [`docs/README.ko.md`](docs/README.ko.md).

## Install

1) Backend (required, both harnesses):

```bash
pipx install notionmemory      # or: uv tool install notionmemory / pip install --user notionmemory
```

2a) Claude Code (plugin):

```bash
/plugin marketplace add legojeon/notionmemory
/plugin install notionmemory@notionmemory
# skills appear as notionmemory:calendar, notionmemory:memory, …
# Do NOT also run `notionmemory install --claude` (the plugin already installs skills + hooks).
```

2b) Codex (plugin + hooks):

```bash
codex plugin marketplace add legojeon/notionmemory
codex plugin add notionmemory@notionmemory
notionmemory install --codex --skip-skills --trust-codex-hooks   # hooks + trust (plugin owns the skills)
# --skip-skills: don't mirror skills, the plugin already provides them
# --trust-codex-hooks: required or Codex will silently not fire the installed hooks
```

3) Get set up — run guided onboarding:

Once installed, just ask your agent to **onboard you** — it runs the
**`notionmemory:onboard`** skill. On your first session the agent also offers this
automatically. Onboarding walks you through connecting Notion and setting up memory,
calendar, and library as guided choices, and skips anything already done.

When it reaches the **Notion token** step it sends you to the settings dashboard to
paste your integration token (`ntn_...`) — the token is entered there, never in chat.
Create one at <https://www.notion.so/my-integrations>, and share the Notion pages/DBs
you want notionmemory to use with that integration. It's stored in your OS keyring,
never in config.

You can open that dashboard anytime — ask the agent for the **`notionmemory:settings`**
skill, or run it from a terminal:

```bash
notionmemory serve      # opens the settings dashboard at http://localhost:8765
```

It shows your **Notion**, **Agent** (Claude Code / Codex), and **git** (gh) connections
in one place so you can verify them. Until Notion is connected, the skills load but
can't read or write Notion.

Prefer no plugin? One uniform command sets up both harnesses (skills unnamespaced):

```bash
pipx install notionmemory && notionmemory install
```

Codex users: `notionmemory install` will tell you to also run `notionmemory install --codex --trust-codex-hooks` before Codex hooks fire.

The marketplace source is this repository. If you're working from a local clone
before it's reachable as `legojeon/notionmemory`, add it by path instead:
`codex plugin marketplace add "$(pwd)"` / `claude plugin marketplace add "$(pwd)"`.

## Skills

- **onboard** — first-time guided setup: connect Notion and set up memory, calendar & library
- **memory** — save/recall long-term decisions & patterns in a Notion Second Brain
- **calendar** — read/create/move events in a Notion calendar DB
- **templates** — CRUD over your registered Notion templates & databases
- **library** — content search across your Notion pages
- **settings** — local web dashboard for connections & configuration

## Upgrade

notionmemory installs files on your system (skill mirrors, session/git hooks,
state). To upgrade cleanly — including removing skills that a new version has
retired — run `notionmemory teardown` then reinstall. `teardown` removes only what
it installed; your Notion pages, config, and keyring token are preserved by
default (see `notionmemory teardown --dry-run`).

## Uninstall

Full removal is a few steps because different tools own different pieces: the plugin
(skills + hooks) and its marketplace source belong to the harness, and the Python
backend belongs to your package manager. Run `notionmemory teardown` **first** — while
the CLI still exists — and remove the backend **last** (a running `pipx uninstall` of
itself is unreliable).

`teardown` removes only what notionmemory installed (skill mirrors, session/git hooks,
local state). It never touches your Notion databases/pages, and it keeps config + your
keyring token unless you add `--purge-config --purge-secrets`.

**Plugin install — Claude Code:**

```bash
notionmemory teardown --purge-config --purge-secrets   # config, keyring token, local state
claude plugin uninstall notionmemory@notionmemory      # skills + hooks
claude plugin marketplace remove notionmemory          # marketplace source
pipx uninstall notionmemory                            # Python backend — run last
```

**Plugin install — Codex:**

```bash
notionmemory teardown --purge-config --purge-secrets
codex plugin remove notionmemory@notionmemory          # or uninstall it from `codex /plugins`
codex plugin marketplace remove notionmemory
pipx uninstall notionmemory
```

**Non-plugin install** (you set it up with `notionmemory install`): teardown already
removes the skills and hooks, so it's just:

```bash
notionmemory teardown --purge-config --purge-secrets
pipx uninstall notionmemory
```

Keep `--purge-config --purge-secrets` off if you want to preserve your config and saved
Notion token for a later reinstall. If you installed the backend with `uv`/`pip` instead
of `pipx`, uninstall it with `uv tool uninstall notionmemory` / `pip uninstall
notionmemory`. Notion databases and pages are never deleted.

## License

MIT — see [LICENSE](LICENSE).
