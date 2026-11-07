# Public-pin regression extension — canonical PR115 addendum

Exact-source replay closes the earlier Due/pytest coverage gap without changing the observed outcome of either fallback: **zero gained and zero lost funded labeled pair/background outcomes** for the complete-helper and complete-statement CPU recipes. Publish this extension once with PR115; PR116 can link to this same report and data. This is older observed regression evidence, not a new holdout or a new judge evaluation.

The original missing-source claim searched registered clone attempts. Root subsequently acquired nine exact public commits. This separate extension verified 21,950 native function occurrences in 14 frozen backgrounds, with no missing or ambiguous native source. Due's configured and diagnostic scopes remain distinct. The historical experiments and their recordings were not rewritten.

The 75 inventory rows include lineage repeats: Due has 17 positive and 23 separate rows; pytest-selective has 16 positive and 4 separate rows; pytest-obligation has 6 positive, 6 separate and 3 borderline rows. They map to 115 row/background combinations, or 230 directional records per method. Tables deduplicate lineage within `(method, background, label, pair_id)`: 87 pair/background units and 174 directions per method. Revisions and scopes are correlated; these counts are not independent sample sizes. The full 617-row / 79-background inventory is not claimed as evaluated here.

The comparison freezes production Python source at `73709fdbe884c107b665400a186cb71caecc03f7`. Both arms preserve the original full-background sparse fit, source order, scope, query self-exclusion and preceding TF-IDF routes. The helper adds a bounded complete body only when eligible and only after the original blocks route abstains. CPU uses the same offline pinned MiniLM prefix vectors; its fallback adds at most two complete native statement views and runs only after the original prefix route abstains. [Exact policies](provenance/policies.json), [all source pins/scopes](data/contexts.jsonl), and the [unchanged actual harness](harness/) are included. The helper measured here is research recipe v1; this does not independently establish parity with a later production patch.

[Results and quantified score-floor/same-file tables](TABLES.md) keep every revision, scope and label separate. Funding means estimated exposure under a cold $0.04 single-function-query budget, using the recorded normal-price paired estimate. It is neither an emitted duplication report nor paid judge execution. A separate-labeled pair being funded is therefore an exposure, not a false emitted report. No providers ran. Materialization took 55.1 seconds, blocks replay 31.4 seconds, CPU encoding 335.5 seconds and CPU replay 13.7 seconds; these are historical measurements, not replay timings.

## Two worked cases

**Reply lifetime before and after consolidation.** At pytest-obligation `d39f77ea`, `mongodb_reply_breaker` and `redis_reply_breaker` each create a counter, enter a watcher, yield the counter through the body, then restore the watcher. The inherited label is duplicate. At `389c5bb8`, both adapters delegate this lifetime handling to `counted_reply_breaker`; the inherited label is separate because that operation is already shared. The adapters retain their MongoDB/Redis-specific watcher and reply types. We include both revisions' complete functions, their complete containing files, and the new complete helper with pinned Apache-2.0 licenses in [worked-cases](worked-cases/manifest.json).

| Revision / inherited label | Query lengths (two directions) | TF-IDF score | Raw ranks | Applicable floors | Paired funded directions, original → fallback (both methods) |
|---|---:|---:|---|---|---:|
| `d39f77ea` / duplicate | 10, 8 | 0.812810 | 1, 1 | 0.5, 0.5 | 2 → 2 |
| `389c5bb8` / separate | 4, 2 | 0.856231 | 1, 1 | 0.3, 0.3 | 2 → 2 |

All four directions are cross-file and funded by the preceding TF-IDF route; the blocks region trace has no eligible query region. A higher post-consolidation retrieval score does not reverse the separate label. This is a concrete reason to preserve the distinction between retrieval, useful extraction, and a duplication verdict.

**Snapshot functions with a high rank but insufficient sparse score.** At pytest-selective `ae130637`, `worktree_snapshot` and `snapshot_working_tree` score 0.309721, with raw nonself ranks 1 and 3. Both the ordinary 0.5 and wide 0.35 floors exclude them. Both blocks recipes miss the pair because an endpoint has no eligible region. The original CPU prefix scores 0.801161, ranks the counterpart first in both directions, and funds it before the new CPU fallback is consulted. This is preserved original-CPU coverage, not a fallback gain. The package includes exact full sources and its pinned Apache-2.0 license too.

These results support closing the source-coverage gap while retaining the recipes as opt-in research. They do not demonstrate new useful recall. Earlier synthetic checks show the helper is active, preserves original winners and retains full cleanup/exception evidence; the source-backed extension tests regression preservation.

## Recompute tables without the corpus or a model

From this package directory, using Python 3.11+ and only its standard library:

```bash
python3 -I replay.py --out replayed --verify
python3 -I test_replay.py
```

`replay.py` reads the labeled pair and directional recordings in `data/`, recomputes funded pair counts, gains/losses, directional stage counts, raw-rank bands and the score-floor/same-file table, and writes six JSONL/CSV tables. `--verify` compares the newly computed tables with the included expected outputs. It does not merely check hashes. The test also mutates one recorded outcome, proves the gained count changes, and proves expected-table verification fails. It runs a relocated copy under Python isolated mode to avoid importing the lab checkout.

The recordings preserve exact source IDs, mappings, body hashes, scores, ranks, labels and first losses. CPU per-function view text was removed from the public recordings to avoid reproducing the corpus; only the licensed worked-case full source is copied. This does not affect any replayed table. [Export provenance](provenance/export.json) records original and exported hashes and this transformation. Source labels are inherited historical observations, not newly adjudicated truth; original lineage IDs are retained.

## Full native reconstruction is a different operation

**The frozen full corpus is unavailable in this package.** There are no complete BenchBackground payloads, native function caches, vectors, SQLite cache or encoder weights here. The worked-case source cannot reproduce global IDF or full competitor ranks. The portable command above recomputes tables from recorded outcomes; it does not rerun extraction or retrieval inference.

[Full native rerun requirements and exact commands](NATIVE-RERUN.md) require the external immutable 617-row/79-background inventory, all 14 exact sparse backgrounds, the root-acquired Git objects, existing offline MiniLM artifacts, and the recorded parser/numeric environment at their documented locations. `native_rerun.py` verifies those dependencies and stages the unchanged harness into a new output directory. Never invoke the archived `harness/reproduce.sh` directly: it retains the original absolute lab location for provenance. No downloads, providers, judges or production writes are needed for either supported replay level.

[Licenses and attribution](licenses/provenance.json), [historical-output snapshot](historical-output-snapshot.json), and `validation/historical-immutability.json` bind this package to unchanged older evidence.
