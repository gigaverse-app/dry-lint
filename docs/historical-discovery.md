# Historical discovery and live judging

Status: experiment in progress. Production defaults are unchanged.

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
