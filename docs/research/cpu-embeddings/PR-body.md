## TLDR

A local encoder can find shared-operation candidates missed by three lexical neighbors, but the tested recipe did not demonstrate a useful added report over wider lexical search. This PR publishes original code, exact selected source, prompts/answers and runnable replay so that candidate gains, judge misses and the disputed Windows report are reviewable without another experiment. Keep the original encoder optional and cached; do not promote the revised reranker.

```text
BEFORE: full function -> TF-IDF top3 (+ separate wider top20 control) -> judge
AFTER:  same baseline -> cached CPU cosine candidates -> optional dense20/token rerank -> judge
```

| Measured quantity | Before | After | Interpretation |
|---|---:|---:|---|
| Added positive contexts over top3 (higher preferred, /78) | Original CPU: 15 | Revised CPU: 25 | 11 gained and one prior CPU success lost |
| Added positive contexts over wide lexical search (/78) | Wide baseline | Original CPU: 0 | Narrow-baseline gain is not unique recall |
| Revised selected R2 report projections (/64) | TF-IDF20: 1 | CPU: 1 | Same unsupported ID-policy report |
| Source-supported useful added reports | 0 demonstrated | 0 demonstrated | Cache operation reached by both, missed by Claude |

The actual panel is 207 distinct records in 16 source-compatible backgrounds, 223 pair/background contexts, with 78 accepted positives, 120 accepted negatives and 25 unresolved contexts. R2 has 1 report, 35 nonreports and 28 unknowns; that report is related by source review. The useful cache pair is reached by CPU and TF-IDF20. Windows remains disputed. Fresh actual spend is $0.28323212 and $0.22441836, distinct from simulated $0.04 admission.

Read the [canonical report](https://github.com/gigaverse-app/dry-lint/blob/research/study-cpu-embeddings/docs/research/cpu-embeddings/README.md), [original answers](https://github.com/gigaverse-app/dry-lint/blob/research/study-cpu-embeddings/docs/research/cpu-embeddings/CASES.md), [original algorithm/configuration](https://github.com/gigaverse-app/dry-lint/blob/research/study-cpu-embeddings/docs/research/cpu-embeddings/data/original/README.md), [portable reproduction](https://github.com/gigaverse-app/dry-lint/blob/research/study-cpu-embeddings/docs/research/cpu-embeddings/REPRODUCTION.md), and [full rerun manifest](https://github.com/gigaverse-app/dry-lint/blob/research/study-cpu-embeddings/docs/research/cpu-embeddings/FULL-RERUN.json). Exact public background matches use the separate pinned [goldens acquisition contract](https://github.com/gigaverse-app/dry-lint/blob/research/study-cpu-embeddings/docs/research/cpu-embeddings/CORPUS.md); private/missing inputs are not treated as reproduced. Original provenance hashes remain distinct from sanitized publication hashes.

Validation: clean-copy recorded replay, original selected-algorithm replay, local links, source/request hashes, secret scan including compressed source, and private-payload boundary checks. No production/CI changes, provider calls, credentials, agents or new experiment. Root owns creation/push of this separate research branch.
