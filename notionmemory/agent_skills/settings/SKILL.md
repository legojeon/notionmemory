---
name: settings
description: Opens the notionmemory web settings dashboard. Use this skill when the user says something like "open notionmemory settings" or "show me the connections/settings screen" — it (re)starts the local settings server if needed and opens the browser.
---

# settings

When the user wants to open notionmemory's settings screen (connections, skill options), follow the steps below in order.

## 1. Check if it's already running

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/api/skills
```

- If the response is `200`, the server is already running — don't start a new one, skip ahead to step 3.

## 2. If it's not running, start it in the background

Use the `notionmemory` command (registered on PATH at install time).

```bash
nohup notionmemory serve >/tmp/notionmemory-serve.log 2>&1 &
```

- Wait about 1 second, then re-run the `curl` from step 1 to confirm you get `200`. If it doesn't come up, check `/tmp/notionmemory-serve.log` and report the cause to the user.

## 3. Open the browser

```bash
open http://localhost:8765
```

## 4. Tell the user

- URL: `http://localhost:8765`
- This screen is **settings-only** — it stores connections (Notion PAT, etc.), skill option defaults, and **per-template prompts** (how and in what tone to fill each template). The actual work of reading material and authoring/organizing it into Notion is done by the `templates` skill (`templates create-page` to create the structure → `templates block`/`templates image` to author content).
- To stop the server: `pkill -f "notionmemory serve"`

## Notes

- The port is fixed at `8765`. The server keeps running in the background, so let the user know to stop it with the `pkill` command above once they're done.
