# Balanced discovery with reviewed feedback

`--preset balanced` uses Haiku's shared-operation judge at a 0.5 reporting and blocking threshold. It is intended
for a coding agent that reviews findings and fixes real duplication. The previous `agent-haiku` preset keeps its
baseline-only behavior. Existing unattended presets and explicit thresholds keep their contracts.

## What runs at commit time

The detector proposes the ordinary cross-file baseline first: three neighbours at the existing TF-IDF floors.
A second index proposes up to 20 neighbours at 0.35 similarity, including same-file pairs. It never replaces a
baseline pair or changes its rank. Both lanes use the existing structural filters. The judge reads candidates
as text; extraction and historical replay never execute the target repository.

The production scheduler uses exact-source cached verdicts, prioritizes pending baseline work, then explores
unexamined pairs. Calls are spread across changed functions, accounting for previous attempts. A changed pair
reopens even if its normalized structure hash did not change. An unaffordable baseline pair leaves exploration
deferred; it does not donate its protected capacity.

## Cumulative allowance

| Limit | Balanced default |
| --- | ---: |
| Total campaign dollars | $0.04 |
| Dollars reserved from exploration for baseline | $0.025 |
| Exploration credit earned per distinct tree | $0.006 |
| Exploration credit bank / lifetime maximum | $0.015 |
| Calls per tree / campaign | 20 / 200 |
| Exploration calls per tree / campaign | 10 / 75 |

A local campaign defaults to the Git branch, shared by its worktrees through the common Git directory. Use
`--session TASK` to name a task explicitly, including detached checkouts. Reusing a branch reuses its allowance;
choose a new session for a new task. GitHub PR runs use repository + PR number. Changing prompts, rerunning a tree,
or restarting the process does not reset the campaign. Earlier legacy PR spend is imported conservatively.

The SQLite ledger is `discovery.sqlite3` beside the verdict directory. `--discovery-state PATH` selects persistent
storage explicitly. Atomic reservations prevent concurrent local processes from over-admitting calls. Each
reservation commits before contacting the provider, using a conservative input bound and the configured output
ceiling. Returned token usage settles the charge, including cache tokens. Failed requests without usage and
interrupted processes retain their reservation. Balanced disables SDK automatic retries; a later tree can retry
unresolved evidence using fresh capacity. Unknown-price judges and scheduled escalation are rejected before calls.

The ledger must survive between invocations. Local hooks and hosted CI do not share one distributed wallet.
An Actions cache is an optimization that can be evicted, not durable storage: for a strict CI campaign cap, use
persistent storage and serialize the PR's state lifecycle. `--discovery-state` can point at a persistent runner
volume. Deleting the ledger resets its allowance. The report says how much was accounted, including reservations,
and separately identifies deferred work. A successful check is not an exhaustive duplication audit.

## Fix or dismiss a finding

Balanced checks save their latest report at `git rev-parse --git-path dry-lint/last-report.json`, independently
for each worktree; `--report PATH` selects a report explicitly. Each finding shows a stable pair key.

```bash
dry-lint feedback dismiss PAIR_KEY --reason "Different transaction contracts: ..." --reviewer coding-agent
git add .dry-lint-feedback.json

# After implementing and staging a repair:
dry-lint feedback fix PAIR_KEY --reason "Both callers now use the canonical helper" --reviewer coding-agent
git add .dry-lint-feedback.json
```

Use `--from report.json` to review a saved report. Decisions live in the reviewed repository file
`.dry-lint-feedback.json`, with pair, exact source/context digest, reviewer, reason, action and staged tree.
No source code or credential is copied into that file. A dismissal suppresses only that exact evidence;
changing either function or its context reopens it. Existing inline `distinct-from` and configured patterns
remain available for durable intentional distinctions.

A fix requires staged source to have changed or an endpoint to have been removed. It records the reviewer's
claim; it does not manufacture a negative model verdict or suppress a restored duplicate. The next check judges
the repaired source normally. A disappearance alone never counts as a confirmed fix. Staged checks read feedback
from the index; an unstaged dismissal cannot clear staged source. Committed checks read feedback from HEAD.

## Hook setup

```yaml
repos:
  - repo: https://github.com/gigaverse-app/dry-lint
    rev: <reviewed-release-or-commit>
    hooks:
      - id: dry-lint
        additional_dependencies: ["dry-lint[hooks]"]
        args: [--preset, balanced, --env-file, .env]
```

Run `pre-commit install`. Export `ANTHROPIC_API_KEY` or keep it in the untracked optional `.env` file. The hook
checks staged Python, JavaScript and TypeScript. No PR code is executed by dry-lint. Split CI `detect` and `judge`
carry lane and tree provenance in schema 5; old candidate files default to the baseline lane.

## Validation

The production tests exercise SDK responses, staged/committed feedback, retries, concurrency, inherited spending,
and baseline preservation. Fresh historical validation uses `scripts/replay_production.py`, with independently
reviewed evidence before paid judging. Its results and the promotion decision are recorded separately; a fresh
negative-only PR is a precision/control observation, not evidence of positive recall.
