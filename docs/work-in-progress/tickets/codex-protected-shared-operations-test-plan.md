# Shared operations and protected revision capacity

Use the previous six-PR pilot only as a development set. Freeze the new prompt and scheduler before judging
fresh PRs. Screen fresh PRs for nonempty baseline candidate pools, independently review those candidates, and
retain all screened outcomes. Enrichment for baseline positives is explicit, not a population precision sample.
Do not tune on the final holdout. Keep a $10 physical usage-priced ceiling and private source/labels outside Git.

- [ ] SDK integration: opt-in shared-operation prompt reaches the provider, preserves legacy behavior and has
  a separate cache identity. Exercise real judge/store wiring against the existing fake provider.
- [ ] Scheduling: early exploration cannot spend reserved future-baseline calls or dollars; late baseline work
  remains admissible, under the same cumulative ceiling. No future candidate inspection or known-history length.
- [ ] Reserve exhaustion remains explicit; changed evidence reopens, cached work is free, and retries do not
  replenish a campaign. Exercise historical replay through actual observed provider usage.
- [ ] Development regression: measure old/new judge over the previous positive and negative evidence, including
  thin adapters and task cleanup. Record every draw and avoid treating old data as held-out validation.
- [ ] Fresh PR validation: paired judge and scheduler comparisons, baseline-positive preservation, first-report
  delay, current/ever recall, precision, actual tokens and dollars, with PR-cluster uncertainty and scope limits.
- [ ] Run appropriate full tests, lint, build, self-check and exact-head CI. Apply balanced promotion gates;
  insufficient evidence leaves the experiment opt-in and names the remaining gaps.

No PR template was found. The existing runtime has a cumulative estimated PR budget; this experiment must not
silently reinterpret that estimate as a provider-metered concurrent reservation ledger.
