# Preserve the background of retrieval goldens

A pair's source is enough to ask a judge what it means. It is not enough to reproduce TF-IDF retrieval.
The surrounding repository determines token document frequencies, the common-token cutoff and competing
neighbors. Indexing only the golden snippets measures a different retrieval problem.

Keep a `BenchBackground` beside each pinned corpus revision. Its versioned, compressed format preserves:

- Repository and exact source revision, include/exclude scope, Python version, extractor choices and the
  existing extraction-contract fingerprint.
- Every function's qualified identity, source SHA-256 and sparse token counts, in corpus order.
- Raw document frequencies, including tokens rejected by `max_df`, and the cutoff itself. The number of
  documents is the function count; frequencies count functions, not files or token occurrences.
- A digest covering the payload. Loading validates that document frequencies agree with the sparse rows.

Raw counts preserve sublinear term frequency. Document frequencies reproduce smoothed IDF. Both are needed;
document frequencies alone cannot reproduce neighbor competition. Source bodies remain in the pinned repo and
gold pairs, rather than being copied into the sparse snapshot. Token names still reveal repository vocabulary,
so private snapshots stay with private goldens.

## Capture and replay

Use the same Python/parser environment as the experiment. Due's snapshots in this PR were captured with
Python 3.14; older parsers cannot reproduce all of its function syntax. The default command reads scope from
the requested revision's configuration, not the current working tree:

```bash
uv run python scripts/freeze_bench_background.py --root /path/to/repo \
  --repository owner/repo --revision FULL_COMMIT_SHA --out /path/to/background.json.gz
```

`--diagnostic` includes tests and scripts, excluding only migrations. It is a separate corpus from configured
scope, not an approximation of it. `--max-df` overrides the cutoff; otherwise the command uses the pinned
comparer's `max_df` option or the standard 0.3 default. Preserve diagnostic and configured snapshots under
different paths. No repository source code is executed during extraction.

```python
from pathlib import Path
from dry_lint.bench_background import BenchBackground

background = BenchBackground.decode(Path("background.json.gz").read_bytes())
index = background.index()
query = background.documents[0]
neighbors = [
    (background.documents[position].id, score)
    for position, score in index.similar(query.tokens(), exclude={0}, limit=3)
]
```

This replays frozen TF-IDF weights and raw neighbor ranks with the existing weighting implementation.
It does not apply source-level exclusions, forwarding-wrapper rules or judge budgets; those require the
matching source/configuration and normal detector. The regular `load_gold`/CLI does not automatically switch
corpora when it encounters a background manifest. Research runners must explicitly load the matching revision.
Do not combine different revisions into one index or use after-refactor text to enrich before-refactor queries.

The [Due panel](../examples/due-consolidation-gold.toml) references a manifest of five full diagnostic
backgrounds, each with 2,336–2,368 functions. Fixture tests validate manifest hashes, sparse counts, revision
coverage and every golden source digest. Synthetic integration tests verify that full-background weights and
competitor ranks round-trip and that capture honors pinned scope despite a changed working tree.

The [pytest-selective panel](../examples/pytest-selective-gold.toml) also retains its 272-function before and
270-function after backgrounds. Its legacy snippets normalize class indentation, so the manifest records
source-derived AST fingerprints alongside exact source hashes. These hash sorted JSON AST fields with absent
values and empty lists omitted, so Python's changing `ast.dump` formatting does not invalidate identical syntax.
Fixture tests check syntax equivalence without
rewriting those snippets or pretending their formatting is verbatim. The original private 48-positive trial
also has frozen backgrounds and gold-to-background references in its private artifact directory.
The [pytest-obligation panel](../examples/pytest-obligation-gold.toml) retains separate 1,657-function before
and 1,656-function after backgrounds, using the same source/syntax checks. Its mixed revisions remain separate;
capturing them does not add its labels to the original 48-positive trial. The hand-written calibration examples
in `examples/gold.toml` have no source-repository background to preserve.

The [public operation panel](../examples/public-gold/README.md) retains full diagnostic backgrounds for
T3 clipboard and OpenCode request-normalization before/merge pins, plus separate SDK dead-code evidence.
Its four active rows label narrow operations, not their enclosing functions. Exact snippet-to-extraction
mappings flag scope mismatches; native JSONL import does not turn a partial-operation label into a
whole-function label or silently replace full-corpus tokens with snippet tokens. Same-function regions,
unextracted decoder bindings, dead-code duplicates and disputed labels remain outside its active panel.

When changing tokenization, retain the old snapshot as the baseline. Re-extract the same pinned source into
a new candidate snapshot and compare both. Replacing the old counts in place would erase the evidence of
what changed. Keep benchmark outcomes and ad hoc audit dumps outside the code repository; these sparse
fixtures are maintained benchmark inputs.

## Audit before removing tokens

Inspect frequent retained tokens, discarded tokens, singleton rates, per-family squared vector weight, and
the actual shared-token contributions of true and false pairs. Check configured scope separately: tests can
dominate both vocabulary and function names. A common domain term may distinguish important operations;
a rare test-name word may contribute almost no behavior. Frequency alone is not a stop-word policy.

Run controlled ablations with the same pinned corpus, labels and per-PR budget. Report which positives are
gained and lost, not only the total. Validate added candidates with the unchanged judge, and reserve whole
PR/repository families for holdout. See [the research results](tfidf-enrichment-research.md) for the initial audit
and the resulting fixed ablations.
