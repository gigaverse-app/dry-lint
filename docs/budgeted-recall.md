# Recall within the existing PR allowance

Keep the current judge prompts and thresholds. The cleanup goldens from PRs
[#90](https://github.com/gigaverse-app/dry-lint/pull/90) and
[#91](https://github.com/gigaverse-app/dry-lint/pull/91) motivated this investigation,
but improvements on those examples did not consistently transfer to other labels.
The safe implementation change is smaller: do not let an unaffordable request
prevent later, affordable requests from using the remaining allowance.

## The scheduling change

Previously, ordinary judging funded only a prefix of the ranked queue. With
requests costing $0.01, $0.035 and $0.005, a $0.04 allowance funded the first
request and stopped. The last request was never considered. It now funds the
first and last requests and leaves the middle one unjudged.

This applies to a single judge and to the second-opinion queue in a cascade.
The cascade's first pass keeps its existing prefix: spending more there could
crowd out second opinions the old scheduler would fund. Priority order, judge
semantics, thresholds, retrieval and the $0.04 setting are unchanged. Subscription
limits count funded calls, not candidates skipped because they are too expensive.
Skipped first judgments remain deferred; skipped second judgments retain the first
answer. Existing cache reuse and cumulative PR spending still apply.

For the same queue and remaining allowance, every previously funded request is
preserved. This is not a guarantee about arbitrary future commits: spending spare
capacity now can leave less for new candidates later. The separate `balanced`
discovery scheduler already skips unaffordable requests and is unchanged.

## Budget semantics

The ordinary `Ledger` limits **estimated** input/output cost. It does not enforce
a hard provider invoice ceiling. The discovery campaign uses conservative
reservations and provider-returned usage instead. This change preserves that
existing distinction; it does not raise either configured allowance or revise
prices to make more requests appear affordable.

In the frozen stress replay below, some ordinary batches estimated under $0.04
cost roughly $0.05–$0.06 at the recorded provider usage. Both the old and new
schedulers exhibit this. Do not advertise ordinary judging as a hard four-cent
billing cap. Enforcing that contract needs separate admission/accounting validation.

## Paired funding evidence

On 2026-11-05, replayed unchanged Sonnet `dry-v2` observations through production
`decide` and `Ledger`, with the old prefix policy as the control. The same verdict
is used in both arms; no fresh draw can manufacture an improvement. Three panels:

- Cleanup: 14 positives and 10 negatives, with three borderline cases excluded.
- Earlier private regression labels: 40 positives and 110 negatives from the
  110-pair regression panel and two 20-pair semantic-channel panels.
- Public hard examples: 15 positives and 15 negatives, including TypeScript.

Each panel is a synthetic one-run workload. For each, use its source order and
100 permutations from `random.Random(1379)`, retaining equal candidate priority
and similarity. Source-order funding was unchanged in all three panels. The
300 permutations expose budget fragmentation without pretending to be real PRs:

| Measurement across 300 permutations | Prefix | Refill |
| --- | ---: | ---: |
| Funded judgments | 3,615 | 3,656 |
| True reports at 0.60 | 1,208 | 1,221 |
| False reports at 0.60 | 224 | 225 |
| True blocking reports at 0.70 | 1,059 | 1,071 |
| False blocking reports at 0.70 | 111 | 112 |

No estimate exceeded $0.04. Aggregate report precision was 84.36% versus 84.44%;
these reused, correlated observations do not establish statistical noninferiority
or population recall. The small gain is budget utilization, not better judgment.

Also replayed baseline admission across 33 frozen captures covering 31 distinct
backend/AI PRs and 162 captured revisions from earlier discovery experiments.
Every old funded source version remained funded at the same revision; counts
were unchanged. That admission-only replay used neutral verdicts, so it establishes
no new true findings or historical judge-recall improvement. Some older captures
have the base-selection limitations already documented in those experiments.

## Prompt experiments that were not promoted

Compared the shipping concept prompt with the existing compact shared-operation
policy, a revised compact policy recognizing infrastructure contracts, and a
narrower concept revision. The latter two preserved intentional acceptance-policy
differences and requested shorter answers. No expected label was changed.

The revised compact policy initially looked good on cleanup: Sonnet reported
13/14 positives with 0/10 false reports at 0.60, versus 12/14 and 2/10 for the
shipping prompt. On the 150-pair regression panel it produced 36/40 and 19/110,
versus 36/40 and 9/110. On the public hard examples it produced 4/15 and 3/15,
versus 8/15 and 1/15. The recall/precision tradeoff failed the promotion check.

Opus's revised compact policy improved the private panel from 37/40 positives
and 13/110 false reports to 39/40 and 11/110 at 0.55, but regressed on the public
hard examples from 8/15 and 0/15 to 4/15 and 3/15, including one invalid answer.
The narrower concept revision also increased private-panel false reports.

Haiku needed its existing 2,048-token ceiling: 512-token experiments frequently
returned invalid/truncated answers. At 2,048 and the `balanced` threshold of 0.50,
the revised compact policy lost three cleanup positives, added false reports on
the other panels, and produced an invalid public-panel answer. It was rejected.

These tests used frozen labels, including disagreements that may deserve separate
source review. For example, the Wagtail fixture pair shares an enqueue operation
but has different setup and result contracts. Its expected positive remains intact;
neither calling it negative nor weakening the template rule is evidence of progress.
The small pytest-selective corpus's snapshot retrieval miss also remains documented.

The complete experiment made 1,716 paid attempts, including 38 invalid answers:
1,801,432 input and 434,358 output tokens, approximately $6.98 using the repository
price table. That research spend is separate from replayed PR allowances and is not
invoice reconciliation. Raw source packets and observations remain outside the
repository. These are development/regression results, not a fresh independent holdout.

## Regression checks

The offline tests exercise actual admission and judging with deterministic provider
stand-ins: an oversized request cannot hide a later affordable finding, a request
that fits the full allowance can still be skipped when only the remainder is too
small, a first pass cannot consume its second opinions' allowance, and subscriptions
retain both call limits and previous spending. The new single-judge and escalation
tests failed against prefix-only scheduling before the fix.

```bash
uv run pytest -q tests/test_costs.py tests/test_judging.py
```
