# Consolidation and contextual judging validation

The production journey is checkout → TypeScript extraction → per-peer detection/ranking → cached/budgeted
judging → source-linked report and sticky comment. Source reads and CLI subprocesses stay real in integration
tests; only GitHub and judge HTTP boundaries are faked. Live judge calibration uses frozen private snapshots
through `scripts/probe_context.py`, separately from deterministic CI tests.

- [x] Workspace CLI check/detect: query changed primary functions, preserve peer identities and source commits,
  allow primary annotations, reject workspace-wide annotations and ambiguous roots.
- [x] Workspace Action single/detect: pass multiline paths, including spaces, through the real CLI and report
  pipeline; preserve primary scope, peer links and preferred-home advice. Fake only GitHub and external judge.
- [x] Destination journey: match both source trees, carry multiple applicable homes into judge state and rendered
  advice; exclude unrelated scopes and reject escaping paths.
- [x] Context extraction: follow imported aliases/local declarations and policy comments, bound large dependencies.
- [x] Cache invariants: changed context or destination reopens even a separate verdict; edits after context truncation
  also reopen; commit-only movement preserves reusable context.
- [x] Ranking: shared repository gets a review slot and one file family cannot monopolize the queue.
- [x] Budget: cached answers are free, excess uncached pairs defer explicitly, subsequent runs progress.
- [x] Judge response integration: destination uncertainty does not erase duplication; concrete separation and
  probable boilerplate do suppress it. This verifies response handling, not model accuracy.
- [x] Live calibration: final scoped configuration retains 9/10 labelled positives, rejects all five known
  platform/schema negatives, and reduces false positives from 17 to 5 on the frozen 44-pair sample. Remaining
  errors, time and token cost are recorded in `docs/context-probe.md`.
- [x] Architecture guidance remains available outside destination scopes; guidance changes reopen cached verdicts.
- [x] Full suite on the integrated upstream baseline: 359 tests, 100% statement coverage; Ruff, wheel build and
  offline self-check pass. Additional destination escaping cases exercise both report summary and table output.
- GitHub checks on each PR are the authority for its current head, including the live self-check and all adopter
  workflows. The live probe preserves source hashes and raw answers for review.
