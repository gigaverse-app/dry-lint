# Sweep a repository and ratchet its duplication

dry-lint is a linter. It lists suspected duplication and fails checks according to the configured judge and
threshold. A human or agent decides whether to refactor, runs the tests, and opens the pull request.
dry-lint does not edit application code, create branches, or open pull requests.

An adopting repository can accept its existing debt without accepting new copies. A baseline records specific
judged duplicate pairs and their logic hashes. Removing one allowance never creates room for another pair.

## Initialize once

Choose the repository's judging preset and credentials as described in [judges.md](judges.md). For example,
with the adopter's `ANTHROPIC_API_KEY` and the `anthropic` extra installed:

```toml
# .dry-lint.toml
preset = "sonnet"
[budget]
usd = 0.25
```

```bash
dry-lint sweep --init --budget-usd 5 --readme README.md --repository OWNER/NAME
```

Review and commit `.dry-lint/baseline.json`, `.dry-lint/progress.json`, the settings and README. `--init` refuses
to overwrite an existing baseline. The larger one-off budget does not change the configured PR budget.
Every proposed pair must have a completed judgment before initialization writes anything.

The sweep queries every extracted function using the same nearest-neighbour detector as PR checks. Its audit
includes both warnings and blocking findings. Only pairs at the blocking threshold receive allowances.
This is a detector's bounded candidate set, not exhaustive proof that all semantic duplication was found.
The default scope excludes test and migration directories; inspect the include/exclude settings before adopting.
Unsupported or invalid source cannot silently disappear from a strict scan.

## Review the audit and clean up deliberately

```bash
dry-lint sweep --budget-usd 5 --report audit.json --output audit.md
# A human or agent reviews the list, refactors selected code, and runs its tests.
dry-lint sweep --update --budget-usd 5 --readme README.md --repository OWNER/NAME
```

The first command is read-only except for explicitly requested report files and the verdict cache. The second
updates metadata after a complete audit. Commit those metadata changes with the refactor. Both commands fail
if they discover a new blocking duplicate; neither can broaden the baseline.

Known debt is revisited even when its pair falls out of the nearest-neighbour ranking. A removed function or a
new `separate` verdict clears its allowance. An ignore, distinct-from comment or declared pattern dismisses it,
which is recorded separately and never counted as cleanup. A changed function that remains a duplicate is new
debt until it is fixed or explicitly dismissed. Moving or renaming code is subject to fresh detection.

Detection scope, extractors, comparer, thresholds and judge configuration are bound to the baseline. Changing
them requires an explicitly reviewed migration; ordinary sweeps cannot manufacture progress by narrowing scope.
Budget changes and human pattern decisions do not change that detection contract.

## Make the CI check required

```yaml
- uses: gigaverse-app/dry-lint@v1
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
    plugins: anthropic==2.4.0
    baseline: .dry-lint/baseline.json
    require-complete: 'true'
```

`baseline` implies complete judging. Missing credentials, skipped/deferred judgments and failed escalation
fail with exit 2. New blocking duplicates exit 1. Accepted unchanged debt exits 0. The normal unbaselined,
non-strict candidate-only mode retains its existing behavior.

Baseline enforcement rejects `--warn-only` and ignores the override label. Deliberate distinct concepts must
be documented using the existing inline/pattern decisions, rather than widening an allowance.

For a local equivalent, use:

```bash
dry-lint check --base origin/main --baseline .dry-lint/baseline.json --baseline-ref origin/main --require-complete
```

`--baseline-ref` verifies that the proposed baseline cannot widen the target branch's allowances. The Action
does this automatically for same-repository PRs. Fork judging reads the trusted default branch's baseline.
Keep a fork's detection job named `dry-lint detect`; require the separate judged `dry-lint` check, never the
detection-only job. Install the [fork judge workflow](../examples/dry-lint-judge.yml) with the same baseline and
strict inputs. Branch rules must require `dry-lint` from GitHub Actions.

Set the Action's `python-version: '3.14'` when the repository uses Python 3.14 syntax. The default parser is
3.13, independent of the application's installed dependencies. Index publishers and consumers must use the
same parser version; an incompatible index is rebuilt under the existing contract validation rules.

For the full setup, including local hooks, PR accounting and a standing ratchet PR, use the
[adoption playbook](adoption-playbook.md) and [audit workflow example](../examples/dry-lint-audit.yml).

## Periodic audits

Use `mode: sweep`, the same judging inputs, and an explicit audit budget in a scheduled or manually dispatched
workflow. The Action writes its audit to the job summary and `$RUNNER_TEMP/dry-lint/report.json` and `comment.md`.
Retain these as workflow artifacts. It does not commit files or open PRs. A newly discovered blocking pair
outside the accepted baseline fails the audit so a maintainer can investigate it.

## README sticky and Shields.io badge

`--readme README.md --repository OWNER/NAME` maintains a block between `dry-lint-progress` markers. It preserves
the surrounding README, lists remaining/retired/dismissed pairs separately for functions and models, and links to
both baselines and the audit workflow. Use `--branch`
when the published default branch differs from `main`.

With the repository's counter key and a configured model baseline, the sign shows three independent counts:
confirmed function duplicates kept out of pull requests, read live from the
[global counter](../README.md#the-counter), accepted function pairs remaining, and reviewed model pairs remaining.
The latter two tiles also show retired and dismissed pairs. The table below the image keeps these counts
readable without the counter service. Without a model baseline it says **Not initialized**, not zero.
The backlog counts travel in the sign's address, so they change only when the block is refreshed.
In GitHub Actions the sweep takes the key from the repository's own id
(`GITHUB_REPOSITORY_ID`); elsewhere pass `--repository-id`, or the sweep keeps the key of the sign already in the
block. `--no-counter-card` leaves the sign out, for example when the repository opts out of sharing its totals with
`share-totals: "false"`; the block then shows a progress badge and a table instead.

Refresh both inventories after model retirement, or upgrade an existing README without another judge run:

```bash
dry-lint progress --readme README.md --repository OWNER/NAME
```

This command validates and renders existing baseline files without changing them or calling a judge. It reads
the model path from `models.baseline`; `--baseline` selects a custom function baseline. A missing configured file
is an error. `model-baseline --update --readme README.md --repository OWNER/NAME` can refresh the block directly.
Scheduled audits should run `progress` after both ratchets succeed, before staging the metadata PR.

The generated `.dry-lint/progress.json` follows the [Shields.io endpoint schema](https://shields.io/badges/endpoint-badge).
Its badge URL is ready to copy from the README block. It reads the committed public JSON file, so no new service
or deployment is needed. Private repositories need their own public aggregate endpoint to expose a badge.

Counts mean accepted pairs within the configured inventories, not deleted lines or guaranteed repository-wide totals.
**Retired** means a side was removed, or, for functions only, a judge now finds the pair separate. It does not
prove a refactor. Model retirement still requires source evidence; a low atomic score cannot retire it.
They start at zero cleaned. They change only when reviewed metadata is published to the badge's branch.
Existing [PR prevention totals](github-action.md#the-ledger) retain their separate meaning. A baselined pull
request's sticky credits the accepted pairs it cleans up as **from the accepted backlog**, on the same evidence
the audit accepts; that is a preview for reviewers, and the audit stays the authority for the badge.

## State and validation

The baseline has independent schema 1 and stores names, hashes and outcomes, without source code or credentials.
It is reviewed adoption policy, separate from the disposable verdict cache. A missing cache costs rejudging;
an incomplete run cannot change the baseline. Losing the baseline is an error, not permission to start over.

The CLI and Action tests use temporary Git repositories and real judge subprocesses. They exercise unchanged
debt, cleanup, reintroduction, policy/allowance tampering, malformed source, incomplete judgments, fork failures,
read-only audits and idempotent README generation. The Anthropic judge optionally accepts `retry_malformed = true`
for one retry of malformed JSON; a second failure still fails rather than inventing a verdict. This option can
make an additional paid request and is off by default, preserving one-attempt replay accounting.
