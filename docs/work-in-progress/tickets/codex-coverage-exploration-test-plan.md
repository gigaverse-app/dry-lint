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
- [ ] Run full tests, Ruff, build and dry-lint on itself; inspect CI for the exact pushed head.

Real historical PR replay, actual judge quality, currency/latency budgets and concurrent live storage remain
separate increments in the design. Frozen snapshots only test repeated discovery opportunities.
