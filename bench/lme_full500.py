#!/usr/bin/env python
"""LongMemEval-S full-500 offline retrieval eval over notionmemory's shipped index.

Protocol mirrors agentmemory's benchmark/LONGMEMEVAL.md:
  - per question: fresh index over its own haystack sessions (~48-54)
  - query with the question text
  - recall_any@K: does ANY gold session id appear in top-K?

No LLM, no network, no Notion writes — this measures the shipped local-index
ranking (`mem_index.build` + `mem_index.search`), the component that determines
`recall`'s ordering. Doc construction mirrors the live adapter + `remember()`:
session content = "[role] text"-joined turns; title = first line (markdown-
stripped, <=200 chars); concepts=[]; strength=7 (remember default). Search uses
the shipped relevance gate (min_score=1.0) — gated-out golds are honest misses.

Usage:
  python bench/lme_full500.py /path/to/longmemeval_s.json [out.json]

Dataset: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned
(or the original LongMemEval-S release — same 500-question structure).
"""
import json
import re
import sys
import time
from collections import defaultdict

from notionmemory.skills.memory import mem_index

K_MAX = 20


def flatten(turns):
    return "\n\n".join(f"[{t['role']}] {t['content']}" for t in turns)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    data = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "lme_full500_results.json"
    qs = json.load(open(data))
    rows = []
    t0 = time.time()
    for i, r in enumerate(qs):
        mems = []
        for sid, sess in zip(r["haystack_session_ids"], r["haystack_sessions"]):
            content = flatten(sess)
            first_line = (content.strip().splitlines() or [""])[0]
            title = re.sub(r"^#+\s*", "", first_line).strip()[:200] or sid
            mems.append({"id": sid, "title": title, "content": content,
                         "type": "fact", "concepts": [], "strength": 7,
                         "status": "Active", "project": "", "last_edited": ""})
        idx = mem_index.build(mems)
        hits = mem_index.search(idx, r["question"], limit=K_MAX, min_score=1.0)
        ranked = [h["mem_id"] for h in hits]
        gold = set(r["answer_session_ids"])
        first = next((j + 1 for j, sid in enumerate(ranked) if sid in gold), 0)
        rows.append({"qid": r["question_id"], "type": r["question_type"],
                     "n_sessions": len(mems), "first_gold_rank": first})
        if (i + 1) % 50 == 0:
            r5 = sum(1 for x in rows if 0 < x["first_gold_rank"] <= 5) / len(rows)
            print(f"{i+1}/{len(qs)}  R@5 so far={r5:.3f}  ({time.time()-t0:.0f}s)",
                  flush=True)

    def recall_at(k):
        return sum(1 for x in rows if 0 < x["first_gold_rank"] <= k) / len(rows)

    mrr = sum(1 / x["first_gold_rank"] for x in rows if x["first_gold_rank"]) / len(rows)
    summary = {"n": len(rows), "R@5": recall_at(5), "R@10": recall_at(10),
               "R@20": recall_at(20), "MRR": mrr, "elapsed_s": time.time() - t0}
    by_type = defaultdict(list)
    for x in rows:
        by_type[x["type"]].append(x)
    summary["by_type"] = {
        t: {"n": len(v),
            "R@5": sum(1 for x in v if 0 < x["first_gold_rank"] <= 5) / len(v),
            "R@10": sum(1 for x in v if 0 < x["first_gold_rank"] <= 10) / len(v)}
        for t, v in sorted(by_type.items())}
    json.dump({"summary": summary, "rows": rows}, open(out, "w"), indent=2)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
