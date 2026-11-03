# GitHub Action

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
  with:
    fetch-depth: 0
- uses: gigaverse-app/dry-lint@main
  with:
    typesafe-api-key: ${{ secrets.TYPESAFE_AI_API_KEY }}
```

That is the whole setup for a repository whose pull requests come from its own branches. Copy
[examples/dry-lint.yml](../examples/dry-lint.yml). If you also accept pull requests from forks, add
[examples/dry-lint-judge.yml](../examples/dry-lint-judge.yml).

## What a pull request gets

- **Annotations** on the changed functions that re-implement existing code, with the function they duplicate
  and what to do about it.
- **One sticky comment**, found again by its `<!-- dry-lint -->` marker and edited in place on every push:
  - A headline and badges say how many duplicated concepts there are, how many block and how many have drifted;
    a blocking, advisory or overridden status follows as a GitHub alert.
  - One row per pair: a severity dot, the concept, both copies linked at the analyzed commit (short file names,
    the full path on hover, GitHub Enterprise included) and the verdict with the judge's fix.
  - Fold-outs hold each judge reason with a copy-paste `distinct-from` line, and every scope of override.
  - A `dry-lint scan` report reads as an audit of existing code that never blocks, not as a pull request review.
  - A clean pull request gets a green report of what was checked: changed functions, how many they were
    compared with, look-alike pairs, what the judge cleared and the closest call. Opt out with
    `comment-on-clean: "false"`.
  - When findings are fixed, the comment says so instead of going stale.
  - Copies left by two runs racing are deleted.
  - Once dry-lint's repository is public, the comment carries the banner. The action checks first, so it never
    shows a broken image.
- **The job summary**, with the same report.
- **Red for a reported duplicate**, unless overridden. The threshold is the `fail-at` input. See
  [When it fails](#when-it-fails-and-false-positives).

Without a judge (no `typesafe-api-key` and no `judge-command`), dry-lint lists look-alikes in the log. It adds no
annotations, no comment and no failure, so installing it before the secret exists costs nothing.

### Preview without posting

[Open the illustrative report](comment-preview.md), or render it locally without a token or model:

```bash
uv run dry-lint report --from examples/comment-report.json --format markdown --warn-only
```

The fixture contains illustrative verdicts, not measured findings. To preview your own run, substitute its
`report.json`. `report` renders saved results and never posts a comment. Local reports without repository/commit
metadata show full qualified names instead of source links.

## When it fails, and false positives

Two thresholds decide what a finding does: `report_at` and `fail_at`, both in `[tool.dry-lint]`. The `fail-at`
action input (or `--fail-at` on the command line) overrides `fail_at` for one workflow.

| Judge score | Finding | Check |
| --- | --- | --- |
| below `report_at` (0.8) | not shown | green |
| `report_at` up to `fail_at` | warning annotation, listed in the comment | green |
| `fail_at` and above | error annotation, listed first as **blocking** | **red** |

The thresholds come from the judging preset, which the keys you pass choose ([judges](judges.md)):

| Keys passed | Preset | Fails at | Precision / recall | Red pull requests |
| --- | --- | --- | --- | --- |
| `typesafe-api-key` + `anthropic-api-key` | `jev+sonnet` | 0.7 (warns from 0.6) | 97% / 84% | |
| `typesafe-api-key` only | `jev` | 0.8 | 94% / 73% | 15% of 600 |

A red check is a real duplicate about 33 times in 34 with `jev+sonnet`, 17 in 18 with `jev`; the overrides below
handle the rest. To fail only on near-certain duplicates, raise `fail-at` (with `jev`, 0.9 is 100% precise and
45% recall); findings between `report_at` and `fail-at` then only warn ([benchmark](benchmark.md)). `warn-only`
never fails.

**When dry-lint is wrong**, record the decision where it belongs:

| Scope | How | Where it lives |
| --- | --- | --- |
| this pair | `# dry-lint: distinct-from src/text.py::shorten_text` in the new function | next to the code it explains |
| this function | `# dry-lint: ignore` in the function | next to the code |
| a family of deliberate look-alikes | a `patterns` entry (`members`, `reason`) in `[tool.dry-lint]` | configuration, reviewed |
| whole paths | `exclude` in `[tool.dry-lint]` | configuration, reviewed |
| this pull request only | the `dry-lint: override` label | the pull request; the comment says it was overridden |

The code and configuration routes are permanent and reviewed like any change: the pair is never proposed again.
The label is for an urgent merge or a call you don't want to write down. It lets blocking findings through for this
pull request only, and the comment records that it did. Adding or removing the label re-runs dry-lint (the example
workflow listens for `labeled` and `unlabeled`), and the verdicts come from the cache, so that re-run costs no
judge calls.

## Modes, and pull requests from forks

GitHub gives a pull request from a fork no secrets and a read-only token, so it cannot be judged or commented on
in its own run. The default `mode: auto` handles each case:

| Event | Mode | What runs |
| --- | --- | --- |
| `pull_request` from the same repository | `single` | detect, judge, annotate, comment |
| `pull_request` from a fork | `detect` | propose candidates, upload them as the `dry-lint-candidates` artifact |
| `workflow_run` after the above | `judge` | download the candidates, judge, comment, post a check run |
| `push` | `single` | judge what the push changed; no comment |

The judge job runs from the default branch, with secrets. It treats the fork's candidates as untrusted data:
- it never checks out or runs the fork's code;
- it installs only the `plugins` named in the workflow;
- it comments only if the artifact's commit is the triggering run's head commit, and that commit is still the
  pull request's head.

## Inputs

| Input | Default | |
| --- | --- | --- |
| `typesafe-api-key` | | Enables the Jev judge. |
| `anthropic-api-key` | | Enables escalation: Claude Sonnet re-judges first-judge scores in the escalation band, for about one call every three PRs ([judges](judges.md)). Empty: no escalation. |
| `claude-code-oauth-token` | | A Claude subscription token (`claude setup-token`): the `claude-code` judge runs on the subscription. The `claude` CLI is installed only when this is set. |
| `claude-code-version` | `2.1.311` | The `@anthropic-ai/claude-code` version installed for it. |
| `preset` | | Judging preset; `dry-lint config` lists them. Empty: dry-lint picks one from the keys it has (jev+sonnet, jev+claude-code, jev, ...). |
| `budget-usd` | | Spending cap per run for paid judges; pairs past it are left unjudged and say so. |
| `judge` | `auto` | `auto` leaves the choice to the preset. An explicit `jev`, `command`, `none` or installed plugin replaces it (preset `custom`). |
| `judge-command` | | For `judge: command`: reads the prompt on stdin, prints a JSON verdict ([judges](judges.md)). |
| `plugins` | | Extra packages to install, one per line. |
| `mode` | `auto` | See above. |
| `base` | the PR's base commit, or the previous push, or the default branch | What to compare with. |
| `working-directory` | `.` | The repository, or the package within a monorepo. |
| `repositories` | | One `OWNER/NAME=PATH` per line, including the primary checkout. Enables changed-function checks against committed peers in `single`/`detect` mode. Checkout and credentials remain the workflow's responsibility. See [workspaces](workspaces.md). |
| `comment` | `true` | Keep the sticky comment. |
| `comment-on-clean` | `true` | Comment on a clean pull request too; `false` comments only once there are findings. |
| `check-run` | `true` | In judge mode, post a `dry-lint` check run on the pull request's head; `neutral` with findings, so it never blocks. |
| `sticky-key` | | One comment per key, when several dry-lint steps report on one pull request. |
| `fail-at` | the preset's (0.7 with `jev+sonnet`, 0.8 with `jev`) | Judge score at or above which a duplicate fails the check. |
| `warn-only` | `false` | Never fail; blocking findings are reported like the rest. |
| `override-label` | `dry-lint: override` | The pull request label that lets blocking findings through. |
| `github-token` | `github.token` | Needs `pull-requests: write`; in judge mode also `actions: read` and `checks: write`. |

The outputs are `mode`, `findings` (how many duplicates were reported), `blocking` (how many reached `fail_at`),
`overridden` and `exit-code`: 0 for nothing blocking, 1 for blocking findings, 2 when dry-lint could not run. Exit
code 2 always fails the step, so a broken setup is never silent.

Thresholds and exclusions live in `[tool.dry-lint]` in `pyproject.toml`, so that the action, the pre-commit hook
and the command line all agree ([README](../README.md#settings)).

## Verdict cache

Verdicts are kept in the Actions cache:
- Caches are partitioned by job and `sticky-key`, so concurrent local and cross-repository jobs do not race to
  save different verdict sets under the same key. Use a distinct `sticky-key` for multiple steps in one job.
- A pull request's run restores the newest verdicts it can see, so a later push only judges pairs whose logic
  changed.
- Runs on the default branch, that is pushes to `main` and judge-mode runs, save their verdicts where every pull
  request can read them.

Losing the cache only costs re-judging.

## Running it in a monorepo, or more than once

Use one step per package, each with its own `working-directory` and `sticky-key`:

```yaml
- uses: gigaverse-app/dry-lint@main
  with: { working-directory: services/api, sticky-key: api, typesafe-api-key: "${{ secrets.TYPESAFE_AI_API_KEY }}" }
- uses: gigaverse-app/dry-lint@main
  with: { working-directory: services/web, sticky-key: web, typesafe-api-key: "${{ secrets.TYPESAFE_AI_API_KEY }}" }
```
