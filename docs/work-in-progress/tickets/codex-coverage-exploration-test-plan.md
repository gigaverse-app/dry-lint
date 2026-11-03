# Coverage exploration spike test plan

The public entry point is `scripts/replay_coverage.py`. It consumes canonical candidate snapshots and simulates
unit-cost completed/failed judgments. It does not call judges or change production defaults.

- [x] Replay unchanged snapshots: fixed shortlist stalls, broader scheduling progresses without paying twice.
- [x] Bound per-run and cumulative attempts, including failures and zero budgets; deferred work stays explicit.
- [x] Deduplicate unordered pairs across sources; reject contradictory evidence within one snapshot.
- [x] Invalidate simulated coverage on either-side code, context or judge-policy changes; ranking-only changes reuse it.
- [x] Persist and resume ledger through JSON; same logical run retries do not advance or spend again.
- [x] Preserve a fair aging lane under continuous arrivals and one-call runs.
- [x] Exercise the CLI with actual detector-produced candidate files, then run frozen real-repository probes.
- [x] Run full tests, Ruff, build and dry-lint on itself; inspect CI for the exact pushed head.

Validation: 30 focused tests; both experiment scripts have 100% statement coverage. The full local suite with
Dryer passed (421 tests before the final additional provenance test), with 100% production statement coverage.
Ruff and the package build passed. CI run `41637394347` passed on implementation commit `39a3f97`, including
Python 3.11/3.13 and the live dogfood judge. Frozen-tree probe results and their limits are in
[`docs/coverage-exploration.md`](../../coverage-exploration.md#built-spike-and-frozen-tree-results).

Real historical PR replay, actual judge quality, currency/latency budgets and concurrent live storage remain
separate increments in the design. Frozen snapshots only test repeated discovery opportunities.
