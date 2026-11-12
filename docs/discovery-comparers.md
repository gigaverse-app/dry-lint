# Find shared operations that whole-function similarity misses

Use an extra discovery comparer when ordinary TF-IDF retrieves the wrong neighbours, or misses a useful
operation inside otherwise different functions. A comparer proposes **two complete functions to inspect**.
The configured judge decides whether there is an operation worth sharing, and the existing budget decides
whether that question is asked.

The `balanced` preset now includes TF-IDF exploration and one bounded Python operation-block candidate per
changed function. Other judging presets keep their existing behavior. Choose an additional route for a measured gap:

| Your problem | Method to try | Why it might help | Important limit |
| --- | --- | --- | --- |
| A Python helper's work is repeated inside a larger workflow | [Operation blocks](operation-blocks.md) | Compares complete statement regions, so unrelated surrounding work has less influence | Needs several concrete shared operations; tiny helpers and other languages are outside its current scope |
| Functions use different vocabulary, or useful descriptions accompany short implementations | [Offline CPU embeddings](cpu-embedding.md) | A pretrained model puts text into a learned vector space | The current encoder sees only the first 256 wordpieces; semantic similarity is not proof of duplicate behavior |
| A useful operation occurs beyond a long function's embedding prefix | [Complete statements + rank fusion](cpu-tail-rrf.md) | Represents whole tail statements and combines eligible ranks | Narrow development gain; no demonstrated shared-campaign gain; extra cold CPU cost |
| A candidate is found but never judged | Inspect the campaign budget and admission order | Another retrieval method cannot by itself fix budget loss | Extra candidates compete for the same allowance |
| A judge identifies shared work but scores it below the reporting rule | Inspect the actual answer, policy and controls | This is a judging/reporting issue | Raising retrieval scores will not repair that answer |

**Operation blocks run automatically within `balanced` when its default TF-IDF comparer is used and no explicit
discovery comparer list is supplied.** The complete-helper fallback added nine net bounded useful reports in a selected balanced-policy
comparison, alongside three net unsupported reports. That comparison used cold single-query campaigns; it does
not establish the same gain on multi-function PRs. The [method guide](operation-blocks.md#complete-helper-follow-up)
explains the additions, displaced reports and source-review limits.

The prefix-only CPU plugin has not demonstrated an additional useful report over the wider TF-IDF baseline.
The [complete-statement and rank-fusion route](cpu-tail-rrf.md) adds three independently supported useful reports
across 66 selected single-function campaigns, with three tiny reports and no lost admissions. It found no gain
in five shared campaigns, so it remains an explicit option for long-function misses. Cold encoding is expensive;
use the existing vector cache and compare full-stack report additions and losses on your repository.

## Use balanced, or choose explicit routes

For agent-reviewed discovery, start with `preset = "balanced"` in `.dry-lint/config.toml`. No comparer list is needed.
The [activation and opt-out guide](operation-blocks.md#balanced-activation-and-opt-out) explains which explicit
settings override the defaults. This chooses the balanced judge and reporting thresholds as well as discovery.

To configure the same retrieval routes independently of a judging preset, use an explicit list.

In the adopting repository's `.dry-lint/config.toml`:

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

For the complete evaluated CPU stack, use the [CPU recovery setting](cpu-recovery.md), supplying local model and
cache paths. It enables both prefix and tail retrieval with shared resources. Prefix-only CPU retrieval remains
an experimental option in its setup guide. The first route to propose a pair owns its score;
later routes skip it before consuming their extra slot. Two extras still share the same campaign allowance.
This order is a configuration example, not a measured guarantee that combining them improves recall.
Retrieval order also does **not** protect all earlier candidates' funding: the campaign scheduler orders the
combined pool using lane, priority, query fairness and similarity. New exploration candidates can displace
earlier exploration candidates. Evaluate the whole pool under the actual scheduler, not by reserving the old
stack first in a separate experimental loop.

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
