# How CI runs dry-lint

Three workflows and one branch rule keep new duplicates out and record cleanup.
This page shows how they fit together. The [GitHub Action guide](github-action.md)
lists every input. A coding agent sets all of it up from one prompt, following the
[agent setup](../skills/dry-lint/SKILL.md); the [adoption playbook](adoption-playbook.md)
covers auditing an existing adoption.

```text
pull request (this repo) ──► dry-lint.yml ── detect + judge + comment ──► check "dry-lint"  ◄── required
pull request (fork)      ──► dry-lint.yml ── detect only, no secrets ──► check "dry-lint detect" (never required)
                                   │ uploads candidates
                                   ▼
                         dry-lint-judge.yml (workflow_run, default branch, secrets)
                                   └─ judges the artifact, never runs fork code ──► check "dry-lint"
push to default branch   ──► dry-lint.yml ── judges merged code, saves the verdict cache, folds the ledger
weekly / manual          ──► dry-lint-audit.yml ── full sweep ──► dry-lint/ratchet PR: baseline, progress, README only
                                   └─ new blocking pair? the audit fails, no ratchet PR
```

## 1. The required check: `dry-lint.yml`

Start from [examples/dry-lint.yml](../examples/dry-lint.yml). On a pull request from the
same repository it finds the changed functions, judges their look-alikes, annotates the
diff and keeps one sticky comment up to date ([what a pull request gets](github-action.md#what-a-pull-request-gets)).

Once the backlog is accepted ([first run, step 3](tutorials/first-run.md#3-accept-the-existing-backlog-once)),
pass it to the Action:

```yaml
- uses: gigaverse-app/dry-lint@v1
  with:
    typesafe-api-key: ${{ secrets.TYPESAFE_AI_API_KEY }}   # your secret's name
    baseline: .dry-lint/baseline.json
    require-complete: 'true'
```

The preset comes from `.dry-lint.toml`, the same one the baseline was written with
([one preset everywhere](judges.md#one-preset-everywhere)). Replace `main` in the
example's `push: branches:` with your default branch
(`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`).

What the check enforces:

| Situation | Check |
| --- | --- |
| No new duplicate at the preset's threshold | green |
| A new blocking duplicate | **red** until the author reuses the existing function or adds `distinct-from` |
| The pull request widens `.dry-lint/baseline.json` | **red**; the `dry-lint: override` label cannot waive it |
| The judge failed or its key is missing | **red**; strict checking never passes unjudged |
| The per-pull-request budget ran out | the unjudged pairs show as warnings, not failures |

Keep the `push` trigger on the default branch: that run judges merged code, saves the
verdict cache every pull request restores, and folds merged pull requests into the
repository's ledger. The example's concurrency settings cancel superseded pull request
runs but never a default-branch run.

## 2. Pull requests from forks: `dry-lint-judge.yml`

GitHub gives a fork's pull request no secrets, so its run only proposes candidates. The
example's job `name:` expression calls that run `dry-lint detect`:

```yaml
name: >-
  ${{ github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name
  != github.event.pull_request.base.repo.full_name
  && 'dry-lint detect' || 'dry-lint' }}
```
 Add [examples/dry-lint-judge.yml](../examples/dry-lint-judge.yml):
it runs after `dry-lint` from the default branch, with secrets, judges the uploaded
candidates and posts the `dry-lint` check. It never checks out or runs the fork's code,
and it comments only if the candidates belong to the pull request's current head
([modes and forks](github-action.md#modes-and-pull-requests-from-forks)).

Give both workflows the same judge, baseline and strict inputs.

## 3. Make it required

In the repository's ruleset (or branch protection), require the status check **`dry-lint`**
from GitHub Actions: Settings, Rules, Rulesets, New branch ruleset; target the default branch;
enable "Require status checks to pass"; add `dry-lint` with source GitHub Actions. This is a
repository setting, so a coding agent setting dry-lint up leaves it to a person. Do not require `dry-lint detect`: a fork's detection-only job must
never satisfy the gate. A workflow named `dry-lint` is not required until a rule says so;
check rulesets as well as classic branch protection.

## 4. Record cleanup: `dry-lint-audit.yml`

Add [examples/dry-lint-audit.yml](../examples/dry-lint-audit.yml). Every week, or when
dispatched after a cleanup merges, it sweeps the whole repository against the accepted
backlog:

- Pairs that were refactored away, or are now judged separate, are recorded as cleaned.
- It opens or updates one `dry-lint/ratchet` pull request that changes only
  `.dry-lint/baseline.json`, `.dry-lint/progress.json`, `.dry-lint/models.json` and the README block.
- That pull request runs ordinary CI, including the required check that refuses any widening.
- A newly found blocking pair fails the audit, and no ratchet pull request is opened.
- It never edits application code and never merges its own pull request.

Give it the same judge inputs as your check. A pull request created with the default
`GITHUB_TOKEN` does not trigger other workflows, so the ratchet needs its own token,
`DRY_LINT_RATCHET_TOKEN`, with contents and pull-request write access. Creating it is a
person's job. Until it exists, the audit still runs and fails visibly at its
"Require ratchet PR authentication" step
([playbook, step 6](adoption-playbook.md#6-close-the-weekly-ratchet-loop)).

## Secrets

Store each key as a repository or organization secret. The names are yours; the examples
use the ones below. Check what exists first: `gh secret list` shows repository secrets, and
`gh api repos/OWNER/NAME/actions/organization-secrets --jq '.secrets[].name'` the organization
secrets this repository can use.

| Secret in the examples | Passed as | Used by | Notes |
| --- | --- | --- | --- |
| `TYPESAFE_AI_API_KEY` | `typesafe-api-key:`, or env `TYPESAFE_AI_API_KEY` in a `run:` step | all workflows | The Jev judge: presets `jev`, `agent`, and the first judge of `jev+opus`. |
| `ANTHROPIC_API_KEY` | `anthropic-api-key:`, or env `ANTHROPIC_API_KEY` | all, for a Claude preset | `jev+opus` with a TypeSafe key, or `sonnet` on its own ([judges](judges.md)) |
| `DRY_LINT_RATCHET_TOKEN` | `token:` of the ratchet step | the audit | Contents and pull-request write, so the ratchet pull request runs CI |

Use the same preset everywhere: the baseline records the detection and judging setup it
was written with, and changing it later is an explicitly reviewed migration
([sweeps](sweeps.md#review-the-audit-and-clean-up-deliberately)).

dry-lint never provides keys or runs a judge for you. Without a judge key it only lists
look-alikes and never fails. With `require-complete`, a missing key fails the check
instead, so a misconfigured secret cannot pass silently.

## No judge key on your machine

`sweep --init` judges every candidate pair once, so it needs the key, and coding agents
rarely have one locally. Run it in Actions instead with
[examples/dry-lint-bootstrap.yml](../examples/dry-lint-bootstrap.yml):

1. Commit it to `.github/workflows/` with `.dry-lint.toml`, using your secret's name, and push.
   The push that adds the file runs it on that branch; unlike `workflow_dispatch`, a push
   needs no copy of the workflow on the default branch.
2. `gh run list --workflow dry-lint-bootstrap.yml --branch BRANCH --limit 1`, then
   `gh run download RUN_ID --name dry-lint-baseline --dir OUT`.
3. Copy `.dry-lint/` and `README.md` from `OUT`, delete the bootstrap workflow, review the
   accepted pairs and commit.

The workflow has read-only permissions; nothing reaches the repository except the commit you
make. Budget it for the judge: `--budget-usd 1` is ample for Jev (273 pairs cost $0.010),
`5` for a Claude preset.

## Check the installation

After merging, confirm it end to end:

1. Open a test pull request that adds a near-copy of an existing function **in a different
   file** (functions in the same file are never compared): the required `dry-lint` check
   fails and the sticky names the pair.
2. Dispatch the audit workflow once: with no cleanup, it passes and opens no pull request.
3. Confirm the ruleset lists `dry-lint`, not `dry-lint detect`.

The playbook's [verification step](adoption-playbook.md#7-verify-the-actual-installation)
covers hooks and model duplication too.
