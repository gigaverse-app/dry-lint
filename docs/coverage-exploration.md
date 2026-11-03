# Discovery over time: design and exploration

Status: experimental design and offline spike, 2026-11-03. Live `check`, `scan`, judge presets and defaults are unchanged.

## What we want to achieve

Find useful duplication early, then use subsequent runs to cover more of the search space under an explicit
cumulative judging budget. A developer should get an actionable reuse suggestion while writing new code;
revising the PR should improve coverage rather than repeatedly inspect the same shortlist. A maintainer should
be able to spend a separate backlog allowance on untouched code. None of these modes promises absence of duplication.

There are three independent decisions: what to retrieve, what to spend judging, and what to report or block.
Precision and recall are measured outcomes of those decisions, not knobs with guaranteed percentage settings.
Retrieving every eligible pair would remove retrieval misses within that eligibility boundary, but would not
remove judge errors, missing context, or exclusions. More unrelated pairs also create more opportunities for false alarms.

| Measurement | Definition | Direction |
| --- | --- | --- |
| Retrieval recall | Labelled duplicates admitted to the candidate pool / eligible labelled duplicates | Higher |
| Judging yield | Confirmed useful duplicates / newly judged pairs, with unknown labels reported separately | Higher |
| Report precision | Correct reported duplicates / all reported duplicates | Higher |
| End-to-end recall | Correct reported duplicates / eligible labelled duplicates, including retrieval misses | Higher |
| Cost | Calls, input/output tokens, money, escalations and p50/p95 wall time | Lower at equal quality |
| Discovery delay | Runs, commits and elapsed time from duplication introduction to first correct report | Lower |
| Current coverage | Pairs with valid answers for the current evidence / current admitted pool | Higher |
| Historical coverage | Distinct pairs ever examined, including now-stale versions | Diagnostic; not current recall |

Coverage is relative to a declared pool. Report its source, floor, size and exclusions. Looking at 100% of a
narrow pool does not imply repository-wide recall. Repeated snapshots are not independent samples.

## Use cases and priorities

| Situation | Desired behavior | Tradeoff to measure |
| --- | --- | --- |
| New function in a PR | Initial scrutiny across strong lexical and semantic matches | Newness is a risk hypothesis, not a proven prior |
| Substantial rewrite | Revalidate affected findings; inspect new partners | Rechecks must not consume all exploration indefinitely |
| Another commit with unchanged function evidence | Reuse valid answers and advance to unexamined pairs | Same-head infrastructure retries must be idempotent |
| Follow-up PR | Continue repository coverage while reserving fresh-code capacity | Shared state must survive individual PRs |
| Newly added potential partner | Schedule new pair even if the other function was already covered | Coverage cannot be a permanent boolean on a function |
| Rename or move | Preserve lineage when confidently established; otherwise examine again | Never transfer a verdict based only on fuzzy identity |
| Scheduled backlog sweep | Spend a separate allowance on old untouched functions | PR-only checking cannot promise eventual discovery |
| High-assurance audit | Broader pools and explicitly requested larger budget | More judging does not guarantee accurate judges |
| Limited CI latency | Return valid findings plus explicit deferred work | Deferred or failed judgments are not negative verdicts |

## What the current implementation prevents

`Detector` is stateless and should stay that way. Today it selects a fixed nearest-neighbour shortlist before
`Judging` consults `VerdictStore`. Cached answers save calls but do not refill the shortlist with unexplored
pairs. `scan()` additionally requires mutual first neighbours, so raising `neighbours` alone does not broaden
the backlog. Hard similarity floors and same-file/language filters create other boundaries.

The existing verdict store remains the owner of real judgments and their reuse rules. Main now includes source
context and a context digest in verdict reuse (PR #21); build on that contract rather than recreating it. A scheduler belongs
between proposing and judging, outside the detector. It must not relax verdict reuse to obtain attractive savings.
The judge/model presets and per-run spending ledger merged in PR #22 remain a separate axis. Discovery profiles
must compose with `presets.py` and `costs.Ledger` rather than implement another model resolver or price table.
That ledger estimates per-run dollars/subscription calls; repository-wide cumulative reservations and discovery
progress are additional contracts. The replay's unit-attempt accounting is deliberately an experimental proxy.

```text
BEFORE
changed functions -> fixed top 3 -> rules -> verdict cache -> judge misses -> report
next run          -> same top 3  -> rules -> cache hits    -> no wider coverage

PROPOSED
changed/new/backlog functions -> diverse pools -> rules -> valid cached answers
                                                       -> pending pairs
pending + coverage history + remaining budget -> scheduler -> judge -> record outcome
cached and new valid answers -> calibrated report policy -> findings + deferred counts
next run -> refreshed pool + prior progress -> further coverage and required revalidation
```

## Retrieval: preserve good routes, add complementary ones

Protect baseline candidates first. Add a quota from the combined API-resolution, argument-binding and field-flow
experiment instead of mixing every token into the only vector. Keep source names, versions, ranks and scores
on each proposal. Deduplicate the unordered pair before judging; a pair found by three sources costs one judgment.
Use source-specific ranks and calibrated floors, not comparisons between unrelated raw cosine scales.

Maintain a larger inexpensive pool than the immediate call allowance. Exploration should include deeper baseline
ranks, alternative signals, and a small audited sample below usual floors. An absolute floor remains a permanent
blind spot. Same-file and language eligibility should be separate ablations, not silently changed by a profile.
Scan must expose its own candidate policy instead of always taking mutual top one.

More signals are useful when they discover additional true pairs or reduce judging cost at equal recall. Synonyms,
stopword changes, size ratios, resolved keyword/positional arguments and class identifiers should each have an
ablation. Size is initially a ranking feature, not a hard veto. Broad synonym expansion risks merging concepts;
start with measured domain-specific aliases and retain original names. Already-split snake/camel/acronym words
and existing key tokens remain part of the baseline.

## Scheduling and state

Separate strong unresolved candidates, complementary-source exploration, and aging work. An illustrative
60/25/15 allocation is a hypothesis. Quotas roll forward across small runs so a one-call budget still eventually
explores; empty lanes lend their slots. Round-robin across changed functions prevents one large function from
consuming the allowance. Reserve initial coverage for newly introduced functions, then age deferred work.

The invariant is bounded spending with explicit incomplete work. Before a call, reserve the applicable cost
allowance, including possible escalation. After completion, reconcile actual usage and acknowledge coverage only
for a valid answer. A timeout, malformed response or failed escalation does not become `separate`. Cached
findings remain reportable even when new-call capacity is zero. Strong stale findings receive revalidation priority.

Production needs two related records:

- **Verdict evidence:** reuse the canonical pair, functions and verdict. Include the judge/model/prompt/escalation
  policy and the evidence actually supplied to it. Function structure hashes alone may omit import bindings,
  decorators, signatures or contextual changes that affect a judgment. Audit that boundary before claiming reuse
  is sound. A changed policy or relevant context invalidates the answer.
- **Coverage and spending:** stable repository/function lineage, pair identity, first seen, retrieval provenance,
  attempts, completed evidence versions, outstanding reservations, and run/PR/repository budget accounting.
  This is operational progress, never a human suppression or a fabricated verdict.

Keep historical exploration when evidence changes, but mark the old answer stale. Separate stale rechecks from
previously unseen partners. A newly added candidate enters the queue regardless of prior coverage. Preserve
human suppressions in code/configuration. Recomputing IDF or changing retrieval weights does not itself invalidate
an unchanged judge input; changing the judge input does.

Use idempotency keys for logical runs, not commit-derived random shuffling. Same-run retries resume reservations;
an explicitly new discovery pass may explore further. Concurrent jobs need atomic reservation/claim semantics,
expiry and recovery for interrupted workers. The current store's independent object writes and Actions cache
restore/save do not establish shared cumulative budget safety. Reuse its backend where possible, but add an
explicit coordination contract before making guarantees. A local single-writer mode is a useful first deployment.
Keep trusted accounting in the judge job; a fork's candidate artifact cannot grant itself more budget.

Eventual coverage is conditional: a finite admitted pool, recurring opportunities, successful judgments and a
nonzero fair exploration allocation. It cannot be guaranteed for an ever-growing pool under insufficient budget.
Track queue age and arrival/completion rates; show backlog growth rather than promising convergence.

## Profiles and the meaning of balanced

Profiles express preferences. Budget is independently configurable. A low-budget high-recall policy can explore
more widely over time while judging fewer pairs in any one run. Reporting/blocking thresholds remain calibrated
to the selected judge; a retrieval profile must not treat cosine or an LLM's self-score as a calibrated probability.

| Proposed profile | Discovery preference | Reporting preference | Likely use |
| --- | --- | --- | --- |
| High precision | Strong matches first, small continuing exploration | Conservative evidence threshold; warnings and blocking separate | Low tolerance for noisy review |
| Balanced | Protected baseline, complementary candidates, steady aging | Validated general-purpose threshold and escalation | Ordinary PR checks |
| High recall | Broader sources/floors, larger exploration share | Surface weaker evidence as clearly identified warnings | Audits and consolidation campaigns |

These names are proposed product policies. The spike's same-named policies only vary scheduling; they cannot
demonstrate final precision because they do not run judges. They must not become live defaults by naming alone.

**Improve balanced** when a change dominates the existing policy at the same cumulative budget: useful earlier
discovery, no meaningful precision/latency regression, and no new operational requirement for ordinary users.
Fixes to cache refill, deduplication, fairness and explainability generally belong in every profile once proven.

**Add or retain a profile** when the tradeoff is intentional: more cost/latency for recall, stricter reports for
precision, or different exploration delays. Do not create a new profile for every feature combination or preserve
an inferior balanced implementation forever. Version the resolved policy, show it in reports, allow an explicit
version pin, and document migration and rollback. Explicit user overrides win over profile settings.

## Promotion gates and rollout

Agree these gates before evaluating the held-out set. Suggested initial acceptance targets, not measured results:

1. All reviewed positive regressions stay retrievable; explanations exist for eligibility changes. This is a
   regression gate, not an estimate of global recall.
2. On held-out repository/time/PR groups at equal cumulative budget, the paired 95% confidence interval for
   recall-by-merge improvement excludes zero. No material loss of first-run recall; initial non-inferiority margin
   is 2 percentage points. Cluster by PR/repository, not repeated pair snapshots.
3. Report precision meets the chosen judge policy's published target; its paired lower confidence bound for
   change is above -1 percentage point. Evaluate blocking precision separately. If data cannot resolve that
   margin, collect more data rather than declare success from a point estimate.
4. p95 latency stays within the declared CI ceiling and no more than 10% above the existing policy at equal cost.
   Report dollars, tokens, retries and escalations; a call-count proxy cannot satisfy this gate.
5. Zero budget overruns in interruption/concurrency tests; deferred and failed pairs remain visibly unjudged.
   No stale finding or clean result may overwrite a newer run's report.
6. A warn-only pilot covers multiple repositories and at least a full review/revision/merge cycle, with false
   positives adjudicated and a documented rollback. Expand sample size until uncertainty supports the decision.

First ship opt-in experiments, then warn-only pilots, then promote a version of balanced when the gates pass.
Leave high-precision/high-recall alternatives where they occupy a useful different point on the tradeoff curve.
Default promotion is separate from merging tools that let us gather the evidence.

## Exploration plan and independently useful increments

| Increment | Deliverable and value if work stops there | Evidence needed |
| --- | --- | --- |
| 1: offline replay (this change) | Reproducible scheduling comparison over candidate snapshots, no paid calls | Progress, deduplication, invalidation, caps and replay invariants |
| 2: historical capture | Real chronological PR snapshots, introduction/change classification, source quotas | Reproduce queries from each historical tree without future-code leakage |
| 3: opt-in local scheduler | Cache-aware refill and bounded exploration using actual judges | Failure handling, valid cached reports, cost accounting, fresh labels |
| 4: shared CI coverage | Repository history and cumulative PR budgets across jobs | Concurrency, retries, forks, stale runs, retention and recovery |
| 5: profiles and promotion | Versioned balanced/high-precision/high-recall policies | Held-out quality/cost/latency gates above |

Start with deterministic allocation, not a learned bandit. First measure whether signal-specific yield is stable
enough to learn. Exploration labels are selected by policy; they are biased evaluation data. Maintain a separate
randomly sampled, independently adjudicated holdout. Report unknown labels as unknown, never as negatives.

Replay real PR histories in chronological order. Compare fixed top three, larger static k, cache-aware deepening,
protected baseline plus semantic candidates, and aging exploration under the same budgets. Include unchanged
reruns, revisions to either partner, new partners, deletions, renames, interrupted calls and exhausted budgets.
Separate the frozen-tree experiment (can the queue progress?) from the historical experiment (does it help before
merge?) and live judging (are the additional reports correct?). Preserve raw evidence privately if it contains
consumer source. Commit only synthetic fixtures, aggregate results and reproduction instructions.

## Initial evidence

The earlier semantic trial used 5,057 backend and 9,907 AI Python functions, 110 previously reviewed backend
pairs and 40 fresh pairs. These 150 labels have already informed the design and are not a held-out evaluation.
The queries below use both endpoints of labelled pairs; candidate counts are not a production PR cost estimate.

| Retrieval policy | Backend old positives / 27 | AI fresh positives / 7 | Unique candidates across sampled queries |
| --- | ---: | ---: | ---: |
| Baseline top 3 | 27 | 6 | 435 |
| Combined signals top 3 | 25 | 7 | 417 |
| Combined signals top 20 | 25 | 7 | 1,164 |
| Baseline 3 plus one novel combined candidate | 27 | 7 | 537 |

All these policies retained the six fresh backend positives. Raising k did not repair the combined scorer's
two lost regression positives; lowering its floors did, at increased candidate volume. That separates ranking
budget from floor effects. Preserving baseline routes plus a semantic supplement is a promising first policy,
not yet evidence for changing defaults. See [the semantic trial](semantic-signal-trial.md) for pinned repositories,
feature definitions and limitations.

## Built spike and frozen-tree results

`scripts/replay_coverage.py` implements a single-writer, offline scheduler over canonical `CandidatesFile`
snapshots. It deduplicates pairs across sources, accounts for successful and failed unit-cost attempts,
resumes a serialized ledger, rejects contradictory snapshots and reuses only identical code/context/policy
evidence. It does not produce verdicts or integrate with live checks. No function code appears in its output,
but identities and hashes may still be private. Its format has an independent schema version of 1.

| Experimental policy | Selection schedule across attempts | Empty-lane behavior |
| --- | --- | --- |
| `fixed` | Baseline only | Stop when baseline is covered |
| `refill` | Baseline first | Continue into the larger pool after covering baseline |
| `high-precision` | 8 baseline, 1 exploration, 1 aging | Lend unused slots |
| `balanced` | Baseline, baseline, exploration, baseline, aging | Lend unused slots |
| `high-recall` | Baseline, exploration, aging | Lend unused slots |

The schedule position persists across runs. Query attempt counts provide round-robin preference within a lane;
aging considers first-seen time before rank. Sources supply ordered lists; no raw score from one source is
compared with another. Source ranking is not yet a learned yield estimate. `refill` deliberately has no guaranteed
exploration share under continuously arriving baseline work: it is a useful comparator, not the final policy.

`scripts/probe_coverage.py` builds three pools: baseline top 3 at normal floors, deep baseline top 20 at normal
floors, and combined semantic top 20 at experimental floors 0.35 / 0.2 for short functions. It then compares
all five schedules over five discovery opportunities on a frozen tree. The detector's filtering rules still apply.

Measured with Python 3.14.7 and `PYTHONHASHSEED=0`, both tracked trees clean:

| Corpus | Source commit | Functions | Query functions | Admitted pair pool | Reviewed positive / negative pairs |
| --- | --- | ---: | ---: | ---: | ---: |
| Backend | `22dfbe180c6704101658a088cc269a25fa9c82dd` | 5,057 | 258 | 2,157 | 33 / 97 |
| AI | `806bd7ef848b66fb7dd8974384532dc419deb86c` | 10,307 | 40 | 163 | 7 / 13 |

AI advanced since the earlier semantic trial. All 150 labelled function bodies still matched the captured
trees exactly after indentation/outer-whitespace normalization; no missing, stale or borderline labels were
used in these counts. That body check does not re-adjudicate changed dependencies or establish held-out truth.

Each cell below is cumulative **known positive pairs examined**, higher is better. Calls are simulated
unit-cost attempts, not actual LLM calls. All arms have the same configured ceiling within each corpus; fixed
uses less than that ceiling when its shortlist ends. Unlabelled examined pairs are excluded from positive and
negative counts, not treated as negatives.

| Policy | Backend after 100 / 200 / 300 / 400 / 500 available attempts | Backend attempts used | AI after 10 / 20 / 30 / 40 / 50 available attempts | AI attempts used |
| --- | --- | ---: | --- | ---: |
| fixed | 26 / 32 / 33 / 33 / 33 | 393 | 1 / 5 / 6 / 6 / 6 | 42 |
| refill | 26 / 32 / 33 / 33 / 33 | 500 | 1 / 5 / 6 / 6 / 7 | 50 |
| high-precision | 20 / 30 / 31 / 32 / 33 | 500 | 1 / 4 / 6 / 7 / 7 | 50 |
| balanced | 20 / 29 / 31 / 32 / 33 | 500 | 1 / 4 / 6 / 7 / 7 | 50 |
| high-recall | 20 / 28 / 30 / 32 / 32 | 500 | 1 / 3 / 6 / 7 / 7 | 50 |

The result rejects an immediate switch to the initial balanced schedule. It delays six known backend positives
at the first checkpoint (20 versus 26), while getting the seventh AI positive one opportunity sooner than refill.
Refill preserves the baseline's early sequence and expands to that seventh AI pair by the fifth opportunity.
Backend refill examines 107 additional pairs without adding a known positive; most additional pairs are unlabelled,
so this is neither proof of wasted effort nor proof of better recall. Independent labeling is the next evidence gap.

This motivates **protected initial scrutiny followed by continuing exploration**, with a fair aging reserve once
fresh-code coverage has been delivered. Test that hypothesis on historical revisions before adopting it. Profile
names alone do not imply quality: the high-recall schedule reaches fewer backend positives at this budget.

These runs establish queue progress and an early-discovery tradeoff. They do not measure historical recall by
merge, judge precision, token cost, dollars, p95 latency or concurrent budget correctness. No paid judge calls
were made. The fixed comparator uses the same replay ordering/accounting as other arms; it is a fixed-retrieval
control, not a claim that the existing live tool already implements these budgets.

## Running the experiments

From a dry-lint checkout, run against a local Python repository. With no `--gold`, the probe queries every
extracted function. Gold files select query endpoints; keep source-bearing gold and all outputs outside public repos.

```bash
uv run python scripts/probe_coverage.py --root ../project --gold /private/gold.jsonl \
  --passes 5 --per-run 100 --total 500 --depth 20 --out /private/coverage-probe
```

For the backend table, pass the 110-pair regression gold and 20-pair fresh gold together after `--gold`.
For AI, pass the 20-pair fresh gold and use `--per-run 10 --total 50`. The output contains `summary.json`
and one replay result per policy. Raw local evidence was retained outside the repository in
`coverage-trial/backend/` and `coverage-trial/ai/`; only aggregates are published here. The private source and gold
are required to reproduce those exact counts. Synthetic end-to-end reproduction is in `tests/test_coverage_replay.py`.

To replay your own changing snapshots, create a JSON input with this envelope. Each source value is a complete
canonical `candidates.json` object from the same tree, including its schema and run provenance. Baseline contains
the protected shortlist; semantic/deep contain broader candidates. A label is not required to measure coverage.

```python
import json
from pathlib import Path

sources = {name: json.loads(Path(f"/private/{name}.json").read_text())
           for name in ("baseline", "semantic", "deep")}
payload = {"schema": 1, "steps": [
    {"run_id": "pr12/head-a/pass1", "sources": sources, "judge_policy": "offline-v1"},
    {"run_id": "pr12/head-a/pass2", "sources": sources, "judge_policy": "offline-v1"},
]}
Path("/private/replay.json").write_text(json.dumps(payload))
```

```bash
uv run python scripts/replay_coverage.py --input /private/replay.json --out /private/result.json \
  --profile balanced --per-run 3 --total 12
uv run python scripts/replay_coverage.py --input /private/next.json --resume /private/result.json \
  --out /private/continued.json --profile balanced --per-run 3 --total 12
```

The resumed `--total` is the whole campaign ceiling, not twelve more calls. Identical run IDs are no-ops;
reusing an ID with different evidence is rejected. Deliberate new passes need new IDs. The spike stores no
partial in-flight calls and is not a concurrent production budget store. A failure can be simulated with
`failed_keys` on a step; it consumes an attempt but leaves the pair uncovered for a later opportunity.

Currently implemented: bounded replay, deduplication, exact-evidence invalidation, persisted progress, deterministic
lanes and frozen-repository probes. Still proposed: new-function classification and protected initial allowances,
real historical capture, actual judges, currency/latency budgets, shared reservations and live profile settings.
