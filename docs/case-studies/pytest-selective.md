# Duplicate debt exposed four correctness bugs

Use duplicate findings to compare the guarantees each implementation preserves. In
[pytest-selective #77](https://github.com/gigaverse-app/pytest-selective/pull/77),
retiring seven accepted pairs fixed four existing bugs, clarified shared ownership,
and exposed a tempting consolidation that would have weakened selection safety.

The comparison is pinned to
[`ae13063`](https://github.com/gigaverse-app/pytest-selective/tree/ae1306377dda82d1d0a6fa0b43dbb612d69d72b2)
before the cleanup and
[`4ab22f3`](https://github.com/gigaverse-app/pytest-selective/tree/4ab22f35385bb0e3225cf9d40877b559d45c23dc)
after it. This is one reviewed cleanup, not a population estimate of how often
duplication causes bugs.

## What changed for users

| Existing bug | Observable failure before | Result after |
| --- | --- | --- |
| Audit Git helper lacked repository isolation | A calling hook's `GIT_DIR`/`GIT_WORK_TREE` could make the audit inventory another checkout | The requested repository wins through the shared Git executor |
| Checker path helper omitted the dot root | Omitted `include`, `["."]` and `["./"]` could report no affected files after a real source change | Changed files and their affected importers remain in scope |
| Hygiene discovery omitted cache exclusion | A stale `__pycache__/test_*.py` could create a false test-isolation finding | Hygiene uses the canonical inventory's cache exclusion |
| Expansion guard copied index contents without timestamps | A same-size edit within Git's index timestamp window could look unchanged | The copied index retains the timestamp used by Git's racy-clean check |

The new tests were replayed against the original implementation: **6 failures and
9 passing controls across 15 cases**. The same cases passed against the result.
Three failing include variants represent one bug, so this is **four bugs**, not six.
The snapshot timestamp failure existed in the expansion guard before the refactor;
it was not merely a defect introduced by moving the code.

The planner's behavior for `assume-unchanged` and `skip-worktree` is a preserved
guarantee, not a fifth bug fix. Both flag controls passed before and after. An
intermediate attempt to copy its index would have hidden those edits, and was
rejected before merge.

## What became simpler

Git execution and environment filtering now have one owner. So do test discovery,
relative module-name conversion, Unicode normalization, dotted-package ancestry
and membership, and repository path containment. The expansion script still works
without installing the package because its shared owners remain stdlib-only.

Production Python shrank from **5,904 to 5,875 physical lines**, and function/method
definitions from **247 to 244**. Those counts include comments/docstrings and nested
definitions. Tests and documentation grew; the whole PR is not a net-line reduction.
The main simplification is fewer independent rules to keep consistent.

The snapshot implementation explicitly preserves two policies:

```text
one private-index lifecycle
  planner   -> rebuild staged entries -> include all inputs, even index-hidden edits
  expansion -> copy index + timestamp -> update Python paths, retain the stat cache
```

Sharing a lifecycle does not require erasing caller policy. A useful review question
is: which guarantees would disappear if every caller used the apparently simpler copy?

## Performance: no speedup claim

A paired Windows/Python 3.14.7 probe used eight measured samples per implementation,
after two warmups, alternating before/after order in persistent separate processes.
Snapshots used the same real Git repository with 1,000 Python files and one dirty
file. Graph construction used the same fixed pytest-selective tree (`ae13063`),
fresh SQLite databases for cold runs and a previously built graph for warm runs.
Process startup is excluded; OS caches are warm. Every paired tree/graph result
matched. Lower elapsed time is better; Git-call counts explain work, not user benefit.

| Operation | Before median ms (min–max) | After median ms (min–max) | Git calls before / after |
| --- | --- | --- | --- |
| Planner snapshot | 402 (310–541) | 353 (307–562) | 6 / 6 |
| Expansion snapshot | 247 (188–386) | 280 (229–305) | 3 / 4 |
| Cold graph | 507 (438–687) | 528 (435–685) | 4 / 4 |
| Warm graph | 44 (38–105) | 43 (39–50) | 1 / 1 |

The ranges overlap and do not establish an end-to-end speedup. Expansion now checks
the explicit repository root before snapshotting, adding one Git process. Its
observed median increased by about 32 ms; that is a cost to disclose, not a saving.
This small local probe is not a CI throughput or billing measurement.

## What the zero means

The accepted backlog went from **7 remaining to 0**, with the same original nine
pair identities and detection contract. Two entries had already been retired by
rejudgment before this cleanup. Do not claim nine refactors or nine bugs.

The [independent hosted audit](https://github.com/gigaverse-app/pytest-selective/actions/runs/42029824004)
made 44 fresh judgments and reported zero findings. Its update reused all 44 verdicts
and opened no metadata PR. The local unchanged repeat was byte-identical and made
zero model calls. [Platform CI](https://github.com/gigaverse-app/pytest-selective/actions/runs/42029723763)
passed; local full-suite validation passed 805 tests with two skips.

Zero means no remaining accepted pairs and no findings among this detector's
candidates under this policy. It does not prove that every possible semantic
duplicate has been found, nor that every refactor is correct without behavior tests.

## Regression goldens

[The public panel](../../examples/pytest-selective-gold.toml) freezes eight positive
before-cleanup pairs and four separate after-cleanup adapters, with source revisions,
symbols and rationales. It covers drift, shared sub-operations inside larger
functions, and forwarding/adaptation after ownership is consolidated.

These labels come from the implementation agent's source review and executable
consumer regressions. They are not independent three-vendor labels, a random sample,
or a fresh holdout. Keep them separate from the calibrated benchmark population.
No judge scores or prompt thresholds were changed to fit this panel.

A live `dry-v2:claude-sonnet-5-5` judgment on 2026-11-05 flagged all eight positives
(scores 0.70–0.90) and kept all four after-cleanup controls separate (0.05–0.12),
at the `sonnet` preset's 0.60 report and 0.70 failure thresholds. This is binary
duplicate/separate agreement, treating `drifted` as a duplicate; it does not claim
agreement on every drift annotation. The run used 9,558 input and 2,263 output tokens.
One run on this deliberately selected panel does not establish general accuracy.

Default top-three TF-IDF retrieval finds seven of the eight positives in the reduced
frozen before-corpus. Replaying the unchanged snapshot pair against the full tracked
scope at `ae13063` also misses it. Both functions' extracted tokens are identical
between these two evaluations:

| Retrieval corpus | Functions | Snapshot similarity | Required floor |
| --- | ---: | ---: | ---: |
| Frozen positive panel | 15 | 0.275 | 0.5 |
| Full repository at the pinned pre-cleanup revision | 272 | 0.310 | 0.5 |

TF-IDF drops tokens appearing in more than 30% of indexed functions. For example,
`w:git` appears in 5/15 panel functions and is dropped, but in 21/272 repository
functions and is retained. That changes the score without changing either function,
but does not recover this pair. The original baseline does not include it either.
The earlier claim that the full sweep retrieved these frozen bodies was unsupported.
Do not relabel the pair or claim retrieval coverage from judge agreement. Retrieval
comparisons need a pinned corpus as well as pinned pair bodies.

```bash
uv run dry-lint bench --gold examples/pytest-selective-gold.toml --preset sonnet
```

Use the adopter's own credentials. Judge agreement on this small panel is diagnostic;
the before/after behavior tests establish the four bug claims. Regressions should
test both sides: notice independently repeated policy before, and stop asking to
extract behavior that already delegates to one owner after.
