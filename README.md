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

2) Connect Notion — do this first, before using any skill:

```bash
notionmemory serve      # opens the settings dashboard at http://localhost:8765
```

In the dashboard, click the **Notion** connection and paste your Notion integration
token (`ntn_...`). Create one at <https://www.notion.so/my-integrations>, and share
the Notion pages/DBs you want notionmemory to use with that integration. The token is
stored in your OS keyring, never in config. Without this, the skills can't reach Notion.

3a) Claude Code (plugin):

```bash
/plugin marketplace add legojeon/notionmemory
/plugin install notionmemory@notionmemory
# skills appear as notionmemory:calendar, notionmemory:memory, …
# Do NOT also run `notionmemory install --claude` (the plugin already installs skills + hooks).
```

3b) Codex (plugin + hooks):

```bash
codex plugin marketplace add legojeon/notionmemory
codex plugin add notionmemory@notionmemory
notionmemory install --codex --skip-skills --trust-codex-hooks   # hooks + trust (plugin owns the skills)
# --skip-skills: don't mirror skills, the plugin already provides them
# --trust-codex-hooks: required or Codex will silently not fire the installed hooks
```

Prefer no plugin? One uniform command sets up both harnesses (skills unnamespaced):

```bash
pipx install notionmemory && notionmemory install
```

Codex users: `notionmemory install` will tell you to also run `notionmemory install --codex --trust-codex-hooks` before Codex hooks fire.

The marketplace source is this repository. If you're working from a local clone
before it's reachable as `legojeon/notionmemory`, add it by path instead:
`codex plugin marketplace add "$(pwd)"` / `claude plugin marketplace add "$(pwd)"`.

## Skills

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

```bash
notionmemory teardown              # removes skills, hooks, local state
notionmemory teardown --purge-config --purge-secrets   # also config + token
```

Notion databases and pages are never deleted.

## License

MIT — see [LICENSE](LICENSE).
