<p align="center"><b>English</b> | <a href="EXAMPLES.ko.md">한국어</a></p>

# Examples

None of these ship built-in. Each is one of **your own** Notion databases or pages,
registered once with the **templates** skill — and, for the richer ones, an **attached
prompt** that tells the agent how to author into it. After that you just talk, and the
agent follows your spec.

Every card below has two parts: a **base template** (a public Notion template you can
duplicate into your own workspace) and, where used, the **attached prompt** — the
notionmemory layer that lives in your config, not in the Notion page. The prompts below are
translated from the author's Korean originals (the [Korean version](EXAMPLES.ko.md) keeps
them verbatim); adapt them freely.

---

## 📚 A reading list that tracks itself

*Plain DB — no prompt.*

> *"Add this paper to my reading list — DOI 10.1088/…, tag it exoplanets, status To-read."*

The agent writes the row into your tracker DB **by property name** — status, tags, DOI — and
later *"show me everything still unread"* filters it back by those same properties. This is
the baseline templates move: register any Notion DB and CRUD it in plain language, with no
schema wiring on your side.

- **Base template:** [Research Paper Tracker](https://www.notion.com/templates/research-paper-tracker)
- **Attached prompt:** none — property CRUD only.

---

## 💡 An idea bank that researches itself

*Attached prompt.*

> *"Log this idea: a CLI that turns shell history into a runbook."*

Instead of saving a bare title, the agent follows the template's prompt and fills the page
body across four sections — **the problem & who it's for**, a real **web search of similar
tools and reusable libraries**, a critical **feasibility & risk** read (it's told to name at
least one reason it *won't* work), and **next steps** — then sets Feasibility / Impact /
Effort to match its findings. Say *"just stash it"* and it skips the research and only files
the row.

- **Base template:** [Idea Bank Database](https://www.notion.com/templates/idea-bank-database)
- **Attached prompt:** ↓

<details>
<summary>Attached prompt (English, translated from the author's Korean original) — click to expand</summary>

```text
When registering a new idea in this template (Idea Bank), don't just write one line and stop —
research the four axes below yourself and fill in **the properties + the page body**. The goal
is to turn a "passing thought" into "a form you can judge and act on." (If the user says "just
stash it quickly," fill only the properties and skip the body research.)

## Procedure
1. Create the row with `add`, filling the properties, and get back the **row id**.
2. Attach the four body sections below to that row id with `block add --markdown-file <path>`
   (or `-` = stdin). The body contains links and code fences, so never pass it to the shell via
   `--markdown "..."` directly — always use a file/stdin.
3. Adjust the evaluation properties (Feasibility · Potential Impact · Effort · Priority) to match
   what the research turned up.

## Filling the properties
- Idea Name: a short, searchable name / Description: the core value in one line
- Category (Tech · Business · Education · Lifestyle, etc.; create a new one only if none fits,
  preferring existing ones) / Tags
- Date Added, Inspiration Source, Link (if there's a source)
- Status: default `Spark` / Next Step: the first thing to validate, in one line
- **After research** Feasibility (Easy/Moderate/Challenging/Unknown) · Potential Impact
  (Small/Medium/Big/Game-Changer) · Effort Estimate (a number, e.g. person-weeks) — keep these
  consistent with the body evidence below.

## Four body sections (## headings verbatim; concise, objective)

### ## 💡 Fleshing out the idea
- The problem being solved / the target user (who feels the pain, and why)
- Core behavior — spell out how it works in a paragraph or two (input → processing → output)
- The MVP scope and the definition of "it worked"

### ## 🔍 Market research
- Similar services/products: name + link + a one-line note (at least 2–3, actually searched on
  the web). If none, state "not found."
- Reusable open source / models / libraries / APIs: name + link + what it does for you.
- Differentiator: why the existing options fall short / what this idea newly provides.

### ## ⚖️ Viability & assessment
- Technical difficulty, the data/resources/cost needed, the expected effort.
- Major risks, uncertainties, regulatory/privacy concerns (if any).
- The rationale for Feasibility / Potential Impact / Effort, one line each — matching the property
  values above.
- **Critically**: always write at least one downside or reason it might fail (no overselling).

### ## 🚀 Expansion & improvement
- Next step: one smallest, fastest way to validate.
- Directions to grow/expand (features, market, monetization, etc.).
- Other ideas it could combine with — if there's a related item inside the Idea Bank, name it.

## Rules
- Market research, similar services, and open source must be **actually verified with the agent's
  own web search/tools**. If it's a guess, mark it "(estimated)"; if you couldn't verify it, say so
  honestly as "unverified." Don't make things up.
- The tone is a cool-headed review note, not a sales pitch. Links must be real URLs only.
- If the user asks to "flesh out / research" an existing row: `read` that row to check the sections
  already there, and fill or update the four sections above in the same format (don't create
  duplicates).
```

</details>

---

## 📁 A portfolio that reads your actual code

*Attached prompt.*

> *"Add my side project to the portfolio."*

The agent inspects the **real repo** — dependencies with versions, directory layout,
`git log` for the development arc and the fix/refactor commits, CI and Docker files,
screenshot folders — reports what it found, asks you the few things code can't answer
(motivation, real metrics, deploy status), then authors an **evidence-based** project card
with real snippets and cropped figures. It's explicitly forbidden from writing anything not
grounded in the code or commits, so there are no template-filler guesses.

- **Base template:** [Personal Portfolio](https://www.notion.com/templates/personal-portfolio)
- **Attached prompt:** ↓

<details>
<summary>Attached prompt (English, translated from the author's Korean original) — click to expand</summary>

```text
Each project page in this portfolio must be researched and written separately,
following the order below.

━━━━━━━━━━━━━━━━━━━━
[Step 1] Research

Check all of the following:
- README, dependency files like package.json / requirements.txt (with versions)
- Directory structure and the role of the main modules
- git log --oneline for the overall development arc and the first/last commit dates
- fix / refactor / perf / hotfix commits
- .github/ workflows, Dockerfile, docker-compose, infra config files
- git remote get-url origin for the repository address
- folders where images might be gathered — assets / images / screenshots / docs / static /
  public, etc. — and image paths in the README

Output the research first as a "📋 Research findings" section:
1. What service this project is
2. Tech stack (with versions) — only what's confirmed in the actual code
3. The list of main features and each feature's entry-point file
4. The 1–2 pieces of logic that look most carefully built, with their file paths
5. Traces of technical problem-solving found in commits/code (with specific commit hashes)
6. Screenshot/demo image file paths found (if none, state "none")
7. Parts you can't judge → a list of questions

━━━━━━━━━━━━━━━━━━━━
[Step 2] Items needing confirmation

Reorganize the question list from #7 above into a "❓ Needs confirmation" section.
(e.g. project motivation, real performance numbers, whether it's deployed, future plans)
Once I answer, you'll fold that in and update the Step 3 document.

━━━━━━━━━━━━━━━━━━━━
[Step 3] Writing the document

It's going into Notion, so don't use GitHub-only syntax (badges, <details> tags).
Write the sections below in this exact order; keep the heading even when there's no content,
marking it "[needs confirmation]."

## Project info
   - Period: based on the first/last commit dates in git log
   - GitHub: remote URL
   - Deploy link: check the README or workflows; if none, [needs confirmation]

## One-line intro
   - Hero image: directly under the One-line intro heading, before the intro sentence, always
     insert one image that represents the project. It's used as the portfolio card preview, so
     choose it distinctly from the demo screenshots. If no hero image can be found, use the one
     demo image that best shows the project's character.

## Demo
   If you found image files in Step 1, insert their paths as markdown images.
   If not, leave only the placeholder "![demo screenshot - insert manually]".
   Don't fabricate image files.
   Put the demo screenshots inside a collapsible toggle, collapsed by default
   (so the document doesn't get long with screenshots). A toggle can't be made
   with standard markdown, so put only the "## Demo" heading in markdown, then
   create a toggle block and nest the images as its children (calling the Notion
   API directly). Keep the hero image (One-line intro) and any comparison images
   outside the toggle.

## Overview
   - Why you built it (2–3 lines)
   - How you solved it (2–3 lines)
   - If there's an approach that differs from existing methods or similar services, 1–2 lines.
     Only write it when backed by code; otherwise omit this item.

## Tech stack
   Table form: Category | Technology (version) | Role
   Categories are Frontend / Backend / DB / Infra
   In the "Role" cell, write only what that technology handles in this project.
     e.g. Redis 7.2 | session storage and token whitelist
     e.g. Prisma 5.x | ORM, schema migration management
   Don't explain why it was chosen or its advantages.
   Items where the tech choice involved real deliberation go in the [Technical decisions] section.

## Architecture
   Draw the system diagram as a Mermaid code block.
   (flow between client / server / DB / external APIs)
   Notion supports mermaid code blocks, so use it as-is.
   Only draw components confirmed in the actual code.

## Main features
   3–5. For each item:
   - Feature name + one-line description + entry-point file path
   - One line on any implementation quirk (only when it differs from a typical implementation)

## Core logic
   Explain the 1–2 most carefully built parts in depth.
   - The flow step by step (use a Mermaid sequenceDiagram if complex)
   - Why a simple approach wouldn't work, what constraints there were
   - Quote the key code snippet within 10 lines (specify the file path)
   Pick the parts you actually thought through, not routine CRUD.

## Technical decisions
   2–3 points where the design involved deliberation.
   Structure: "what you chose → what alternatives existed → why you picked this."
   Note the file paths or commit hashes that back it.

## Troubleshooting
   1–3. Each in four parts: problem → cause → fix → result.
   Note the commit hashes or file paths that back it.

## Retrospective
   2–4 paragraphs, written in plain declarative style ("did X").
   - What you newly learned from this project (technical or a design judgment)
   - This project's limitations (what's lacking) and why
   No self-evaluation or sentiment ("it was a good experience," "I grew a lot").
   Write only retrospection on concrete technical judgments.

━━━━━━━━━━━━━━━━━━━━
[Optional sections] Add only when applicable; otherwise drop entirely

- ERD: if there's a DB schema with complex table relations, as a Mermaid erDiagram
- API spec: if there's a REST API, only the 3–5 key endpoints as a table
   (method | path | description). Don't list them all.

━━━━━━━━━━━━━━━━━━━━
[Style rules]

Keep the style in a terse, noun-ending register.
- "did X (polite)," "is X (polite)" (X)
- "does X," "composed of," "applies X," "adopts X approach" (O)
- Noun-form endings allowed ("a Redis-based cache layer")
Only the [Retrospective] section uses plain declarative style ("did X").

Write the document from the stance of "introducing a project I built."
Don't use third-party, repo-analyzing phrasings like "according to the README,"
"looking at the code," "on inspection," "is described as."
Don't note the file paths / commit hashes / sources you used as evidence in parentheses in the body.

━━━━━━━━━━━━━━━━━━━━
[Writing rules] — must follow

1. Never write facts not confirmed in the code / commits / config.
2. Only write performance numbers (response time, throughput, user counts) when a backing file or
   measurement record actually exists. Otherwise leave "[needs confirmation: measurement]."
3. Don't invent troubleshooting or technical decisions.
   Only what's actually confirmed in the commit history or code.
   If you found none, leave "[needs confirmation: tell me the issue you remember]."
4. Prefer "adopted X approach because Y" over "implemented X," so the decision shows.
5. No overuse of adjectives like "efficient," "powerful," "optimized."

━━━━━━━━━━━━━━━━━━━━
[Final check]

After writing the document, always verify and fix the following.
- Check that no commit hashes, file paths, or source references remain inside parentheses
- If any such notes exist, delete them, and remove the file-path comments in code snippets too
- Technical decisions / troubleshooting state the judgment and result, not a list of evidence
- General parenthetical notes needed to understand the content — like period, version, product
  name — may stay
```

</details>

---

## 📝 Lecture notes from raw slides

*Blueprint — prompt-only, reused per subject.*

> *"Turn this lecture PDF into notes."*

A prompt-only **blueprint** stamps out a fresh, structured note each time. You read the
PDF/slides; the agent writes a personal knowledge note **in the source's own language** —
reorganized by concept rather than slide order, key terms glossed on first use, important
figures cropped in beside the paragraph that explains them, and nothing invented that isn't
in the source. Because it's prompt-only, there's no page to duplicate — you recreate it by
attaching the prompt below to a `lecture-note` blueprint.

- **Base template:** none — it's a prompt-only blueprint (no Notion page).
- **Attached prompt:** ↓

<details>
<summary>Attached prompt (English, translated from the author's Korean original) — click to expand</summary>

```text
Read lecture, paper, or study material (PDF/image/slides) and organize it into a personal
knowledge note that's still useful months later when you look again. Don't pretend to know
information that isn't in the material.

[Authority & evidence]
- The source material is the only factual ground. Don't add background knowledge, examples,
  quotes, performance numbers, author intent, or causal explanations from the model's memory.
- Restructure and paraphrase boldly for clarity, but preserve the source's conditions, exceptions,
  uncertainty, formulas, terminology, and direction of comparison.
- If a reading is uncertain, don't guess to complete it — omit it or mark it uncertain. Don't insert
  meaningless misrecognized characters.

[Terminology]
- For key technical terms, theorems, definitions, and variable types, give both the English original
  and the Korean on first appearance: `Random variable (확률변수)`. Use the paired form at headings,
  definition paragraphs, table labels, and the first appearance in each section.
- If the source gives no Korean equivalent, don't force a translation — leave the original term and
  abbreviation as is. Preserve the source's casing, abbreviations, and math notation.

[Structure — matched to the material type]
- Infer the material type from the source; don't force every document into the same frame.
  - Lecture/concept notes: scope → prerequisite concepts → key concepts and their relations →
    examples actually in the source → limitations/common confusions → a concise synthesis.
  - Paper: bibliographic info → research question → motivation/gap → method/assumptions →
    experimental setup → results → limitations → relation to the field.
  - Experiment/assignment/project: goal → setup/variables → procedure → observations/results →
    interpretation grounded in the results → failures/uncertainty → next steps stated in the source.
- Common: open with a 2–4 sentence overview stating the scope, the key question, and how the
  sections connect. Reorganize by **concept and argument structure**, not slide/page order. Define a
  term on first use, then explain its mechanism, conditions, and relation to adjacent concepts. Use
  paragraphs for reasoning, and lists only for genuinely parallel items, procedures, or checklists.
  Include examples only when they're in the source (no fake examples). End with a synthesis of the
  conclusions that follow from the source; don't tack on a generic motivational conclusion. Don't
  create empty headings or headings that are just noun fragments.

[Style & sentence quality]
- Describe **the subject directly** rather than reviewing the material itself. Don't make the lecture,
  document, slide, or presenter the subject. Instead of source-reporting phrasing like "this lecture
  …," "the slide shows …," "this material …," write direct statements about the subject like "X is
  defined as …," "in the figure, X …."
- Default tone: a calm textbook register. End sentences in a declarative register, and don't use
  reader-addressing or exclamatory/exaggerated expressions like "let's try," "let's look," "let's
  remember." State things plainly, fact-focused, without filler modifiers.
- One paragraph carries one role. Keep it to 1–2 sentences, roughly under 220 characters, and break
  with a blank line when moving definition→implication, condition→example, example→interpretation, or
  into a contrast/exception/calculation. Prefer direct sentences of roughly 12–25 words; don't cram
  multiple definitions, conditions, formulas, and conclusions into one sentence. Make transitions
  reveal the actual relation (cause, contrast, premise, specialization, sequence). Restore OCR line
  breaks by meaning before use, and don't carry slide fragments over as if they were sentences.

[Format]
- Choose markdown that fits the content (Notion converts it into blocks). Keep key definitions/
  theorems in a separate short paragraph and bold only the key term — don't mechanically prepend
  "Definition —" prefixes or use blockquotes.
- Put short defining expressions in inline LaTeX; put long derivations in a standalone `$$...$$` block
  right after the explanatory paragraph. After a formula, don't just list the symbols — explain the
  relation and conditions of use in 1–2 sentences.
- Use **tables** for comparisons/attribute summaries, **numbered lists** for order/procedure/
  algorithms, **bullets** for parallel enumerations, language-tagged **code blocks** for code, and
  **checkboxes** for to-dos.

[Figures]
- Crop important figures/diagrams/charts from the source and insert each **right after** the paragraph
  that interprets it. Don't pile figures at the end of the note. Don't include decorative logos/
  backgrounds, tables of contents, or pages that fully duplicate the body.
- If there are handwritten notes, don't float them separately — fold them into the related sentence.
  If handwriting is uncertain, don't guess; omit it.

[Notion output syntax]
- `[[wikilinks]]` don't render in Notion, so don't use them — connect concepts with plain sentences
  (bold the important terms).
- Headings only up to three levels `#`~`###`; list nesting only one level. Tables, blockquotes (`>`),
  checkboxes, code blocks, and formulas are supported.
- Don't use Notion slash commands (`/code`, `/table`) or HTML tags in the body — write code blocks and
  tables in markdown syntax.

[Title]
- Pull the title from the cover/first title page (not a generic filename or an invented summary). If a
  lecture number and topic title are visible, use the form `Lecture N — original title`, preserving
  the source's language and wording. Don't invent a missing lecture number or title.

[Final pass]
- Remove every claim not traceable to the source. Verify that numbers, names, comparisons, and figures
  have grounding. Fix broken sentences and abrupt section transitions.
```

</details>

---

## Build your own

Register a page or DB — *"register this Notion page as a template"* (paste the URL) — and,
when you want the agent to author into it a certain way, **attach a prompt**: set it in the
settings dashboard, or just tell the agent what the prompt should say. That's the whole
setup. See the [templates skill](../README.md#agents) for the full surface.
