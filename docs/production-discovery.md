> `balanced` is now the recommended function default. Keep model ownership findings in the separate agent review lane.
> See [defaults and migration](judges.md) before upgrading an existing baseline.

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

Pairs are asked up to the judge's own `workers` at a time (`anthropic`, `http` and `command`: 4; `jev`: 8;
subscription judges: 2). Every reservation in a batch commits before its call, and a batch holds a single lane,
so exploration still waits for every baseline answer. Each pair is its own call: one failure leaves the others'
verdicts. A residual pass asks one pair at a time, because its admission requires earlier attempts to be
answered. Raise `workers` in the judge's options for more concurrency, or set it to 1 to ask serially.

A pair that the dollar budget or a call cap (per tree, per campaign, exploration, subscription or
`max_judgements`) leaves unasked is `budget_deferred`. This is a budget gap, not a failure: `--require-complete`
on a check warns about it and passes, and a later push asks again while the campaign has room. A failed or
interrupted call, or a pair whose evidence this tree already tried, is still incomplete and fails a strict
check. Initializing or advancing a baseline needs every pair judged, budget-deferred ones included.

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

## Experimental residual recovery

`discovery.residual_comparers` opts into a second pass under the **same campaign allowance**. It is empty by
default. Add this key to the existing discovery table; retain the adopter's existing comparer list and other
settings:

```toml
[discovery]
residual_comparers = [
  { use = "tfidf", neighbours = 100, min_similarity = 0, min_similarity_small = 0 },
]
```

Discovery must be enabled. With `preset = "balanced"`, it is enabled automatically and the protected pass keeps
both TF-IDF exploration and the operation-block route. Explicit comparer lists remain explicit. The
[complete example](../examples/residual-discovery.toml) uses the otherwise unchanged balanced preset and $0.04
total allowance. All judges still require adopter-owned credentials; without a judge this only lists candidates.

Detection completes the original candidate array, including filters, comparer identities and advisory relatives,
before appending deduplicated residual candidates. Judging runs the complete configured protected pass first.
Only then can its unattempted deferred exploration and the appended candidates use the remaining dollars, in the
existing query-fair order. Floor and depth are ordinary TF-IDF configuration, not a new comparer. A zero floor
still searches the sparse index's retained postings; it does not enumerate every unrelated pair.

Native admission computes residual room inside the existing SQLite reservation transaction. It bypasses the
paced exploration credit and the fractional lifetime exploration dollar/call reserves. It retains prior spending,
all attempts, conservative holds, actual-usage settlement, the total dollar/call caps, per-revision call limits,
exploration calls per revision and `max_judgements`. Residual settlements do not refill protected credit. Exact
source, context and judge identity still govern verdict reuse; scheduling metadata does not change the question.
Repeating a revision cannot retry failed or abandoned attempts or mint capacity. A later revision may retry
within the same remaining allowance. Unresolved baseline work bars recovery. Failed or unfinished attempts on
the current revision also bar residual reservations, including attempts owned by another process. These barriers
are deliberately conservative; in-flight work can be revisited after settlement, but an abandoned hold is retained.

This borrows capacity reserved for **future baseline evidence**. It preserves the current protected pass's
admissions, not future-push coverage. Later pushes may have less money and fewer calls, including when the option
is subsequently disabled. Concurrent processes share atomic accounting; they must use the same complete source
inventory and policy for a meaningful protected-prefix comparison. Persistent storage is still required.

This option supports single-judge native campaigns (`check` and split `detect`/`judge`). Ordinary estimated
admission, scans and sweeps do not implement this policy and reject residual judging without a campaign. Scheduled
escalation remains unsupported. Candidate/report schema 14 records `residual`; campaign schema 2 records residual
attempts. Older records load with `residual = false`. Upgrade all producers and workers together before enabling
it; older workers do not understand the phase marker.

No default profile is changed. The implementation has been tested against the complete balanced prefix at
matched budgets, but promotion is held on **report quality**. TF-IDF-only ablations, additional emitted pairs and
preservation tests do not establish independent useful-family gains or acceptance.

### Optional recovery judge

To keep the complete balanced pass on its original policy and use the measured grounded policy only for newly
funded recovery questions, add this table alongside `residual_comparers`:

```toml
[discovery.residual_judge]
use = "anthropic"
model = "claude-haiku-5-5"
prompt_policy = "shared-operations-grounded-claim-v1"
max_tokens = 2048
max_retries = 0
retry_malformed = false
```

The [complete example](../examples/grounded-residual-discovery.toml) retains the original balanced judges,
comparers, thresholds and $0.04 campaign cap. The plugin uses the adopter's existing `ANTHROPIC_API_KEY`.
The optional field defaults to absent: the existing judge, verdict keys and protected pass are unchanged.
It must name an explicit judge plugin, with residual comparers enabled; it is not an escalation or a second
opinion on answered pairs. Arbitrary installed judge plugins use the same constructor-options contract.

The frozen template is exactly the one measured in PR #123, SHA-256
`bcec108a5d1c316c1557a12434b14c209fb1899b277da83b26ac5de5346933a1`. With the example's model and output limit,
the exact judge version is `dry-grounded-claim-v1-bcec108a5d1c316c:claude-haiku-5-5:output=2048`.
The template is frozen separately from the evolving shared-operations prompt; changing either cannot silently
change this tested policy. There are no fallback requests or retries in this configuration. This wiring does
not claim comparative usefulness or acceptance; matched comparative replay remains the acceptance gate.

The complete original pass runs before the optional plugin is loaded. No main judge means no recovery judge;
an empty queue, unresolved baseline, failed/inflight campaign or exhausted cold campaign does not initialize it.
Previously answered recovery work can still load the current plugin to validate and read its exact-policy cache,
even after exhaustion or a later failure. Every newly admitted pair gets one selected-judge call. Reservations
use that judge's actual prompt, configured output ceiling and configured prices; known provider usage settles
at those prices, while unknown usage retains the reservation. All campaign dollar and call caps remain shared.
The summary names both full judge versions and records their separate calls, costs and failures in `spend`.

Configured recovery uses a separate cache namespace keyed by the full judge identity. It neither reads nor
overwrites original-policy verdict slots, even when both judges share a name. A rollback keeps the original
cache keys. Exact source and version checks still apply within the recovery namespace. Campaign schema 3 adds
judge-independent `source_evidence` and a subscription flag to attempts: switching policies cannot charge the
same source twice on one revision when either attempt is recovery. Old campaigns remain readable and all holds
remain charged; schema-2 attempts under the original judge also bar a second recovery question on that revision.
A new revision may fund a new protected question under its original policy, subject to remaining capacity.
Candidate/report schema 14 and the verdict record payload are unchanged; upgrade workers together before use.

### Measured residual behavior

A provider-free replay on product base `2aab042c256141383c7c731b7ba6097dd2db53b3` compared the unchanged
balanced pass (including operation blocks) with protected balanced followed by zero-floor TF-IDF depth 100.
Both arms used the same $0.04 native campaign cap on each of 12 frozen historical cases. Actual `Detector`,
`Judging` and `CampaignStore` ran in separate processes; a recorded-answer judge supplied independently audited
exact-question responses and their original token usage. No new provider calls were made.

| Native campaign comparison | Preserved report occurrences | Lost | Added | Control logical dollars | Residual logical dollars |
| --- | ---: | ---: | ---: | ---: | ---: |
| 11 complete paired campaigns | 24 | 0 | 10 | $0.0382533 | $0.0969322 |
| Remaining campaign, known prefix only | 2 | 0 | 2 | $0.0035410 | $0.0140067 |

An occurrence is one reported pair in one campaign, not an independently useful operation or family. All 12
protected candidate passes, admitted attempts and charges were preserved exactly. Each individual campaign
stayed below $0.04; table costs sum separate campaigns. One treatment reached a previously failed question
without a reusable successful answer. Its $0.0060248 conservative hold remains charged, with no retry; its
known-prefix report is reconstructed and does not establish a completed campaign result.

The independent actual-rationale audit, reproduced by the coordinator, classifies the 12 added occurrences as
**3 useful, 6 nonuseful and 3 disputed** (11 unique pairs: 3 useful, 6 nonuseful, 2 disputed). In the 11 complete
campaigns, the 10 additions comprise 3 useful, 5 nonuseful and 2 disputed. All three confirmed claims occur in
`gigaverse-app/gigaverse-ai`; the required two-repository adoption bar is not met. Several other reports name
tiny guards or already-shared operations even when a different useful fragment exists elsewhere in the pair.
Seven source-useful pair exposures therefore do not mean seven useful reports. Disputed claims receive no
confirmed usefulness credit. This is an outcome audit against frozen judgments, not an expanded gold dataset.

A bounded ownership review of four baseline findings and the three confirmed additions in two campaigns found
one new useful campaign family claim, one new owner in an existing family, and one redundant alternate pair.
The first claim also adds an owner while retaining the already-exposed one, so the first two claims add two
independent owner memberships in total. All occur in AI; none is a globally new family in the frozen source
history. This review did not expand the gold dataset or inspect other campaigns.

The [public replay scripts and fixture instructions](../examples/research/residual-budget/README.md) use the
private `residual-native-replay-v1` dataset, pinned to corpus merge
`f14564f05f1541bc1ee8557b099253d82e7fa70f`. No private source or answers are included in the product example.

The implementation remains a draft: budget and candidate preservation passed, while report quality prevents
promotion. This measurement uses the original judge; a separate grounded-policy experiment has not changed
these results or this implementation. The frozen single-revision traces agree with the research native replay,
but the product has stricter barriers after
deferred baseline work or failed/in-flight attempts and does not reset protected pacing credit. Normal estimated
admission was not implemented or evaluated. This measurement does not establish future-push preservation,
general policy equivalence, or product acceptance.

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
    rev: v1
    hooks:
      - id: dry-lint
        additional_dependencies: ["dry-lint[hooks]"]
        args: [--env-file, .env]  # inherits preset=balanced from repository settings
```

Run `pre-commit install`. Export `ANTHROPIC_API_KEY` or keep it in the untracked optional `.env` file. The hook
checks staged Python, JavaScript and TypeScript. No PR code is executed by dry-lint. Split CI `detect` and `judge`
carry lane and tree provenance in schema 5; old candidate files default to the baseline lane.

## Validation

The production tests exercise SDK responses, staged/committed feedback, retries, concurrency, inherited spending,
and baseline preservation. Fresh historical validation uses `scripts/replay_production.py`, with independently
reviewed evidence before paid judging. [Results and promotion](production-discovery-results.md) support agent hooks; a fresh
negative-only PR is a precision/control observation, not evidence of positive recall.
