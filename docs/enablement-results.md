# Enablement: automatic balanced blocks and usable CPU recovery

This change makes bounded Python operation blocks automatic within the explicitly agent-reviewed `balanced`
preset, and turns the complete CPU recovery stack into one supported opt-in setting. Compatible CPU routes
automatically share an encoder and block preparation. Legacy credential-selected `auto` presets keep their
existing behavior. There are no judge-threshold, provider, CI or adopter-configuration changes.

The decisions have different foundations. CPU resource sharing is a measured engineering improvement with
identical output. Automatic balanced blocks is a deliberate recall/noise tradeoff supported by the earlier
selected helper study; **the new chronological replay does not demonstrate additional useful-pair recall**.
It adds one unsupported pair and reports an already-discovered tiny operation one revision earlier. The
default block route also has a substantial indexing cost. Neither observation is hidden behind the earlier gain.

## What changes for an adopter

With `preset = "balanced"`, the ordinary TF-IDF baseline and its exploration run first. If the baseline is
TF-IDF and no explicit discovery comparer list is supplied, one previously unseen eligible block candidate
per changed query is appended. Both full functions still reach the existing judge and cumulative PR budget.
Explicit floors, depth and TF-IDF options remain effective. To retain TF-IDF exploration alone, set
`discovery.comparers = []`; `discovery.enabled = false` disables discovery. See [activation](operation-blocks.md#balanced-activation-and-opt-out).

For long-function recovery, install the optional CPU dependencies and supply local pinned model files:

```toml
preset = "balanced"

[discovery.cpu_recovery]
model_dir = ".dry-lint-local/minilm"
cache_dir = ".dry-lint-local/vectors"
```

This expands to TF-IDF20/.35, operation-blocks/top1, prefix CPU/.65/top1, and complete-statement rank-fusion/top1.
It preserves the evaluated ranking, comparer identities and full-function prompts. No model is downloaded.
The [CPU guide](cpu-recovery.md) covers requirements, configuration precedence and costs. Prefix-only CPU
retrieval remains experimental; this activation recommendation concerns the complete evaluated stack.

## Paired historical result: useful timing, one false addition, no new useful pair

The comparison starts from product commit `b0abdf52706a2b715ecc7f56bc1de2ea8ee56781` and runs actual PR diffs,
full pinned source backgrounds, `Detector.candidates`, `Judging.findings`, `CampaignStore` and `Report.build`.
Each arm starts with its own cold ledger and keeps a $0.04 cap across the PR's revisions. Both use
Haiku 5.5/shared-operations/2048, .50 report/drop, .80 drift, no escalation and no retries.
These are explicit current-policy replays, not claims about the historical adopter's deployment.

| Previously evaluated cohort | Complete PRs / revisions | Report source versions, baseline → blocks | Distinct reported pairs, baseline → blocks | Independent assessment of delta |
| --- | --- | --- | --- | --- |
| Original historical histories | 6 / 27 | 10 → 11 | 8 → 8 | One tiny operation reported earlier; no new pair |
| Production-discovery histories | 4 / 20 | 21 → 22 | 18 → 19 | One unsupported new pair |
| Combined supported input | 10 / 47 | 31 → 33 | 26 → 27 | Zero new bounded-useful pairs; zero lost prior pairs or report versions |

The input inventory contains 19 PRs and 85 revisions. Seven other production histories and both regression
histories, totaling 38 revisions, lack an authenticated head-to-merge-base mapping in the supplied partial
Git exports. Retrying Git ancestry against all 38 pins recovers none. Those inputs are excluded, not misses,
negatives or successful controls. These cohorts were already evaluated; this is not a fresh-family holdout.

The two changed cases explain the result:

* Backend #5632: the treatment reports the repeated fresh-load/missing-email-campaign guard at ordinal 0;
  baseline reports that same pair at ordinal 1. Independent source review calls the remaining extraction tiny.
  This is earlier feedback, not a new independent operation family.
* AI #3296: a viewer-promotion handler and widget channel adapter both parse a channel identifier and map
  failure to HTTP 400. The actual parser already has a shared owner. Widget conversion changes channel type
  after authorization; promotion reads preserve the requested channel and enforce different access and
  pricing rules. The added report is unsupported. It is retained as a negative result.

Baseline/treatment normal ledger charges total $0.0428716/$0.0445097 across the six historical PRs and
$0.0639207/$0.0632286 across the four production PRs. Every individual arm stays below $0.04; the largest
is $0.0172499. Cached external observations are charged normal usage in every arm; native exact store reuse
follows the production rules. Physical acquisition was **73 fresh observations costing $0.0422378**, separate
from these logical charges and from coding-agent usage. No paid failures or unresolved funded questions
remain in the supported final histories. Provider scores are observations, not independent truth.

The audit corrected branch-base substitution, commit-versus-tree revision pacing, and manual report counting.
Only corrected version-2 runs contribute to the table. Source commit identity and tree pacing identity are
both authenticated. Exact source, context, prompt, model, output cap and policy constrain observation reuse;
unrendered adapter-metadata upgrades have explicit proofs. Independent source labels were sealed before
inspecting the corresponding provider scores. No manually protected ordering replaces the native scheduler.
After workers finished, the coordinator reran the independently written audit in a fresh output directory:
all 94 revision/arm states and 421 recorded judge attempts matched, including exact admission order, cache
reuse, settlement and report flags. An earlier audit retry had reused its old ledger directory; the fresh
rerun resolves that failure without changing its verification logic. The portable bundle separately reproduced
all 20 complete arms. Superseded interim receipt issues are recorded in the coordinator's artifact audit.

## Why enable balanced blocks despite the limited historical result?

The earlier helper-development comparison produced **+9 net bounded-useful reports and +3 net unsupported
reports**, including one useful report lost to budget competition. That selected panel is positive evidence
for the Python helper-use case; it is not an estimate of population recall. The new chronology provides a
check on real revision settlement and losses, but its marginal output is worse, not a recall victory.

The coordinator chooses automatic bounded blocks only for `balanced`, whose findings already require agent
review and whose purpose favors recall. This accepts the measured noise and runtime cost in exchange for
making the demonstrated helper capability available without custom comparer setup. It does not justify
changing high-precision legacy presets. Explicit opt-out and full candidate provenance remain available.
The residual-token veto and protected-first scheduler diagnostic do not ship: neither established a better
overall tradeoff. Ownership-aware judging remains a separate unproven improvement direction.

On AI #3294's 10,319-function snapshot with six changed functions, three fresh-process paired runs measured
median complete Detector construction plus candidates at **1.73s → 12.68s**, and peak process RSS at
**215 → 351 MiB**. Extraction and object loading are excluded. The output pools match the frozen replay.
This substantial overhead is a reason to choose TF-IDF-only exploration for latency-sensitive repositories.

## CPU recovery: same output, less repeated work

Compatible plugins share resources only within one detection call. Each constructor still verifies supplied
model files; resource keys bind the encoder contract and explicit cache directory. Prepared block state can
be shared, while mutable query caches stay separate. Successful and failed calls release their scope;
concurrent calls do not share it. Missing weights remain an error when the route is required.

| Corpus | Functions | Warm full-stack seconds, before → after | Warm peak RSS, before → after | Measurement |
| --- | --- | --- | --- | --- |
| T3 small snapshot | 1,601 | 8.47 → 7.65 | 390 → 299 MiB | Median of three paired runs |
| OpenHands | 2,349 | 13.57 → 10.00 | 411 → 323 MiB | Median of three paired runs |
| T3 gain-sized snapshot | 18,892 | 87.46 → 75.25 | 807 → 729 MiB | One paired run |

All measured candidate and prompt hashes match. Warm encodes are zero. The small cold runs still encode the
same 1,842 and 2,714 inputs; their 117.34→123.61s and 183.26→181.41s timings under shared-host load do not
establish a cold speedup. Gain-sized T3 uses validated recorded vectors to seed its disk cache; it is not a
cold-inference measurement. Seventy-five seconds is still expensive, so CPU remains explicit and cache-backed.

Recorded-vector validation also matches complete candidates, raw scores, identities, prompt hashes and native
admissions on all **66 selected single-query campaigns and five shared campaigns** across four complete public
backgrounds. Their 207 and 27 admissions respectively remain identical. Two small-T3 gold queries add a narrow
pilot check; the earlier 30-background/524-input corpus sweep was not repeated for this resource-only change.
These recorded-vector checks are distinct from the actual model inference in the cold timing runs.

The earlier raw-rank experiment's three useful operation families and zero gain across five shared campaigns
remain unchanged. Resource sharing adds no recall claim. Tail and fused selection were identical in that
panel, so the evidence still does not establish extra predictive power from ensembling or learned boosting.

## Reproduce and inspect

The [machine-readable results](enablement-results.json) preserve per-PR counts, costs, timing summaries,
parity scope and the evidence archive's exact SHA256.

The [private enablement evidence release](https://github.com/gigaverse-app/dry-lint-goldens/releases/tag/recall-enablement-v1-20261107)
contains the frozen historical replay bundle and CPU resource-study package. Access to the separate corpus
repository is required; private source-bearing prompts are not copied into this product repository.
The CPU package also uses the existing
[combined-recall-data-v1 release](https://github.com/gigaverse-app/dry-lint-goldens/releases/tag/combined-recall-data-v1-20261107).
Its required-file manifest names every source/vector input and hash; model files remain adopter-supplied.

```bash
# Historical bundle: hashes, native chronological judging, cache, ledger and reports; no providers.
python historical/reproduce.py --bundle historical --output /tmp/enablement-replay
# Add --refit to rebuild every candidate pool from the complete frozen function extraction.

# CPU package: change paths freely; recorded vectors make this provider- and inference-free.
python cpu/run.py --data-root /data/combined-recall-data-v1 --model-dir /models/minilm \
  --out /tmp/cpu-replay --arm baseline replay a068703e --one
python cpu/run.py --data-root /data/combined-recall-data-v1 --model-dir /models/minilm \
  --out /tmp/cpu-replay --arm runtime replay a068703e --one
python cpu/compare.py /tmp/cpu-replay
```

Package READMEs give dependency versions, full-corpus commands and fresh-output requirements. The CPU package
was tested after moving code, model and corpus into three separate directories. Historical reproduction
executes the native pipeline from recorded answers; it does not merely check hashes. Full-source refitting
is a slower separate option. Small T3 timing inputs are explicitly identified as outside the older four-corpus
bulk kit; they are not implied to be downloadable from that kit.

Integrated validation: 1,427 tests passed with the pinned local model and zero skips; the final preset-object
isolation fix passed 56 targeted tests. Lint/format, offline wheel/sdist builds and a budget-zero, no-judge
self-check passed. Production source changes do not include CI, credentials, model downloads or scheduler changes.
