---
name: library
description: Use this to find where something is organized in my Notion. When the user's own Notion content (pages, documents, Second Brain) needs to be found by content — "where did I organize this", "how did I handle X before", "let's reuse that paper summary elsewhere" — run the notionmemory CLI with this skill.
---

# library

Finds **"what something is about"** across my entire Notion. Whether it's a page, a document,
or a Second Brain entry, and regardless of whether it's a template or a plain document, it finds
it by content in one shot.

```
notionmemory library search "<query>" [--limit N]   # ranked pointers (source · title · section · id)
notionmemory library read <page-id>                 # live-read the found page's body (block ids inline)
notionmemory library refresh [--full]                # refresh the scan (--full for a full crawl)
notionmemory library status                          # scan age · count
```

`search` returns **pointers, not body content** — `content · [page-id] title > section`,
`memory · [mem-id] title`. Each pointer carries its source.

## Three usage modes

- **locate** — Just show the pointers from `search`. Do not read the body.
- **pull** — Live-read only the top 1–2 candidates with `library read <page-id>` and use that.
  The read output has block ids inline, so if you need to revisit a specific part, use those.
  Do not bulk-read every candidate (delegate below if 3+ sources).
- **sweep** — When you need to sweep 3+ sources and synthesize, **delegate to a subagent**.
  Have the subagent read the candidates and return **only the answer + sources (ids)**, so the
  raw body content doesn't flood the main context. (Delegation conditions: 3+ sources, synthesis
  needed, read-only. Source pointers must always be returned.)

## If the scan is empty or stale

If session start injects "library: not scanned yet" or a stale age, the scan doesn't exist yet or
is out of date. **Tell the user you're scanning their Notion**, then run `library refresh --full`
before searching (this crawls the whole workspace and takes time, so don't do it silently). For
queries where recency matters, like "what did I write today," also `refresh` first.

If session start instead injects "deleted or unshared pages may be lingering … run `notionmemory
library refresh --full`", that's a **periodic prune request** (a full crawl drops pages you
deleted/unshared in Notion). Run it at a non-disruptive moment — it's routine cleanup, not urgent
— and mention it's a ~1–2 min periodic tidy, not something the user asked for. (You don't need to
ask permission; just say you're doing a quick library cleanup.)

## Limits

- **The scan only knows titles and headings.** A page whose relevant content lives only in the
  body, not in the title or headings, may not be found — try broadening the query with synonyms
  (e.g., "container orchestration" → "Kubernetes"), or ask the user which page they mean.
- Search reflects the current scan, so **a page you just created may not show up until you
  refresh.**
- **Deletions lag search, not read.** A page you deleted or unshared in Notion can linger as a
  `search` pointer until a `refresh --full`; but `read` is always live, so reading a dead pointer
  simply reports the page is gone (and self-heals that entry out of the scan). Never present a
  stale `search` hit as if it still exists — the live `read` is the source of truth.
- **Date/status filters** ("tomorrow's schedule", "incomplete todos") belong to templates'
  structured queries, not library. library only finds things by "what they're about" (text).
