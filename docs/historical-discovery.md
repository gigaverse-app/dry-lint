# Historical discovery and live judging

Status: six-PR historical pilot completed on 2026-11-03. Keep production defaults unchanged; continue with an
opt-in baseline-first exploration experiment. Retrieval improved, but judging recall and future-budget protection
do not yet support making this balanced.

This follows [the coverage design](coverage-exploration.md). The question is whether protecting baseline
candidates before exploring improves discovery across actual PR commits at a controlled cumulative budget,
without sacrificing early detection or report precision.

## Protocol fixed before judging

Use merged, multi-commit Python PRs with modest changed-file counts, selected from recent PR metadata before
examining candidate results. Backend: #5632 (mail reads), #5567 (checkout), #5626 (campaign execution).
AI: #3280 (soccer identity), #3275 (onboarding images), #3270 (translation policy). This is a small convenience
cohort, not a representative sample. Publish every selected PR, including zero-candidate commits.

Capture GitHub's ordered PR commit list and each immutable tree. For each revision, compare to its merge base
with the PR base. Rebuild the corpus from that tree, including only files allowed by the fixed default Python
settings. Never use current working-tree code, execute historical code, or inject a later function into an
earlier index. A commit is a discovery opportunity; it is not necessarily a recorded CI run or push event.

Compare fixed top-three retrieval against baseline-first refill using the existing replay scheduler. Both arms
start with empty coverage per PR. Include deeper baseline and combined semantic candidates only in refill.
Reuse a live answer across arms only for identical pair evidence and judge policy; keep each arm's virtual
coverage and spending independent. Report physical experiment expenditure separately from each arm's replayed
deployment cost. No repeated LLM draws are needed to compare deterministic scheduling on identical evidence.

Use the available Sonnet preset, record its exact prompt/model and thresholds, provider-reported input/output
usage, request latency, failures and returned model. Dollar amounts computed from observed token usage and
published prices are usage-priced costs, not reconciled invoices. Keep provider usage distinct from the
existing prompt-length estimate. Limit the complete experiment to $10 in usage-priced successful responses;
bound each request's output and account for uncertainty when reserving calls. Stop on authentication or
unpriced-model errors rather than making unmetered requests.

Reference judgments must be independent of the evaluated judge and attached to immutable pair evidence.
Label the union of scheduled candidates and a declared audit sample from outside that union. Unknown pairs
remain unknown. Report candidate coverage separately from reference-set recall; sampled-pool recall is not
repository-wide recall. Distinguish current-revision recall from pairs ever found, and first discovery from
revalidation of changed code. No default promotion can rest on agreement between a judge and itself.

## Required checks

- Historical extraction uses the requested tree, including deletion/new-function behavior and merge-base semantics.
- Multi-source pools share provenance; candidate evidence and ordering are deterministic.
- Equal-budget replay includes cache hits, failed calls, changed evidence and zero-candidate commits.
- Every live answer has usage and model provenance, with resumable private records and no credentials persisted.
- Report per-commit discovery curves, actual token usage, usage-priced cost, latency and independent labels.
- Apply the existing balanced promotion gates. If evidence is weak or negative, keep defaults and explain the gap.

Raw source snapshots, reference labels and responses stay outside the public repository. Only the harness,
synthetic regression tests, aggregate results and reproduction instructions belong here.

## Results

We replayed 27 commits, including eight with no changed production functions, using Python 3.14.7. Each arm had
10 new judgments per commit, 40 per PR, a $0.15 per-commit ceiling and a $0.50 cumulative PR ceiling. The physical
experiment allowance was $10. Baseline means the default TF-IDF comparer with k=3; refill first serves every
pending baseline pair, then takes unseen candidates from deeper lexical or combined semantic retrieval at k=20.
Semantic retrieval uses API, binding and flow features from the existing signal spike and floors of 0.35/0.20,
compared with the default 0.50/0.30. Selection is query-fair within the lane. These are experimental scheduler
controls, not profiles shipped in the CLI or an exact replay of production CI ordering.

The live judge was `dry-v1:claude-sonnet-5-5`, using the canonical Sonnet preset and report threshold 0.60.
It received the production function-pair prompt, without expanded surrounding source. This does not evaluate
the default Jev/Sonnet cascade. Codex reviewed all 72 distinct prompt inputs before seeing live verdicts:
9 positive evidence versions representing 7 pairs, 62 separate cases, and 1 borderline case. The five AI
positive pairs share one task-cancellation query, so they are correlated examples of one extraction opportunity.
The two backend positives are campaign policy and bulk-email preparation overlaps. They are partial shared
operations, not claims that the enclosing functions are interchangeable. The labels are review judgments,
not proven behavioral equivalence; a second independent reviewer is still needed.

| Cohort | Commits | Reference positive pairs | Fixed calls / USD | Refill calls / USD | Final reported positives | Ever reported positives |
|---|---:|---:|---:|---:|---:|---:|
| Backend #5567 | 8 | 0 | 1 / 0.002442 | 2 / 0.005224 | 0 | 0 |
| Backend #5626 | 3 | 0 | 0 / 0 | 18 / 0.049322 | 0 | 0 |
| Backend #5632 | 2 | 2 | 0 / 0 | 10 / 0.058114 | 0 / 2 | 1 / 2 |
| AI #3270 | 4 | 0 | 2 / 0.005398 | 19 / 0.055714 | 0 | 0 |
| AI #3275 | 8 | 5 | 4 / 0.009710 | 19 / 0.059648 | 3 / 5 | 3 / 5 |
| AI #3280 | 2 | 0 | 1 / 0.003810 | 4 / 0.017668 | 0 | 0 |
| Total | 27 | 7 | 8 / 0.021360 | 72 / 0.245690 | 3 / 7 | 4 / 7 |

Fixed reported no positives. Refill reached all seven positive pairs, but final report recall was **3/7 (43%)**,
and recall of pairs ever reported was **4/7 (57%)**. There were four distinct reported prompt inputs, all labelled
positive by the independent review; no separate or borderline case was reported. Four reports across two PRs
are insufficient evidence for a precision guarantee. Baseline retrieval's eight judgments contained no reference
positives; refill's 72 contained nine positive evidence versions (12.5% pre-judge precision within this pool).
All seven positives arrived through the semantic source, not the deeper default lexical source.

Physical usage was **84 requests, 99,079 input tokens and 9,476 output tokens, costing $0.292918** at published
rates. This includes 12 additional audit requests costing $0.047228. The main comparison alone used 72 requests,
82,075 input tokens and 8,154 output tokens. There were no provider cache tokens, failures or model substitutions.
The fixed arm reused eight physical responses already needed by refill, but its independent ledger still paid
for all eight. Thus $0.021360 + $0.245690 is the cost of deploying both arms independently, not the experiment's
physical bill. Prices were $2/million input and $10/million output, verified against the
[Sonnet 5.5 documentation](https://platform.claude.com/docs/en/models/sonnet-5-5/overview).
These amounts price observed provider usage; they are not reconciled invoices and exclude Codex review effort.

Observed API request p50/p95 was 1.97/3.00 seconds across the 84 calls. Summed sequential judge time for the main
arms was 16.25 seconds fixed and 153.52 seconds refill. Across all 27 commits, p95 sequential judge time was
3.85 versus 21.84 seconds (nearest-rank p95, zero-call commits included). These are measured request times
assigned to each arm, not measured end-to-end CI latency: corpus building, queueing and concurrent execution
are outside that timing. One response per exact prompt also does not measure judge variance under repeated draws.

## What happened across commits

The [per-commit CSV](assets/historical-discovery.csv) includes both arms, current-evidence recall counts,
ever-discovered counts, cumulative cost, attempts and sequential API time. Recall denominators include only
independently labelled positives available in that commit's reviewed pool. Earlier revisions do not borrow
later candidates or labels for absent evidence.

| Cohort / commit | Available positives | Currently judged positives | Currently reported positives | Cumulative refill calls | Cumulative USD |
|---|---:|---:|---:|---:|---:|
| AI #3275 / 1–2 | 0 | 0 | 0 | 0 | 0 |
| AI #3275 / 3 | 3 | 2 | 2 | 10 | 0.037098 |
| AI #3275 / 4 | 3 | 3 | 2 | 16 | 0.052200 |
| AI #3275 / 5 | 3 | 3 | 2 | 16 | 0.052200 |
| AI #3275 / 6–8 | 5 | 5 | 3 | 19 | 0.059648 |
| Backend #5632 / 1 | 2 | 2 | 1 | 5 | 0.029508 |
| Backend #5632 / 2 | 2 | 2 | 0 | 10 | 0.058114 |

The AI PR demonstrates both mechanisms: commit 4 uses previously unused judging capacity to examine a deferred
pair; commit 6 exposes additional candidates as the tree changes. Unchanged evidence is not repaid. The mail
PR changes both query bodies, so all five pair prompts need fresh judgments. A previously reported preparation
overlap falls from 0.62/duplicate to 0.25/separate. We do not reuse its stale positive verdict to inflate final
recall. The judge repeatedly dismisses partial reusable operations because the larger workflows differ, and
is inconsistent about equivalent cancel-and-await task cleanup. More retrieval budget alone cannot fix that.

## Budget sensitivity

These are deterministic reschedules of the same observed responses, with separate ledgers and identical budgets
for fixed/refill within each row. They require no extra API calls. They are diagnostic sensitivity runs, not an
independent validation set. Fixed remained at eight calls, $0.021360 and zero reported positives throughout.

| Refill allowance per commit / PR | USD ceiling per PR | Calls across six PRs | Usage-priced USD | Final positive pairs judged | Final / ever positive pairs reported |
|---|---:|---:|---:|---:|---:|
| 10 / 40 | 0.50 | 72 | 0.245690 | 7 / 7 | 3 / 7 ; 4 / 7 |
| 3 / 40 | 0.50 | 48 | 0.174378 | 7 / 7 | 3 / 7 ; 4 / 7 |
| 10 / 4 | 0.50 | 22 | 0.082932 | 0 / 7 | 0 / 7 ; 1 / 7 |
| 10 / 8 | 0.50 | 38 | 0.151182 | 3 / 7 | 1 / 7 ; 2 / 7 |
| 10 / 16 | 0.50 | 64 | 0.223808 | 5 / 7 | 2 / 7 ; 3 / 7 |
| 10 / 40 | 0.10 | 22 | 0.070166 | 1 / 7 | 1 / 7 ; 1 / 7 |
| 10 / 40 | 0.15 | 72 | 0.245690 | 7 / 7 | 3 / 7 ; 4 / 7 |

Three calls per commit preserved these final findings while spending 29% less than ten. It changes discovery
timing and is not proof that three calls is universally optimal. Four calls per PR can discover a positive early
yet fail to revalidate it after a revision; this is why both current and ever-found recall matter.

Currency admission reserves a conservative UTF-8 input bound plus the judge's maximum 8,000 output tokens
before each call, and releases unused capacity after observed usage arrives. A small dollar ceiling therefore
leaves capacity unused when the next worst-case reservation does not fit, even though typical answers cost far
less. Both arms use the same rule, including when a physical response is already cached. The $0.10 result is
partly a reservation-policy effect. Tuning maximum output length requires its own truncation/quality experiment.

Baseline-first protects the **current** pending baseline, including against cheaper exploration taking the
place of an unaffordable baseline item. It cannot protect unseen future commits with one shared cumulative
budget. A regression fixture demonstrates a one-call campaign: early exploration consumes the call and a later
baseline candidate is missed, while fixed still has its call. A deployable profile needs separate exploration
allowances and replenishing/reserved capacity for fresh evidence, plus explicit exhaustion behavior. No finite
campaign budget guarantees scrutiny of arbitrarily many revisions.

## Is k=3 the blocker? What do extra signals buy?

A final-tree ablation kept queries and labels fixed and changed lexical depth/floors independently. It measures
retrieval of the seven reviewed positives only. Additional candidates outside the reviewed pool remain unlabelled.

| Retrieval | Candidate pairs across final trees | Known positives retrieved |
|---|---:|---:|
| Current lexical, k=3, floors 0.50/0.30 | 8 | 0 / 7 |
| Current lexical, k=20, floors 0.50/0.30 | 13 | 0 / 7 |
| Lexical, k=3, floors 0.35/0.20 | 38 | 5 / 7 |
| Lexical, k=20, floors 0.35/0.20 | 87 | 5 / 7 |
| Combined semantic, k=20, floors 0.35/0.20 | 67 | 7 / 7 |

Increasing k alone did not recover any known positive. Lowering floors recovered five even at k=3. At equal
k and floors, combined signals recovered two more known positives while proposing twenty fewer pairs than
lexical retrieval. This supports an opt-in signal path; it does not establish its population precision because
the reference pool was partly selected by that path. Individual feature contributions still need held-out
ablations. The evidence does not justify synonym dictionaries or extra generic tokens by default. Thin wrappers,
shared helpers, common error types, CLI scaffolding and overloaded words such as “slot” remain common false
positives before judging. Signals that identify an already-shared owner and meaningful shared sub-operations are
more useful next experiments than indiscriminate vocabulary expansion.

The audit selected two nearest excluded pairs per final PR tree, one per changed query per round where possible,
using combined retrieval with k=50 and zero floors. Pairs seen anywhere in the main historical pool were excluded.
All twelve were independently labelled separate, and the live judge also rejected all twelve. This small,
deterministic near-boundary audit is not a random sample and cannot establish global recall or exclude distant
semantic duplicates. One main-pool borderline case stays out of precision/recall denominators.

## Decision and next promotion evidence

Keep baseline-first exploration opt-in. Do not rename it to the production balanced default yet:

- Final report recall is 3/7 despite 7/7 candidate coverage. Test a versioned judge policy that explicitly considers
  reusable sub-operations and existing owners, then validate it on held-out PRs. Do not lower thresholds merely
  to fit this cohort; most misses were labelled separate, not just below the report threshold.
- This cohort has no baseline-positive cases, so it cannot establish protection of early baseline findings.
  Include fresh-code PRs with baseline positives and measure first-discovery delay, revalidation and PR-level
  uncertainty. Five related AI pairs must not masquerade as five independent confirmations.
- Separate new-evidence capacity from exploration spending. Test long PRs, late revisions, failures and exhaustion;
  use a concurrent reservation ledger before production use. The spike is a single-writer research harness.
- Measure the actual deployment judge/cascade, full CI latency, repeated-draw stability and a larger independent
  audit. Require the existing [balanced promotion gates](coverage-exploration.md) before changing defaults.

Use a new opt-in profile when the user deliberately accepts a different budget or discovery delay, such as a
slow background sweep. Change balanced when one policy consistently improves the default user's tradeoff under
the same stated budget, meets precision/latency gates and preserves fresh-code scrutiny. The slower refill run
is a useful next candidate for that comparison, not sufficient evidence of dominance.

## Reproduction and implementation

The harness reuses the existing detector, signal spike, replay selector, canonical judge and preset. The only
production API addition is an optional historical `head` argument to `changed_lines`; default behavior is intact.
`capture_history.py` reads Git blobs, `audit_history.py` builds excluded-pair packets, `judge_history.py` meters
real SDK responses, and `score_history.py` validates exact evidence and computes per-commit counts and ablations.
Tests cover immutable trees, deletion/new-function behavior, out-of-pool audits, independent arm accounting,
currency admission, stale evidence, unknown labels, future-budget starvation and interrupted/unmetered requests.

Create `/private/history/manifest.json` as a list of `{repository, root, number, base, commits}`. `root` is the
local clone path; `base` and every ordered commit are fetched immutable SHAs from the selected PR. The manifest
and captured runs retain exact revisions. The six pilot final heads were `3c0ee6d9`, `9fd755e4`, `cb753172`,
`a7affa4f`, `09235c75`, and `4b8577e7` in the table's order. Use Python 3.14 for this corpus: some historical source
uses syntax unavailable to older Python AST parsers. The public aggregate omits private function identities/code.

```bash
uv run --python 3.14 python scripts/capture_history.py \
  --manifest /private/history/manifest.json --out /private/history/captures
uv run python scripts/audit_history.py --captures /private/history/captures --out /private/history/audit
# ANTHROPIC_API_KEY must already be in the process environment.
uv run python scripts/judge_history.py --captures /private/history/captures \
  --out /private/history/live --per-run 10 --total 40 --run-usd 0.15 --total-usd 0.50 --limit-usd 10
uv run python scripts/score_history.py --root /private/history --ablate
```

Before viewing live verdicts, independently label every distinct prompt in the capture union. Store an array in
`reference/labels.json` with `cohort` (capture directory name), `answer` (the `answer_key` hash for the exact judge
version), `pair`, `label` (`duplicate`, `separate`, or `borderline`) and a concrete `reason`. The scorer leaves
unlabelled reports unresolved. Private packets and labels are required to reproduce the exact recall counts.
For budget sensitivity, call `evaluate` again with a fresh policy ledger and the same `LiveAnswers` store; its
cached observations retain actual usage while each arm independently pays when it first needs an answer.

The live cache keys the actual oriented prompt and judge version. It persists a pending marker before sending;
an interruption or missing/unpriced usage stops further live work until reconciled. Known paid parse failures
retain usage and do not turn into cached verdicts. HTTP retries are disabled. This improves research accounting
but does not provide cross-process reservation or an invoice-reconciliation service. No consumer code, production
retrieval settings, judge prompts or live profile defaults were changed by this experiment.
