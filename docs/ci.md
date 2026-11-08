# How CI runs dry-lint

Three workflows and one branch rule keep new duplicates out and record cleanup.
This page shows how they fit together. The [GitHub Action guide](github-action.md)
lists every input, and the [adoption playbook](adoption-playbook.md) is the full
checklist for an existing repository.

```text
pull request (this repo) ──► dry-lint.yml ── detect + judge + comment ──► check "dry-lint"  ◄── required
pull request (fork)      ──► dry-lint.yml ── detect only, no secrets ──► check "dry-lint detect" (never required)
                                   │ uploads candidates
                                   ▼
                         dry-lint-judge.yml (workflow_run, default branch, secrets)
                                   └─ judges the artifact, never runs fork code ──► check "dry-lint"
push to main             ──► dry-lint.yml ── judges merged code, saves the verdict cache, folds the ledger
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
    preset: agent
    typesafe-api-key: ${{ secrets.TYPESAFE_AI_API_KEY }}
    baseline: .dry-lint/baseline.json
    require-complete: 'true'
    comment: 'true'
```

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

GitHub gives a fork's pull request no secrets, so its run only proposes candidates and
names itself `dry-lint detect`. Add [examples/dry-lint-judge.yml](../examples/dry-lint-judge.yml):
it runs after `dry-lint` from the default branch, with secrets, judges the uploaded
candidates and posts the `dry-lint` check. It never checks out or runs the fork's code,
and it comments only if the candidates belong to the pull request's current head
([modes and forks](github-action.md#modes-and-pull-requests-from-forks)).

Give both workflows the same judge, baseline and strict inputs.

## 3. Make it required

In the repository's ruleset (or branch protection), require the status check **`dry-lint`**
from GitHub Actions. Do not require `dry-lint detect`: a fork's detection-only job must
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

The example passes Anthropic inputs; give it the same judge inputs as your check.
A pull request created with the default `GITHUB_TOKEN` does not trigger other workflows,
so the ratchet needs its own token with contents and pull-request write access
([playbook, step 6](adoption-playbook.md#6-close-the-weekly-ratchet-loop)).

## Secrets

| Secret | Used by | Notes |
| --- | --- | --- |
| `TYPESAFE_AI_API_KEY` | all three workflows | The Jev judge. With it alone, dry-lint picks the `jev` preset; set `preset: agent` for recall-first judging of agent-written code. |
| `ANTHROPIC_API_KEY` | all three, if you choose a Claude preset | `jev+opus` with a TypeSafe key, or `sonnet` on its own ([judges](judges.md)) |
| `DRY_LINT_RATCHET_TOKEN` | the audit | Contents and pull-request write, so the ratchet pull request runs CI |

Use the same preset everywhere: the baseline records the detection and judging setup it
was written with, and changing it later is an explicitly reviewed migration
([sweeps](sweeps.md#review-the-audit-and-clean-up-deliberately)).

dry-lint never provides keys or runs a judge for you. Without a judge key it only lists
look-alikes and never fails. With `require-complete`, a missing key fails the check
instead, so a misconfigured secret cannot pass silently.

## Check the installation

After merging, confirm it end to end:

1. Open a test pull request that adds a near-copy of an existing function: the required
   `dry-lint` check fails and the sticky names the pair.
2. Dispatch the audit workflow once: with no cleanup, it passes and opens no pull request.
3. Confirm the ruleset lists `dry-lint`, not `dry-lint detect`.

The playbook's [verification step](adoption-playbook.md#7-verify-the-actual-installation)
covers hooks and model duplication too.
