# Find shared operations that whole-function similarity misses

Use an extra discovery comparer when ordinary TF-IDF retrieves the wrong neighbours, or misses a useful
operation inside otherwise different functions. A comparer proposes **two complete functions to inspect**.
The configured judge decides whether there is an operation worth sharing, and the existing budget decides
whether that question is asked.

Start with the existing TF-IDF exploration route. Add one extra method for a measured gap:

| Your problem | Method to try | Why it might help | Important limit |
| --- | --- | --- | --- |
| A Python helper's work is repeated inside a larger workflow | [Operation blocks](operation-blocks.md) | Compares complete statement regions, so unrelated surrounding work has less influence | Needs several concrete shared operations; tiny helpers and other languages are outside its current scope |
| Functions use different vocabulary, or useful descriptions accompany short implementations | [Offline CPU embeddings](cpu-embedding.md) | A pretrained model puts text into a learned vector space | The current encoder sees only the first 256 wordpieces; semantic similarity is not proof of duplicate behavior |
| A candidate is found but never judged | Inspect the campaign budget and admission order | Another retrieval method cannot by itself fix budget loss | Extra candidates compete for the same allowance |
| A judge identifies shared work but scores it below the reporting rule | Inspect the actual answer, policy and controls | This is a judging/reporting issue | Raising retrieval scores will not repair that answer |

Neither extra method is enabled by default. The block route has a source-reviewed, diagnostic example of
helper reuse beyond the explicit TF-IDF20 route. The tested CPU route has not demonstrated an additional useful
report over that wider baseline. CPU embeddings are therefore an experimental option for a repository-specific
comparison, not the recommended next step for every adopter.

## Start with one extra route

In the adopting repository's `.dry-lint.toml`:

```toml
[discovery]
enabled = true
comparers = [
  { use = "tfidf", neighbours = 20, min_similarity = 0.35, min_similarity_small = 0.35 },
  { use = "operation-blocks", neighbours = 1 },
]
```

The normal baseline still runs first. This explicit list then keeps TF-IDF exploration and appends at most one
previously unseen eligible block candidate per changed function. An explicit list **replaces implicit
exploration**, so omitting its TF-IDF entry changes your baseline too. This example does not change the judge,
reporting threshold or budget.

To test CPU retrieval instead, replace the second entry with the CPU example in its setup guide. To test both,
list TF-IDF, blocks, then CPU, each extra with `neighbours = 1`. The first route to propose a pair owns its score;
later routes skip it before consuming their extra slot. Two extras still share the same campaign allowance.
This order is a configuration example, not a measured guarantee that combining them improves recall.

Run detection without provider calls:

```bash
dry-lint detect --root . --base origin/main --out candidates.json
```

Inspect complete candidate functions, their `comparer`, `similarity`, `lane` and `filtered` fields. A block or
embedding score is specific to that representation: `0.8` from one is not the same evidence as TF-IDF `0.8`.
Same-file pairs can appear in discovery even though ordinary baseline retrieval excludes them. Self pairs,
settled pairs and adopter exclusions retain their core handling.

## Decide from a paired repository trial

Use the same immutable base/head, source scope, judge configuration and budget for baseline and treatment.
Keep an independent ledger for each. Compare which **useful reports** were added, which previous useful reports
were lost, and which extra reports were related or separate. Preserve missing or invalid answers as unknown.
Count reused cached answers at the normal logical cost in each arm; physical provider spending is a different
measurement.

A quick inspection of a few interesting candidates is useful for development. It is not evidence of improved
repository-wide precision or recall. The [research overview](tfidf-enrichment-research.md) describes the wider
evaluation problem; each method guide explains its current measured boundary and operational costs.
The [research results index](research-results.md) links the separate studies, runnable evidence, and decisions.
