# Budgeted discovery validation

Keep the previous ten PRs as development/regression data. Test Haiku with the existing shared-operation prompt
and a concise Sonnet prompt before freezing a candidate policy. Compare fixed, unreserved refill, and protected
discovery under the same $0.04 cumulative PR allowance. Test a mixed policy retaining Sonnet for baseline
candidates and using the cheaper judge for exploration. Count all paid failures; stop unknown usage. Keep this
turn's physical live allowance at $5, separate from the previous experiment's $3.079554.

Flexible pacing should spend a bounded dollar slice on exploration per unique revision, instead of exactly one
call. Reserve future baseline capacity without inspecting future commits. Compare against the actual fixed
counterfactual at every commit; do not describe a finite reserve as unlimited baseline preservation.

- [ ] Model-specific accounting: real SDK/fake provider, returned-model validation, model-aware maximum-cost
  reservation, cache pricing, distinct prompt/model keys, failed responses retained.
- [ ] Compact prompt: real judge integration, legacy unchanged, output cap and cache identity verified.
- [ ] Mixed judging: baseline upgrade reopens cheap evidence; scoring validates the actual per-pair prompt/model.
- [ ] Flexible pacing: reserved calls/dollars, per-revision exploration dollars, identical-run idempotency,
  changed evidence, no overspend, no automatic retries of accounted failures.
- [ ] Live development replay: report precision and recall before/after judging, per-commit cumulative dollars,
  baseline losses, first discovery, failures and observed latency; retain all tested arms.
- [ ] Freeze a policy before viewing fresh verdicts. Validate on independently reviewed fresh PR histories with
  baseline positives and negative controls. Keep unknown/borderline labels out of binary denominators.
- [ ] Full tests, lint, build, detector self-check and exact-head CI. Apply existing promotion gates without
  weakening them; publish an opt-in recommendation if balanced is not supported.
