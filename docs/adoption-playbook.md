# Full repository adoption

Adopt dry-lint as a loop: catch a copy before commit, explain it on the PR, preserve the value of fixing it,
and steadily retire the duplication that predates adoption. Installing an Action alone leaves parts of that loop open.

This playbook comes from [Due's adoption](https://github.com/gigaverse-app/due/pull/188), its
[cleanup](https://github.com/gigaverse-app/due/pull/190) and subsequent ratchets. Use the current dry-lint interfaces
below rather than copying an old consumer workflow verbatim. [pytest-obligation](https://github.com/gigaverse-app/pytest-obligation)
([adoption PR](https://github.com/gigaverse-app/pytest-obligation/pull/204)) and
[pytest-selective's adoption](https://github.com/gigaverse-app/pytest-selective/pull/74) exercise the same lifecycle.

## Adoption inventory

Work on a branch and open a draft PR early. Inspect the default branch, existing workflows, hooks, settings,
baseline, README markers, CONTRIBUTING instructions, branch rules and available secret **names**. Preserve existing
hooks and debt history. An existing baseline means resume adoption; never delete it and initialize again.

| Surface | Complete adoption means |
| --- | --- |
| Local feedback | `dry-lint` checks staged functions and models with the intended judge and separate baselines |
| Local credit | `dry-lint-trailers` runs at `prepare-commit-msg`, with both hooks installed |
| PR feedback | One sticky, updated in place, including clean runs and incomplete judgments |
| Merge enforcement | The judged `dry-lint` check is required by an active branch rule |
| Forks | Detection without secrets; trusted `workflow_run` judgment supplies the required check |
| Cumulative value | Default-branch pushes fold merged PR ledgers; the README presents prevention and backlog progress |
| Existing debt | A committed, reviewed, pair-specific baseline that cannot expand |
| Model ownership | Source-reviewed model debt and opt-in adopter policies for names, paths and contract boundaries |
| Maintenance | Weekly/manual audit, retained reports, and one standing metadata ratchet PR |
| Human workflow | Contributors know how to reuse, dismiss with a reason, test, and record cleanup |

Check repository **rulesets as well as classic branch protection**. A workflow/job named `dry-lint` does not make
it required. Check repository and inherited organization secrets separately: `gh secret list` alone does not
prove that an organization token is unavailable. Verify its effective permissions with a real run.

## 1. Fix the scope, judge and budget

Inspect `dry-lint config` and the [preset guide](judges.md). Judges use the adopter's own credentials. For the
Sonnet configuration used in Due and pytest-obligation:

```toml
# .dry-lint.toml
preset = "sonnet"
[budget]
usd = 0.25
```

Use `ANTHROPIC_API_KEY` locally and the same repository secret in CI. Keep credentials out of Git and logs.
Choose the parser for the repository's syntax, independently of its runtime dependencies: set the Action's
`python-version` and the hook's `language_version` consistently. Due needs Python 3.14; do not assume every
consumer does. Review include/exclude rules: defaults omit tests and migrations. A full sweep covers the configured
candidate detector, not every possible semantic duplicate. Keep the initial/weekly audit budget separate from
the per-PR budget. Reuse the verdict store between audit and update to avoid paying twice.

Use the `v1` major-version tag throughout adoption: `gigaverse-app/dry-lint@v1` for Actions, `rev: v1` for
pre-commit hooks, and `@v1` for Git-based CLI installs. Do not pin dry-lint to a commit SHA or a minor/patch
release. This keeps adopters on the supported major release without a config edit for every compatible update.
Use published major tags for established Actions too. Exercise staged detection after setup; if an existing
pre-commit environment still runs an older version, refresh it with `uvx pre-commit clean` and rerun the hook.

## 2. Accept the existing backlog once

Install the CLI in its own environment, outside the application's dependency resolution:

```bash
uv tool install --no-config --python 3.13 'dry-lint[anthropic] @ git+https://github.com/gigaverse-app/dry-lint@v1'
dry-lint config
dry-lint sweep --init --budget-usd 5 --readme README.md --repository OWNER/NAME --repository-id NUMERIC_ID
```

Use the real numeric GitHub repository ID (`gh api repos/OWNER/NAME --jq .id`), not its name. GitHub Actions
provides that ID automatically. Locally, omitting it produces a backlog-only badge/table unless the README
already contains the repository's counter sign.

Review each accepted pair and commit `.dry-lint/baseline.json`, `.dry-lint/progress.json`, settings and README.
Keep reports/verdict caches out of Git. For an existing baseline, use `sweep`, then `sweep --update`; omit `--init`.
An incomplete sweep or newly blocking pair must be resolved before updating. Never hand-edit states, hashes,
counts or the detection contract to force a pass. Scope/judge changes need a reviewed migration. See
[baseline semantics](sweeps.md).

### Adopt model duplication alongside functions

Model review is enabled by default in checks, the staged hook and the PR sticky. Keep it enabled during full
adoption, including the trusted fork judge, and verify the Action's `models-checked` output on judged runs.
Fork detection only uploads candidates, so do not require that output on the untrusted detection job.
Record the model inventory and changed-model count from the report. A successful pass with zero changed
models verifies that the pass ran; it does not certify the whole existing inventory as duplicate-free.
Keep hooks on `rev: v1` alongside the Action. An explicit opt-out remains available
through `models: false`, `--no-models`, or repository `models.enabled`, `models.hook` and `models.sticky` settings.

Function and model debt have different authorities. `sweep --init` initializes function debt from a complete
judged sweep. Model debt requires a coding agent or human to read the declarations, nested types, constructors
and consumers, then record exact-source `feedback accept` decisions before `model-baseline --init`. Keep
`.dry-lint/models.json` and `.dry-lint-feedback.json` in Git; preserve them when resuming adoption. Configure
`models.baseline` only after initialization. If no reviewed positive exists, leave it unset and retain review
coverage; do not invent a positive merely to create a baseline. Unknown candidates remain unresolved.

Follow [model adoption](model-adoption.md#establish-and-maintain-reviewed-debt) for the commands. Export the full
inventory with `detect --all` and render it with `judge --judge none` before reviewing. Atomic model scores rank
candidates; they cannot establish debt, dismiss overlap, or authorize consolidation. Matching fields are a
lead to investigate. Trace validation, lifecycle, wire compatibility, exposure and ownership before deciding.

Adopters may supply `models.policies` based on paths, qualified class names and explicit roles. Use `review`
with a priority adjustment for a boundary that needs context; use `discard` only when the repo guarantees that
every matching pair must stay separate. Document the reason and test a matching boundary plus a same-layer
duplicate that must remain visible. Generic request/response suffixes are not universal exemptions.

For example, a repo may keep LLM **prompt schema families** private to their prompt/call file and separate from
**application models**. The family includes the root and all nested structured types, even when only the root
ends in `PromptSchema`. Python `reachable_from` selectors express that family; imported application types
remain application types. Opt into `schema_policy` and the `dry-lint-schema-policy` hook separately when the
repo requires root naming and isolation. Another repo may preserve published Developer API contracts while
Product contracts evolve with its own frontends. Verify the actual compatibility owner, not just the directory.
See [adopter policies](model-adoption.md#adopter-policies) for concrete configuration and static-analysis limits.

## 3. Install both local hooks

Merge this into `.pre-commit-config.yaml`, preserving existing hooks:

```yaml
minimum_pre_commit_version: '4.3.0'
default_install_hook_types: [pre-commit, prepare-commit-msg]
default_stages: [pre-commit]
repos:
- repo: https://github.com/gigaverse-app/dry-lint
  rev: v1
  hooks:
      - id: dry-lint
        args: [--preset, sonnet, --baseline, .dry-lint/baseline.json]
        language_version: python3.13
      - id: dry-lint-trailers
        language_version: python3.13
```

```bash
uvx pre-commit validate-config
uvx pre-commit install
```

The hook's default is the agent preset; explicitly override it when the baseline uses Sonnet. Keep the baseline's
contract consistent. The hook reads judge credentials from the shell or an untracked `.env`. Missing credentials
must fail strict judging. `default_stages` prevents unrelated hooks from accidentally running twice. In shared Git worktrees, hook installation affects sibling worktrees too; use `pre-commit install --allow-missing-config`
when older branches legitimately lack the configuration. This only tolerates an absent configuration; configured
hooks still enforce the baseline. Configuration
in Git does not install hooks in other contributors' clones; put the install command in CONTRIBUTING.

If a general quality job runs `pre-commit run --all-files`, set `SKIP: dry-lint` on that step once the dedicated,
required semantic job owns judging. Keep Ruff, formatting and documentation hooks running there. This avoids
asking the general quality job, including fork runs, for judge credentials. Local hooks still judge normally;
skipping the semantic hook in CI is only valid while the required judged check remains enforced.

When a pair blocks, read both functions. Reuse the existing owner for one concept, preserving its failure and
resource contracts. For genuinely different concepts, add a narrow `distinct-from` comment and reason. Run the
affected tests and restage before retrying. Do not mechanically refactor from the score or add blanket ignores.
The trailer hook carries settled local findings into the commit, so a fix made before the first push still counts.

## 4. Enforce and explain PR changes

Start with [the PR workflow](../examples/dry-lint.yml) and [the fork judge](../examples/dry-lint-judge.yml).
In **both** Action calls set the same judge, parser and these inputs:

```yaml
anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
plugins: anthropic==2.4.0
baseline: .dry-lint/baseline.json
require-complete: 'true'
comment: 'true'
comment-on-clean: 'true'
```

Name the untrusted fork job `dry-lint detect` and the judged check `dry-lint`. Configure the branch rule to require
the latter from GitHub Actions. Fork judgment consumes artifacts with trusted default-branch settings; never run
fork code with judge credentials. Baseline enforcement rejects widening, incomplete judging and warn-only bypasses;
the override label cannot waive it.

Keep the `push` trigger on the actual default branch. Copy the example's concurrency policy: cancel superseded PR
runs, but give default-branch pushes distinct groups and do not cancel them. Those runs fold merged PR ledgers.
Use a shallow head checkout with `persist-credentials: false`; the Action fetches the ancestry it needs.
Keep one sticky publisher per PR, including when combining scopes. See [Action accounting](github-action.md#the-ledger).

## 5. Remember the cumulative value

Keep the PR sticky and the generated `dry-lint-progress` README block. Give the block a visible heading and link it
from the contributor guide. The sign uses the repository ID's hash, not a key guessed from its name. Preserve other
tools' README markers. Use `--branch` when the default branch differs from `main`.

| Measure | Authority and meaning |
| --- | --- |
| New duplicates kept out | PR ledger: a reported pair fixed before merge, plus reported local-hook trailers |
| Old duplicates cleaned | Baseline: an accepted pair removed or now judged separate |
| Remaining | Baseline entries still accepted as debt |
| Dismissed | Explicit human exclusions; never credited as cleanup |
| Judging spend and coverage | Recorded runs, judgments, checked functions and compared pairs |

These are pair counts, not deleted lines, hours saved, or proof the whole repository has no duplication. Backlog
cleanup is separate from prevention. Hook trailers are self-reported evidence. The repository ledger folds each
merged PR once from its sticky; keep clean comments enabled so clean PRs can participate. It lives with the verdict
cache and starts a new counting period if evicted, without reconstructing lost totals. It looks back over the latest
100 merged PRs, so preserve default-branch runs rather than relying on unlimited recovery.

The public counter stores pseudonymous merged-PR contributions once each; it receives no code or credentials.
Its live prevention figure and the committed backlog metadata have different update times. If opting out, set
`share-totals: 'false'` and use `--no-counter-card` consistently; keep local baseline history and the badge/table.
Private repositories need a separately published aggregate endpoint for a public Shields badge.

## 6. Close the weekly ratchet loop

Use [the audit workflow](../examples/dry-lint-audit.yml). The Action's `mode: sweep` is read-only; a later CLI
`sweep --update` records the result using the same store and the CLI already installed by the Action.
Do not resolve/install the moving Action ref again between those steps: a different version can invalidate cached
judgments or change the baseline contract. The workflow opens/updates one `dry-lint/ratchet` branch
containing only baseline, progress JSON and README changes. No application code is automatically refactored.

Configure an adopter-owned GitHub App token or fine-grained token with repository contents/PR write permission
as `DRY_LINT_RATCHET_TOKEN` (Gigaverse consumers use the inherited `GV_CI_CROSS_REPO_TOKEN`). A PR created with the
ordinary `GITHUB_TOKEN` generally does not trigger ordinary PR workflows; the ratchet must receive the same required
checks as other PRs. Keep the token out of source-checkout credentials. A missing token should fail visibly.

Upload any emitted JSON/Markdown reports with `if: always()`, including on a new-debt failure.
An operational failure before report generation may leave no report; retain and link the failed workflow logs,
restore credentials/budget/parser compatibility and retry. Missing artifacts are not a clean audit. New debt, incomplete judging or changed
detection policy must prevent the update step. No-change runs must produce no metadata diff and no new PR. Use a
Conventional Commits title for both bot commit and PR. Do not auto-merge the ratchet or widen its allowed paths.

A cold full audit can expose blocking pairs outside the original baseline even when the adoption PR changes no
functions. Classify those findings before enabling the ratchet: reuse an existing owner for shared policy, and
record narrow exclusions only where the source and tests establish distinct contracts. For example, a Django
commit counter can reuse a framework-free counter while retaining its connection cleanup; real-database and
in-memory crash controls can deliberately keep different failure sites. Different filenames or backends alone
do not justify a dismissal. Report how much of the retired backlog came from actual refactoring and how much
from pairs now judged separate; the library counts both as cleaned, so that total is not a refactor count.
Rerun with the saved verdicts; do not reinitialize a merged baseline or raise thresholds.

### Calibrate a new baseline before its first merge

Independent cold judge runs can move an unchanged historical pair across the blocking threshold. While a
function baseline is still new and unmerged, an adopter may explicitly review those additional pairs into
the initial inventory. First prove the target branch has no function baseline and both implementations,
their logic hashes and relevant context predate the adoption change. Keep the detection/judging policy fixed.
Inspect each additional pair: record an exact source-bound dismissal for independent contracts; retain
genuine or still-unresolved consolidation candidates as visible debt with a review reason. Preserve the
previously accepted pairs and original adoption revision. Report additions and dismissals separately, and
verify that a new or changed copy still fails. This is initial inventory calibration, not cleanup credit.

Once the baseline is on the target branch, its accepted pair set is immutable. A new cold finding then
requires a repair or a justified dismissal; it cannot grow the baseline. Existing model baselines remain
immutable during function adoption, and initial model debt still requires explicit source-reviewed positives.

To clean debt, select a pair from the audit, inspect both contracts, consolidate, run the affected tests, then run:

```bash
dry-lint sweep --update --budget-usd 5 --readme README.md --repository OWNER/NAME
```

Commit that metadata with the refactor, or dispatch the audit after the cleanup merges. A second identical update
must leave the metadata unchanged. A dismissed false positive belongs in code/configuration with its reason.

## Measure what cleanup improved

After a cleanup, describe at least one repeated rule and its new shared owner,
including the callers that now use it. Pair counts track debt history; they do
not count independent refactorings, bugs fixed or performance gains.

- For a bug claim, keep a concrete before-failing/after-passing reproduction.
  Replay the new behavior tests against the pre-cleanup revision, separating existing
  bugs fixed from guarantees preserved and regressions caught during consolidation.
- For a runtime claim, measure the same workload on both revisions. Otherwise
  say that no speedup has been established.
- For a maintenance claim, show how many implementations of the rule became one
  and which caller-specific semantics remain explicit. Report added indirection
  or allocations when relevant; fewer duplicates need not mean fewer lines.
  Compare resource/index ownership, failure behavior and exclusions, not just return values.
- Freeze useful positive pairs and their repaired delegation as regression
  examples. Keep source revisions and label provenance. Mark context-dependent
  judgments as uncertain instead of treating every dismissal as a gold negative.
- Link the actual CI and complete sweep. Reuse verdicts for idempotence checks;
  changing a stochastic answer is not a code repair.

The [pytest-obligation cleanup case study](case-studies/pytest-obligation-cleanup.md)
shows a 32-to-zero backlog with simpler ownership, roughly unchanged source size,
no demonstrated functional bug fix and no measured runtime speedup. Its public
gold pairs preserve both the useful detections and the stop-reporting controls.

The [pytest-selective case study](case-studies/pytest-selective.md) shows four reproduced bugs and why two snapshot
policies still belong inside one shared implementation.

## 7. Verify the actual installation

For model adopters, the scheduled audit also exports the full model inventory for source review. Fetch the
default-branch ref as well as the audited head (`fetch-depth: 0` in the template), because detection verifies
model allowances against that branch. When a reviewed model baseline exists, run `model-baseline --update`
before inventory export: detection refuses stale allowances that should already be retired. These working-tree
retirements are published only if the entire audit succeeds. Add only `.dry-lint/models.json` to the
ratchet's metadata paths. Automated audits must never accept models or generate dismissals. Retain the
model report as an artifact, including unresolved lower-ranked candidates. Run model export with
`if: ${{ !cancelled() }}` so a failed function sweep still leaves model review evidence; keep metadata
updates gated on overall success. `sweep` audits functions only;
its successful exit does not prove models were reviewed. Model cleanup uses source removal or an exact
reviewed dismissal, never an atomic negative score. Keep function README totals and model debt counts
separate, and rerun both inventories after consolidation to discover newly exposed opportunities.

After both ratchets succeed, run `dry-lint progress --readme README.md --repository OWNER/NAME` before staging
the metadata PR. This refreshes both inventories without judging again; the README links each baseline and
shows remaining, retired and dismissed pairs separately. A missing model baseline must read **Not initialized**,
never zero. Keep the configured model baseline path in the ratchet's allowed paths.

Verify the sticky and hook with a mixed change large enough to exceed the function display limit: model ownership
tasks must still be visible. Confirm a model opt-out says **not checked** and cannot resolve earlier model reviews.
Model review resolution must stay separate from confirmed duplicate prevention, and the combined cost must include
both passes. Check the light and dark README sign against both committed baselines, then refresh again to prove
idempotence. Retired baseline pairs are not a count of refactors; function judgments can also retire a pair.

For each model adoption, exercise unchanged accepted debt, a new or changed copy, retirement after removal,
the opt-out, and both sides of each ownership policy. Confirm model findings survive fork detect/judge and
appear in the combined sticky. Test schema naming/isolation separately if that optional policy is enabled.

A new audit workflow cannot be dispatched directly until GitHub knows it on the default branch. The audit
template also supports `workflow_call`: add this job to an already registered workflow with `workflow_dispatch`,
then dispatch that workflow on the adoption branch to exercise the same audit before merging:

```yaml
jobs:
  audit:
    if: github.event_name == 'workflow_dispatch'
    uses: ./.github/workflows/dry-lint-audit.yml
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      DRY_LINT_RATCHET_TOKEN: ${{ secrets.DRY_LINT_RATCHET_TOKEN }}
```

Pass only the declared secrets, using the adopter's judge credential if it uses a different preset. For an
audit-only manual run, add a boolean dispatch input and gate the audit and ordinary manual validation separately;
leave pull-request and push validation unchanged. Preserve the caller's existing jobs and permissions.
The caller must allow the audit's `contents: read` permission;
the ratchet token supplies the write access. The checkout and ratchet PR target the dispatched branch, so review
and incorporate that metadata into the adoption PR. If no registered workflow can call it yet, record the audit
as awaiting its first post-merge dispatch. Scheduled runs only start after the workflow reaches the default branch.

- Validate hook configuration and install both stages in a disposable checkout. Exercise staged detection and
  trailer handling; a no-source-change skip alone does not prove semantic judging.
- Run a strict baseline check on the adoption PR; retain the existing baseline's contract and history.
- Observe the PR sticky at the current head, its required judged check, and a title check. Inspect the active
  ruleset, not only the workflow YAML. For forks, verify the trusted judge path when a fork PR is available.
- Dispatch the candidate audit workflow. Verify artifact retention, credential access, complete judging and
  that the update either creates a normally checked ratchet PR or has no diff. A YAML parse alone is insufficient.
- Inspect the README light/dark sign, repository identity and committed counts. Confirm surrounding content
  survives regeneration. Check the post-merge default-branch run for ledger folding and counter publication.
- Record what was actually exercised and what remains merge-dependent. Do not claim a docs-only PR proved
  duplicate prevention, fork isolation, cleanup credit or merged-PR accounting.

## Applying the playbook again

Repeat the inventory before making changes. pytest-obligation already had a strict baseline and PR/fork workflows,
but lacked hooks and automated ratchet PRs. Its README had backlog counts without a repository counter sign.
That comparison adds four requirements to the Due recipe: preserve partial adoption, check inherited secrets and
rulesets, pass the numeric repository ID for a local README render, and protect main-push accounting from cancellation.
It also removes a second CLI install from the audit workflow so judgment and update use the same runtime.
pytest-selective additionally exercises the audit through a manual reusable-workflow call before first merge,
and keeps semantic credentials out of its general all-hooks quality job. Its real ratchet and unchanged rerun
verify both the metadata PR path and idempotence. These checks belong in the adoption recipe for future consumers.
Keep consumer-specific paths, parser versions, token names and CI selection rules in the consumer; keep this lifecycle
and the reusable workflow here.
