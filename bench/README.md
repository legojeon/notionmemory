# Reproducing the benchmarks

The numbers in the main README's **Benchmarks** section were measured with
[agentmemory's open eval harness](https://github.com/rohitg00/agentmemory/tree/main/eval)
(label-based P@K / R@K, no LLM judge) through the thin adapter in this directory —
ingest via `notionmemory remember`, query via `notionmemory recall`, against a live,
sandboxed Notion database.

Steps:

1. Clone agentmemory and `npm install` in it.
2. Copy `notionmemory-adapter.ts` into `eval/runner/adapters/notionmemory.ts` and
   register it in the `ADAPTERS` map of `eval/runner/coding-life.ts` (and
   `longmemeval.ts` for LongMemEval).
3. Sandbox: create a dedicated config + test DB so the run never touches your real
   Second Brain:

   ```sh
   printf 'language: en\nskills:\n  memory: {}\n' > /tmp/bench-config.yaml
   notionmemory memory connect --new --config /tmp/bench-config.yaml
   ```

4. Run (from the agentmemory clone):

   ```sh
   NOTIONMEMORY_CONFIG=/tmp/bench-config.yaml \
     npm run eval:coding-life -- --adapters grep,notionmemory

   # LongMemEval-S needs the public dataset (~278MB, see agentmemory's eval/README.md)
   LONGMEMEVAL_PATH=~/datasets/longmemeval/longmemeval_s.json \
   NOTIONMEMORY_CONFIG=/tmp/bench-config.yaml \
     npm run eval:longmemeval -- --adapters notionmemory --stratify 1
   ```

5. Clean up: trash the pages in the test DB (they're plain Notion pages), then delete
   the DB in the Notion UI.

Notes: the adapter suppresses `recall`'s recency fallback (fallback rows are not
matches — fairness), scopes each LongMemEval question to its own `--project`, and
relies on `remember`'s write-through to populate the local index (no manual reindex).

## LongMemEval-S full 500 (offline)

A live full-500 run would create ~24,000 Notion pages, so the full-dataset number is
measured offline over the **shipped index code** (`mem_index.build` + `mem_index.search`
— the component that determines `recall`'s ordering; live verification preserves
candidate order). Same protocol as agentmemory's
[LONGMEMEVAL.md](https://github.com/rohitg00/agentmemory/blob/main/benchmark/LONGMEMEVAL.md):
per-question fresh index, `recall_any@K`, n=500, no LLM anywhere.

```sh
python bench/lme_full500.py ~/datasets/longmemeval/longmemeval_s.json
```

Result (2026-08-01, runs in ~5s):

| | R@5 | R@10 | R@20 | MRR |
| --- | --- | --- | --- | --- |
| notionmemory (BM25, no embeddings) | 0.946 | 0.976 | 0.994 | 0.893 |

By type: knowledge-update 1.000, single-session-assistant 1.000, multi-session 0.947,
single-session-user 0.943, temporal-reasoning 0.932, single-session-preference 0.767 —
the same "preferences are hardest" pattern agentmemory reports.
