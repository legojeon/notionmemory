---
name: templates
description: Use to look up, add, update, or author against a registered Notion template/database. If the user mentions their own Notion templates or DBs — like "add this to my reading list", "show application status", "register this template" — run the notionmemory CLI with this skill.
---

# templates

Register an arbitrary Notion template, then CRUD it according to its schema. Unlike the DBs
we built ourselves (calendar, second brain), **the code doesn't know the schema** — so every
time, read the profile first and use the names in it verbatim.

## 3-step protocol — follow the order

```
1. notionmemory templates list            # which templates are registered
2. notionmemory templates show <slug>     # DB key · property names · types
3. add / query / update using the exact names seen in step 2
```

**Don't skip step 2 and guess property names or options.** The value-enforcement layer
blocks it anyway, but it costs an extra round trip. The rejection message includes the full
allow-list, so read it and retry with the correction.

If you also need to see options/relation targets, use `templates show <slug> --full`.

## Query

```
notionmemory templates query <slug> <db>
  --where "property operator value"     # multiple = AND
  --search "free text"        # token AND × text-property OR
  --sort "property asc|desc"
  --limit N | --all
  --fields "A,B,C" | --count | --json
```

Operators: `=` `!=` `>` `<` `>=` `<=` `contains` `!contains` `starts` `ends` `in` `empty` `!empty`

- **If you use `--limit`, also give `--sort`.** Truncating without sorting gives the first N
  rows in an arbitrary order — if the user asked for "the last 5", you get any 5. If output
  was truncated, that fact appears on the last line.
- **Pass dates as absolute dates, computed by you.** `--where "Due >= 2026-07-22"`. This CLI
  does not interpret relative expressions.
- `in` is the only surface for OR: `--where "Status in Todo,Doing"`.
- Write relations by name: `--where "Company contains Acme"` — no need to look up the id.
- The real row id in results is always the `id` key. If the target DB has a user-created
  property literally named `id`/`url`, that value isn't dropped — it's moved to the
  `"id (property)"` / `"url (property)"` key and preserved — if you requested a property
  with that name, look for it there in the result.

## Add · update · archive

```
notionmemory templates add <slug> <db> --set "property=value" [--set ...] [--notes "markdown"]
notionmemory templates update <slug> <db> <row-id> --set "property=value"
notionmemory templates archive <slug> <db> <row-id>
```

- `<row-id>` is the first column of `query` output. Don't try to update without querying first.
- Values not in the option list are rejected. Attach `--allow-new-option` **only when the
  user explicitly asked you to create a new option** — attaching it by default lets typo'd
  options accumulate in the user's workspace.
- There is no hard delete. `archive` moves to trash, which Notion can restore from within 30 days.

## Register · refresh · remove

```
notionmemory templates register <page URL | page ID | name>   # re-register with --slug
notionmemory templates refresh <slug>     # when the user changed the schema in Notion
notionmemory templates refresh <slug> --refresh-notes  # regenerate schema + usage notes (body) too — slow
notionmemory templates remove <slug>      # deletes only the profile, doesn't touch Notion
```

- Before registering, confirm that **the page has been shared with the integration**
  (the most common failure): page top-right ••• → Connections → notionmemory.
- If registering by name matches multiple candidates, it exits 2 with a list — ask the user
  which one they mean.
- If you hit a "property not found" error, the user renamed it in Notion. Run `refresh` first.

**If you need a new DB** — notionmemory has **no DB-creation command (by design)**. Schema
authoring is your job: call the Notion API directly via `NotionSession` to create a DB with
the schema you want, then bring its URL in with `register` to CRUD it. Property types/options
aren't boxed in by our CLI, so this gives full freedom.

```python
from notionmemory.core.notion_client import NotionSession
NotionSession().request("POST", "/databases", json={
    "parent": {"page_id": "<parent page id>"},
    "title": [{"type": "text", "text": {"content": "<DB name>"}}],
    "properties": { "Name": {"title": {}}, "Status": {"select": {"options": [...]}} }})
# → bring the id/url from the response in with `notionmemory templates register <url>`
```

## Document editing — working with body content, no DB involved

Templates aren't only databases. Pages whose content is **body text (paragraphs, headings,
sections)** — CVs, portfolios, paper notes — get registered too. The `Structure:` list in
`show <slug>` gives each page's heading outline and page-id.

```
templates read <slug> <page-id>                       # live body → markdown + block-id
templates block add <page-id> [--after <block-id>] --markdown "..."   # append (free)
templates page add <parent-page-id> --title "..." [--markdown "..."] # create subpage (free)
templates block set <block-id> --markdown "..." [--yes]   # replace content (needs confirmation)
templates block remove <block-id> [--yes]                 # delete = trash (needs confirmation)
```

If body content contains **backticks (code fences), quotes, or `$()`**, don't pass it via
`--markdown "..."` straight to the shell — use `--markdown-file <path>` (or
`--markdown-file -` for stdin) instead, to avoid the shell mistaking backticks for command
substitution. The same applies to `prompt --set-file` and `new-prompt --prompt-file`
(prompts commonly contain backticks). Writing the markdown to a file first and passing that
path is the safe route.

`read` output is `[<block-id>] <markdown>`; `[db: id]` is an embedded DB (→ handle it with
`query`), `[page: id]` is a subpage (→ `read` it separately).

**A row body is also a document.** Each row in a DB is itself a page. "Add a paper and write
a summary" means: use `add` to create the row and get **the row id**, then use `block add`
on that id to fill in the body — a combination of CRUD (row) + document editing (body).

### Three rules

1. **Never guess a block-id without `read`.** Before editing or deleting, always `read` the
   page first to get live block-ids. The cached outline (`show`) only tells you the
   structure — editing needs a live id.
2. **`--yes` is not a shortcut.** Calling `block set`/`remove` without `--yes` returns a
   preview (before → after) and exits 2. **Show that preview to the user and only re-run
   with `--yes` after getting their approval.** Don't attach `--yes` on your own to skip
   confirmation. Adds/creates are free to do without asking.
3. **New items should imitate an existing sibling.** When creating a new subpage or row
   body, first `read` an existing sibling to see its section structure, then write in the
   same shape (Notion database templates can't be triggered via the API).

`read` only the one page you're editing (not the whole tree). You already know the section
structure from `show`'s cached outline.

## Content authoring — filling in a template

Each template can have an **attached prompt** (`templates show` displays it if present) —
"fill this template like this, in this tone." Read it and follow it before authoring.

- If you need a new structure, create and register a page with `templates create-page
  --parent <id> --title <t> --slug <s>`, then attach a prompt with `templates prompt <s>
  --set "<instructions/tone>"`.
- Fill in the body with `templates block`/`templates page` (document editing);
  **insert images with `templates image <page-id> <local-image> [--caption ...]`** (this
  command handles the Notion upload).
- Read files (PDF/code/HTML) and crop figures **with your own tools** — notionmemory does
  not read. Just pass the path of the image file you produced to `templates image`.

### Example — lecture notes / paper notes
"Organize this folder of lecture material for me": (1) you read the PDFs/images in the
folder yourself (reading and figure-cropping are your own tools' job — install PyMuPDF/
poppler etc., or ask the user if missing; notionmemory only handles writing to Notion),
(2) create a notes page with `templates page add <parent>`, (3) following that template's
prompt, fill the body with `templates block` and insert cropped figures with `templates
image`. Paper notes work the same way — structure/tone come from the template/prompt,
reading/cropping is on you.

`templates create-page` **registers** the page it creates as a template — use it only when
creating a single, ongoing edit-target page (an instance). Notes stamped repeatedly from a
blueprint should not be registered (registry pollution) — use `templates page add` for
those instead.

## Prompt-only templates (blueprints) — repeated generation

A template with a prompt but no `page_id` is a **blueprint** — if `templates show` displays
it as "prompt-only," that means it isn't one page, it's **a definition that stamps out a
new page each time**.

- Create: `templates new-prompt <slug> --name "Lecture Notes" --prompt "<instructions/tone>"`
  (no location fixed yet).
- **Using it**: "organize this lecture material (as lecture notes)" → read that template's
  prompt, **agree with the user on a location**, create a new page with `templates page add
  <parent>`, then fill it per the prompt using `templates block`/`image` (don't register
  it). Repeat per subject — each note you make exists independently, and finding it later
  is `library`'s job.
- **Promoting it**: once it becomes "let's collect these notes into one DB," `templates
  register` that DB **under the same slug** to turn it into an instance-DB (the prompt is
  preserved), and from then on add one row per subject to that DB.
- Prompt-only templates have no `query`/`add`/`refresh` (DB/structure operations) — those
  commands are blocked with guidance.

### Seed — lecture notes
The retired note-capture skill is revived as this blueprint. Set it up once and reuse it
per subject. Create it with `templates new-prompt lecture-notes --name "Lecture Notes"
--prompt "<prompt below>"`, putting the full text below (distilled from the old
note-capture rules) into the prompt verbatim. The tone lives inside the prompt too (a
template = structure + attached prompt, tone included):

```
Read lecture, paper, or study material (PDF/image/slides) and turn it into a personal
knowledge note that is still useful when you look at it again months later. Don't pretend
to know information that isn't in the source. Write the notes in the SAME LANGUAGE as the
source material.

[authority/evidence] The source material is the only ground truth — don't add background
knowledge, examples, quotes, numbers, or claims about the author's intent from your own
memory. Restructure and paraphrase boldly for clarity, but preserve the source's
conditions, exceptions, uncertainty, formulas, terminology, and comparison direction. If a
reading is uncertain, don't guess to fill it in — omit it or mark it as uncertain.

[terminology] When the source uses non-English technical vocabulary, annotate the original
term with a brief gloss on first use — pair the source-language term with a short
explanatory gloss the first time a key term or definition appears. Preserve casing and math
notation. Don't invent forced translations — keep the original term/abbreviation if there's
no natural equivalent.

[structure] Infer the material type from the source and use the matching frame: lecture →
scope → prerequisite concepts → key concepts and their relations → examples present in the
source → limitations/points of confusion → synthesis; paper → citation → question →
motivation → method → setup → results → limitations; experiment/assignment/project → goal
→ setup → procedure → results → interpretation → next steps. Open with a 2–4 sentence
overview stating the scope and the key question. Reorganize by concept/argument structure,
not slide order. Include examples only when they're present in the source.

[style] Describe the subject directly rather than reviewing the material itself — ban
phrasing like "this lecture..." / "the slide says..." (write "X is defined as..." instead).
Default to a plain, dispassionate textbook register — no addressing the reader, no
exclamations. Each paragraph carries one role only — roughly 1–2 sentences and about 220
characters at most — and breaks with a blank line when moving from definition → implication
or condition → example.

[format] Keep key definitions/theorems in short paragraphs, bold only the key terms (don't
overuse a "Definition —" prefix or blockquotes). Use inline LaTeX for short expressions,
standalone `$$...$$` for long derivations. Use tables for comparisons, numbered lists for
procedures, bullets for parallel items, language-tagged code blocks for code, and checkboxes
for to-dos.

[figures] Crop important figures/diagrams and place each right after the paragraph that
interprets it — don't dump them all at the end. Skip decorative logos, tables of contents,
and pages that duplicate body text. Fold handwriting into the relevant sentence; omit it if
illegible.

[Notion syntax] Don't use `[[wikilinks]]` (connect concepts through prose instead). Headings
go up to three levels (`#`–`###`), list nesting up to one level. No slash commands or HTML
tags — write tables and code in markdown syntax.

[title] Pull the title from the cover page or first title in the source, not from the
filename or an invented summary. If a lecture number and topic are visible, use
`Lecture N — original title`; never invent a missing number or title.
```

## Relationship to other skills — parallel sources

Built-in skills (calendar / memory / git) and registered templates are **not competitors.**
Users don't tell you where their data lives.

1. Before answering, check the `notionmemory templates:` list injected at session start.
2. If a template overlaps the request's domain, **query both and merge with sources
   attached** — e.g. "2 from calendar · 1 from todo-list".
3. **Never conclude "nothing" from checking only one source.** A silent omission is the only
   real failure here.
4. Narrow down only once the user names a specific template.

**Writing is different.** If something overlaps a built-in like calendar — a schedule/
deadline — and the user says "add it," you must pick one place. If `notionmemory calendar
add` exits 2 with a list of candidates, ask the user, and if they say they want this
template going forward, lock it in with `notionmemory calendar target
template:<slug>/<db-key>`. To revert, use `notionmemory calendar target calendar`.

## Limits — know these up front

- **Page body is not searchable.** Notion API DB filters only look at properties. Content
  put into `--notes` cannot be found by any condition. Guide the user to put anything they'll
  need to search for into a property instead.
- View/filter/sort settings and automatic creation of the relation's counterpart row are not
  supported.

## Delegating to a subagent

Delegate **only when all three conditions are true.**

1. **3 or more** sources to sweep
2. What's needed is **synthesis**, not raw rows
3. **Read-only**, with no follow-up edit expected

(3) is the key one — a subagent returns only a summary, so **the row ids are lost**, which
makes any subsequent `update`/`archive` impossible and forces the user to re-query.

- Delegate: "What did I do this quarter?" (git + memory + 2 templates, synthesis, read-only)
- Inline: "Show application status" (1 source, raw rows needed, likely follow-up edit)

Reduce output first with `--fields`/`--count`/`--limit`. Delegation is a fallback for what's
left after that — not the first line of defense.
