# Agent feedback at four cents per PR

The lower Haiku threshold is the useful next opt-in. On the reviewed retrieval pools, it reports 19 of 22 final
positive pairs across 20 PRs and 104 commits. The uncertainty cascade reports 12. Neither policy loses baseline
coverage or baseline reports relative to its matched fixed Haiku policy. Every replay stays below $0.04 per PR.

Keep `balanced` unchanged. One regression PR reaches four reviewed false reports on a commit, exceeding the
trial's three-report interruption bound. The runtime also does not yet implement the replay's persistent
exploration scheduler. `agent-haiku` is a separate, explicit local feedback preset with ordinary baseline retrieval.

## Frozen comparison

The first judge is Haiku 5.5, shared-operation prompt v2, maximum 2,048 output tokens. Compare reporting at 0.7
and 0.5 with an uncertainty cascade: first scores in [0.4, 0.7) receive compact Sonnet 5.5, maximum 512 output
tokens, reporting at 0.6. A deferred or failed second opinion retains the first result at 0.7.

Each PR gets $0.04 and 200 calls, at most 20 calls per commit. Reserve $0.025 and 100 calls for baseline work;
exploration and second opinions share the remaining $0.015. Exploration can use ten calls per revision and earns
$0.006 of pacing credit per distinct revision, carrying up to $0.015. Baseline runs first. Identical reruns earn no
new credit. Paid failures consume budget but establish no coverage. Conservative admission reserves maximum
output and an input-byte bound; actual response usage is charged afterward.

| Dataset and policy | Final reviewed positives reported | True / false / unresolved evidence reports | Cumulative replay cost across PRs |
| --- | --- | --- | --- |
| Development: 10 PRs, 45 commits, Haiku 0.7 | 10/18 | 12 / 1 / 1 | $0.075637 |
| Development, Haiku 0.5 | 15/18 | 17 / 7 / 2 | $0.075637 |
| Development, cascade | 11/18 | 13 / 1 / 1 | $0.077782 |
| Regression: 4 PRs, 28 commits, Haiku 0.7 | 1/1 | 2 / 0 / 0 | $0.064264 |
| Regression, Haiku 0.5 | 1/1 | 2 / 2 / 7 | $0.064264 |
| Regression, cascade | 1/1 | 2 / 0 / 0 | $0.064264 |
| Fresh: 6 PRs, 31 commits, Haiku 0.7 | 0/3 | 0 / 0 / 0 | $0.030583 |
| Fresh, Haiku 0.5 | 3/3 | 3 / 0 / 4 | $0.030583 |
| Fresh, cascade | 0/3 | 0 / 0 / 0 | $0.026840 |

Evidence versions and final pairs are different denominators. A function revised twice can produce two reports
of the same final pair. Unresolved includes borderline or unreviewed reports and is never counted as a negative.
These are conditional recalls within reviewed retrieval pools, not exhaustive repository recall.

Development used the previous ten PRs. The policy and fresh reference labels were frozen before fresh paid
judging. Fresh PRs: AI #2787, #3256, #3287; backend #5613, #5624, #5647. The panel includes all baseline versions,
ten nonbaseline versions per larger PR selected by evidence hash, and every version in smaller pools. It contains
62 labels: three positives, 58 negatives, one borderline. The positives span two new operation families, with one
baseline positive. AI #2787 has no extracted changed functions; it remains a zero-op control, not a successful
negative judgment. The four previous PRs are regression evidence, not fresh validation.

## False-positive review and interruptions

After the frozen scoring, the remaining unreviewed Haiku-0.5 reports were inspected without retuning the policy.
In the regression set, five previously unreviewed versions added one true report and four false reports; two
borderline reports remain. In the fresh set, three previously unreviewed versions were false; one borderline
remains. Keep this supplementary adjudication separate from frozen recall: selecting reports for review does not
estimate missed positives.

Across all sets, supplementary review gives 23 true and 16 false evidence reports, with five unresolved. Confirmed
precision is 59%; counting every unresolved report against the policy gives a conservative 52%. Both exceed the
25% agent-feedback floor. However, one regression commit has four false reports, so the interruption gate fails.
Fresh commits have at most two false reports. These counts include recurring findings across revisions; they do
not simulate the developer fixing or suppressing a finding immediately after its first appearance.

False reports often conflate a caller with a helper it already uses, or propose consolidating generic account
validation despite different transaction, lifetime and failure contracts. A real shared operation still needs a
specific reusable rule beyond repeating a call and a guard. Explicit reviewer feedback is preferable to automatically
interpreting a later disappearing pair as a fix. See the [feedback design](agent-reviewed-discovery.md).

## Later commits and actual cost

The 14-commit regression PR's positive first becomes available on commit 10. All three policies find it there and
re-evaluate changed evidence on commit 12, finishing at $0.030918. This is the largest per-PR spend in the trial.
The fresh-set maximum is $0.015226. The matched fixed-baseline audit finds zero lost coverage snapshots and zero
lost report snapshots for all three policies across the 104 commits. This is observed protection on these histories,
not a guarantee of unlimited baseline work after the finite PR budget is exhausted.

Only two second opinions fit the cascade on development histories. None fit the fresh histories. For comparison,
even a tiny pair with the compact prompt and 512-token cap reserves about $0.0108, before larger source snippets.
A short PR may end before the pacing bank can admit a second opinion. Lowering the cheap threshold gives the
coding agent a chance to inspect those candidates immediately, whereas reserving for Sonnet can defer them forever.

New physical research usage: **99 requests, $0.0360279**, 168,474 input tokens, 38,361 output tokens, no failed
responses. Observed request latency was about 2.00 seconds p50 and 6.29 seconds p95; summed API time was 253.55
seconds. Earlier metered answers were reused, with every selected answer charged again to its counterfactual
policy budget. Physical reuse therefore does not make a replay judgment free. The separate live pre-commit probe
uses the production estimated-cost ledger and is excluded from these exact provider-usage totals.

## Shipped boundary and next default gate

The implementation adds an opt-in cheap preset, staged-source correctness, credential loading for isolated hooks,
and a metered cascade replay using the existing escalation contract. A real installed hook rejected a staged
duplicate with live Haiku, preserved an unstaged repair, and accepted the next commit after the repair was staged.
Python and TypeScript staged-source regressions cover the snapshot behavior. The hook runs at commit time;
pre-push snapshot support is not implemented. Local budget is estimated per invocation, unlike the cumulative,
usage-priced research budget. Consumer adoption exposed and fixed an action installer bug where application uv
constraints leaked into the tool's isolated environment.

Before making this `balanced`: implement the scheduler through the production ledger, bound repeated interruptions
without permanently hiding candidates, validate a feedback loop where repairs and explicit dismissals change future
work, and repeat frozen validation on more independent positive families. Keep sampling below-threshold and
unretrieved candidates so lower reporting volume cannot masquerade as a cleaner codebase. The new local preset is
useful for that experiment; the broad default has not met its promotion gate.

Aggregates: [JSON](agent-feedback-results.json) and [per-commit CSV](agent-feedback-curves.csv). Private captures,
source-bearing labels, provider observations and the separate post-verdict label set stay outside the repository.
Use `scripts/capture_history.py`, `scripts/compare_history.py` (including `--escalate-model`,
`--escalate-between`, `--escalate-max-tokens`) and `scripts/score_comparison.py` to reproduce with authorized data.
