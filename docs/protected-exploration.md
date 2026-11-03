# Shared operations and protected discovery

This experiment separates three questions: can the judge recognize a useful shared operation inside different
workflows, can exploration leave capacity for later baseline candidates, and do both improvements justify a
new balanced default? Defaults remain unchanged. The judge policy is usable today; protected discovery is a
historical replay experiment, not a live discovery profile.

## What changed

The opt-in `shared-operations` Anthropic prompt asks for a concrete shared operation, its inputs, ordering and
failure contract, and the variations that stay in callers. Whole functions need not be interchangeable.
It distinguishes callers of an existing helper from independently repeated compositions of several helpers.
Confidence concerns whether an operation is repeated, rather than how many lines extraction might save.

The legacy prompt remains the default. The experimental policy has its own judge name and version; output-limit
changes require an exact cache version. Switching back cannot reuse experimental answers as legacy verdicts.
Replay results retain their actual prompt template so a later prompt revision cannot silently alter scoring.

```toml
[tool.dry-lint]
preset = "sonnet"
judge = { use = "anthropic", model = "claude-sonnet-5-5", prompt_policy = "shared-operations", max_tokens = 2048 }
```

Run `dry-lint check --warn-only` for an opt-in pilot. This changes judging only. It does not expand retrieval or
enable the experimental scheduler. The existing Sonnet thresholds are comparison thresholds, not newly
calibrated confidence guarantees for this prompt. This is not a validation of the default Jev/Opus cascade.

## Reserving capacity across commits

All replay arms use the same total/per-run call and dollar limits, and identical evidence for each revision:

| Policy | Current work | Later work |
| --- | --- | --- |
| Fixed | Baseline candidates only | Reuse valid answers; judge changed evidence |
| Refill | Baseline first, then unexplored candidates | Exploration may consume the whole campaign allowance |
| Protected | Baseline first, at most one exploration call per revision | Half of campaign calls and dollars cannot be spent by exploration |

Protection does not inspect future commits or divide by a known history length. Baseline selection keeps its
own query-fairness counters so earlier exploration does not reorder its priorities. An identical logical run
cannot replenish the allowance; conflicting evidence under the same identity is rejected. Changed evidence
requires a new judgment, and earlier answers cease to count as current coverage.

The guarantee is bounded: exploration cannot consume the reserve. Baseline work can exhaust it, and a future
request larger than the remaining allowance still cannot run. Permanently reserving capacity also leaves some
money unused when a PR never needs it. These are explicit tradeoffs, not an unlimited baseline-preservation claim.

## Evaluation protocol

The previous six PRs and 27 commits are development data only. The first shared-operation prompt was revised
using its development misses. Version 2 was frozen before inspecting fresh verdicts; its SHA-256 is
`d16aa74739f455d380262e448db3d28a68241c4af47c4f87549b2dc83df6474f`.

Screening captured final trees from 18 additional PRs. Independent source review identified baseline positives
in backend #5587 and AI #3209. Those two and baseline-negative controls backend #5614 and AI #3283 form the fresh
18-commit replay. The control designation concerns the baseline: broader review found additional positives in
their exploration pools. This is an explicitly enriched sample, not a random estimate of production precision.
The other screened PRs are not represented as fully labelled negative PRs.

All 121 distinct evidence versions in these four replay pools were reviewed by Codex before inspecting their
live verdicts: 11 positives, 103 negatives and seven borderline cases. Borderline cases remain separate from
binary denominators. References are independent of the
tested Sonnet judge but remain one reviewer's judgments. Retrieval-pool recall is conditional on this reviewed
union; it does not measure duplication outside the union or across repositories.

Live calls use the canonical Anthropic judge and provider-reported tokens. Prices come from the repository's
price table. Each scheduler pays independently for its selected answers even when a shared physical cache
avoids buying the same experimental answer twice. Failed paid attempts remain charged. The combined physical
experiment ceiling is $10. This is usage-priced cost, not a reconciled invoice.

The initial 1,024-token development comparison encountered one invalid answer at the output cap. Both prompts
were rerun at 2,048 tokens; the original answers and failed attempt were retained in the physical ledger. The
main comparison uses three calls per revision, 40 per PR, $0.15 per revision and $0.50 per PR. A second comparison
uses $0.04 per PR/per revision to test the current default-sized allowance. The reservation uses a conservative
UTF-8 input bound and the full output cap, rather than assuming the next request will cost the observed average.

Captures used Python 3.14.7, which can parse the consumers' current syntax. An older parser may produce a
different eligible pool; preserve the interpreter and capture manifests when reproducing these measurements.

## Results across commits

The four fresh PRs contain 11 confirmed positive pairs in the reviewed pool, including two baseline positives.
At the research allowance, both baseline positives were reported on their first eligible commit: backend's
first commit and AI's third commit. Protected preserved every fixed-arm judgment at every revision, not only
those two final findings. Its extra confirmed finding appeared two commits after first becoming eligible.
Refill found another positive two commits after eligibility. These histories demonstrate eventual discovery,
but not eventual completeness.

| Judge / scheduling | Newly judged evidence | Positives reached | Final true reports | False / unresolved reports | Total USD across four PRs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Legacy / fixed | 18 | 2/11 | 2/11 | 0 / 0 | 0.045176 |
| Legacy / protected | 28 | 3/11 | 3/11 | 0 / 0 | 0.093522 |
| Legacy / refill | 42 | 4/11 | 4/11 | 0 / 1 | 0.147458 |
| Shared operations v2 / fixed | 18 | 2/11 | 2/11 | 0 / 0 | 0.091472 |
| Shared operations v2 / protected | 28 | 3/11 | 3/11 | 0 / 0 | 0.158968 |
| Shared operations v2 / refill | 42 | 4/11 | 4/11 | 0 / 1 | 0.260222 |

All arms used the same budget ceilings. Physical answer reuse does not discount the individual arms above.
Unresolved reports concern a reference-labelled borderline case. Current and ever-reported pair counts coincide
at the final revision in these fresh histories. The [per-commit curves](protected-exploration-curves.csv) also
include development results and the $0.04 sensitivity.

Protected's pre-judge yield was 3/28; its resolved report precision was 3/3. Three correct reports cannot
establish a population precision guarantee. Exhaustively resampling the four PR clusters with replacement
(256 paired bootstrap samples) gives a 95% percentile interval of **0 to 12 percentage points** for its final
recall gain over fixed, using v2. That interval includes no improvement and fails the proposed promotion gate.

Summed observed API request time was 49.64 seconds for v2/fixed, 77.92 for v2/protected and 125.54 for v2/refill
across all four histories. These are serial request measurements, not CI wall time or a production p95 claim.
Protected saved 39% of refill's dollars while finding three rather than four positives. The longer v2 prompt
did not improve these scheduled fresh findings over the legacy prompt and cost more.

At **$0.04 per PR**, v2/fixed, v2/protected and v2/refill all made seven calls, spent $0.038112 in total across
the four PRs and reported the same two baseline positives. Legacy/fixed and legacy/protected made 15 calls,
spent $0.036352 and also reported those two. With a 2,048-token maximum, output reservation alone is $0.02048;
protected's $0.02 exploration slice cannot admit a request even before input is counted. Total measured spend
can be well below the ceiling because the next request's conservative reservation no longer fits.

### Development diagnosis

The complete old development pool has 72 evidence versions: nine frozen positives, 62 negatives and one
borderline. At report threshold 0.6, legacy reported 6/9 positives, operations v1 5/9, and v2 7/9. V2 fixes
payload-composition misses, but still puts two correctly identified shared operations below the report
threshold. Recognizing an overlap and calibrating its score remain separate problems.

V2 also reports one frozen negative. Review of that disagreement supports a narrower shared preparation
operation: both implementations derive a sport from the same subject/query fallback and filter successful
facts to that provider and sport, although their roster evidence contracts differ. The original whole-function
label missed this overlap. Keep the primary 7-true/1-reference-false count; post-verdict adjudication can repair
development references but cannot count as independent validation. Future references should record the shared
region and extraction contract, rather than only a whole-function binary label.

On the old histories, v2/protected reports 2/7 final positive pairs versus legacy/protected's 1/7; v2/refill
reports 6/7 versus legacy/refill's 5/7. The one-exploration-per-revision pace leaves many known positives unjudged
in short PRs. A reserve and a pacing limit should be evaluated separately.

### Judge-only diagnostic and reserve ablation

Judging the entire fresh reviewed pool, outside scheduler allowances, isolates the judge from retrieval/order:

| Prompt | True reports / 11 positives | False reports / 103 negatives | Borderline reports / invalid answers | USD for 121 attempts |
| --- | ---: | ---: | ---: | ---: |
| Legacy | 8/11 | 2/103 | 3 / 0 | 0.417708 |
| Shared operations v2 | 10/11 | 0/103 | 2 / 1 | 0.738790 |

The new prompt improves this judge-only sample and rejects the deliberately independent cohort oracle. It
costs 77% more. Its invalid answer was on a borderline pair, used 301 output tokens and cost $0.006344; it was
not an output-cap failure. It remains unresolved, not a negative or a free retry. The diagnostic runner now
continues independent work after a known, charged invalid answer, preserves failure details for new attempts,
and still stops when usage is unknown. Scheduler-selected judgments in the main comparison had no failures.

An offline ablation kept the same half-budget reserve but allowed up to three exploration calls per revision.
It matched refill: 6/7 final development positives for $0.305824 and 4/11 fresh positives for $0.260222. No new
provider calls were made. At the research allowance the reserve was not binding; the one-call pacing rule
caused the recall loss. This post-evaluation sensitivity is a design clue, not another independent holdout.

The entire experiment made **635 paid attempts**, including development revisions, diagnostics and two failed
answers: **945,427 input tokens, 118,870 output tokens, $3.079554**, with no provider cache tokens. The 1,620.74
seconds of summed API request duration is neither elapsed experiment time nor CI latency. Main-arm costs above
exclude diagnostic work and charge shared cached observations independently to each counterfactual scheduler.

## Balanced decision

Keep this opt-in. The reserve protects later capacity, but these measurements do not justify changing balanced:

- The default-sized allowance provides no exploration with this reservation/output policy. Lower-cost judging,
  better input bounds, bounded structured responses and an explicit exploration allowance need paired tests.
- The fresh recall gain is uncertain, and the judge revision has no scheduled fresh recall gain over legacy.
  Larger pools need better ordering and an explicit recall/latency tradeoff; increasing `k` alone is insufficient.
- Shared-operation references need region-level adjudication. A small number of correct reports cannot certify
  the precision or blocking noninferiority gates.
- The production Jev/Opus cascade, concurrent cumulative reservations, retry/crash accounting, follow-up PR
  coverage and a warn-only pilot still need validation. The replay does not implement these runtime contracts.

Retain separate profiles only for measured tradeoffs people want: high precision can spend less and report
conservatively; high recall can pay for deeper/faster exploration. Promote a version of balanced when it improves
discovery at the agreed allowance while preserving first-pass baseline findings and meeting the existing
[precision, recall and latency gates](coverage-exploration.md#promotion-gates-and-rollout). A new name cannot
substitute for those measurements.

## Reproduction

Use immutable, locally fetched commit SHAs and the ordered PR commit list. Captures contain private source and
must stay outside the repository. Capture and independently label packets before inspecting live results:

```bash
uv run python scripts/capture_history.py --manifest manifest.json --out private/captures
uv run python scripts/compare_history.py --captures private/captures --out private/live \
  --answers private/answers --packets-only
# Save blinded labels as [{"evidence": "<packet evidence key>", "label": "duplicate|separate|borderline"}].
uv run python scripts/compare_history.py --captures private/captures --out private/live \
  --answers private/answers --max-tokens 2048
uv run python scripts/score_comparison.py --captures private/captures --results private/live \
  --labels private/labels.json --answers private/answers --out private/scored.json
```

Supply `ANTHROPIC_API_KEY` through the environment. Use one writer for the answer directory. An unmetered
attempt stops the experiment for reconciliation; a paid invalid answer stops automatic retries while preserving
its usage. Complete-pool diagnostics continue other pairs after accounted failures and record unresolved keys.
`--complete-pool` is a separate diagnostic allowance and does not represent a scheduler's PR spend.
