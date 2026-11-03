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
  - A clean pull request gets no comment.
  - When findings are fixed, the comment says so instead of going stale.
  - Copies left by two runs racing are deleted.
  - Once dry-lint's repository is public, the comment carries the banner. The action checks first, so it never
    shows a broken image.
- **The job summary**, with the same report.
- **Red for a reported duplicate**, unless overridden. The threshold is the `fail-at` input. See
  [When it fails](#when-it-fails-and-false-positives).

Without a judge (no `typesafe-api-key` and no `judge-command`), dry-lint lists look-alikes in the log. It adds no
annotations, no comment and no failure, so installing it before the secret exists costs nothing.

## When it fails, and false positives

Two thresholds decide what a finding does: `report_at` and `fail_at`, both in `[tool.dry-lint]`. The `fail-at`
action input (or `--fail-at` on the command line) overrides `fail_at` for one workflow.

| Judge score | Finding | Check |
| --- | --- | --- |
| below `report_at` (0.8) | not shown | green |
| `report_at` up to `fail_at` | warning annotation, listed in the comment | green |
| `fail_at` and above | error annotation, listed first as **blocking** | **red** |

By default `fail_at` is 0.8, the same as `report_at`, so **every reported duplicate fails the check**. On the gold
set (the shipped `reuse-v2` prompt) that is 75% precision and 59% recall. A quarter of red checks will be false
positives, which is what the overrides below are for.

To fail only on near-certain duplicates, set `fail-at: "0.91"`:

| `fail_at` | Precision | Recall | Red pull requests |
| --- | --- | --- | --- |
| 0.80 (default) | 75% | 59% | about 1 in 6 |
| 0.85 | 78% | 44% | |
| 0.88 | 90% | 32% | |
| 0.91 | 100% | 21% | about 1 in 20 |

At 0.91, the highest-scoring false positive was 0.892 and the lowest true duplicate above it was 0.910, so
nothing is lost against 0.90 and the margin is wider. Findings between 0.8 and 0.91 then only warn
([benchmark](benchmark.md)). `warn-only` never fails.

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
| `judge` | `auto` | `jev` when the key is set, otherwise `none`. Can be `jev`, `command`, `none` or an installed judge plugin. |
| `judge-command` | | For `judge: command`: reads the prompt on stdin, prints a JSON verdict ([judges](judges.md)). |
| `plugins` | | Extra packages to install, one per line. |
| `mode` | `auto` | See above. |
| `base` | the PR's base commit, or the previous push, or the default branch | What to compare with. |
| `working-directory` | `.` | The repository, or the package within a monorepo. |
| `comment` | `true` | Keep the sticky comment. |
| `check-run` | `true` | In judge mode, post a `dry-lint` check run on the pull request's head; `neutral` with findings, so it never blocks. |
| `sticky-key` | | One comment per key, when several dry-lint steps report on one pull request. |
| `fail-at` | `fail_at` from `[tool.dry-lint]` (0.8) | Judge score at or above which a duplicate fails the check; `0.91` fails only near-certain ones. |
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
