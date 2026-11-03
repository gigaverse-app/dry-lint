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
- [ ] Live calibration: retain at least 8/10 labelled positives, reject five known platform/schema negatives,
  and reduce false positives on the frozen 44-pair sample. Record remaining errors, time and token cost.
- [ ] Final full suite, 100% statement coverage, Ruff, wheel build, self-check and GitHub CI on all four PR heads.
