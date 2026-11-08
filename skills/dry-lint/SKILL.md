---
name: dry-lint
description: Set up and tune dry-lint, the pull-request check that flags new code re-implementing a concept the codebase already has. Use to adopt it in a repository end to end (settings, baseline, CI workflows, hooks, README), to choose the judge and thresholds (presets), to pay with API keys or a Claude or ChatGPT subscription, to set a cost budget, to declare deliberate copies, to silence false positives, or to measure a change with a gold set.
license: Apache-2.0
---

# Set up dry-lint in a repository

You are a coding agent adopting dry-lint in the repository you are working in. This file is the whole procedure.
Follow it in order and open one pull request. Links are for depth only; you should not need them.

dry-lint finds functions that re-implement something the codebase already has. A detector proposes look-alike pairs
without a model. A judge, running on the repository's own API key, decides whether each pair is one concept. The
result is a required `dry-lint` check, annotations and one sticky comment. Old duplicates are accepted once in
`.dry-lint/baseline.json`, which can only shrink.

**Ground rules**

- Work on a new branch and open a draft pull request. Follow the repository's AGENTS.md, CONTRIBUTING and pull
  request template; they win over this file on style.
- Never print, log or commit a secret. Refer to secrets by name only.
- Stop and tell the human, with the exact step, when something needs a secret or a repository setting. Do not change
  repository settings, rulesets or secrets yourself.
- If a command fails, report the exact command and its error. Do not work around a failure by editing
  `.dry-lint/baseline.json` by hand, raising thresholds, or adding broad ignores.

## 1. Preflight

Run these and note the answers. Every later step uses them.

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)                   # OWNER/NAME
gh repo view --json defaultBranchRef,visibility -q '"\(.defaultBranchRef.name) \(.visibility)"'
gh api "repos/$REPO" --jq .id                                                # numeric id, for the README sign
grep -rhE '^\s*-?\s*uses:' .github/workflows 2>/dev/null | sort | uniq -c    # how actions are pinned
ls AGENTS.md CLAUDE.md CONTRIBUTING.md .github/pull_request_template.md .github/PULL_REQUEST_TEMPLATE* \
   .pre-commit-config.yaml .dry-lint.toml .dry-lint/baseline.json 2>/dev/null
grep -n "tool.dry-lint" pyproject.toml 2>/dev/null; grep -rln "dry-lint" .github/workflows 2>/dev/null
gh secret list                                                               # repository secrets
gh api "repos/$REPO/actions/organization-secrets" --jq '.secrets[].name'     # organization secrets it can use
```

- **Default branch.** Use it wherever this file says `DEFAULT`. Do not assume `main`.
- **Pinning policy.** If the workflows pin actions to 40-character commit SHAs, pin every action you add the same
  way, with the tag as a comment: `gh api repos/gigaverse-app/dry-lint/commits/v1 --jq .sha` gives the SHA for
  `gigaverse-app/dry-lint@<sha> # v1`. Otherwise use the tags shown in this file.
- **Judge key.** The judge needs a TypeSafe API key (the Jev judge) and optionally an Anthropic key. The secret
  can have any name. Look for one in both secret lists (names like `TYPESAFE_API_KEY` or `TYPESAFE_AI_API_KEY`). Call
  its name `KEY_SECRET` below. A 403 from the organization endpoint means you cannot see those secrets, not that
  there are none; ask the human before concluding there is no key. If there is none, finish the steps that need no key and stop at step 10 with the
  request to add one. Check for a local key without printing it: `test -n "$TYPESAFE_AI_API_KEY" && echo set`.
- **Existing adoption.** If `.dry-lint/baseline.json` exists, you are resuming: never delete it or run
  `sweep --init` again. Keep existing hooks, settings and README markers, and fill in only what is missing.
- **Python syntax.** If the code uses syntax newer than Python 3.13, use that version for the parser below
  (`--python 3.14`, the Action's `python-version`, the hook's `language_version`).

## 2. Look at the repository, no key needed

```bash
uv tool install --no-config --python 3.13 'dry-lint>=1,<2'   # or: pipx install 'dry-lint>=1,<2'
dry-lint scan --judge none --limit 30
```

If the shell then says `dry-lint: command not found`, the tool folder is not on `PATH` yet: run
`export PATH="$(uv tool dir --bin):$PATH"` (or `uv tool update-shell` and a new shell) and try again.

Expected: a line `dry-lint: showing the 30 closest of N look-alike pairs; raise --limit to see more`, then pairs
like the following, then a summary line. Nothing is judged and nothing fails.

```text
src/dry_lint/judges/http.py:49: HttpJudge.judge looks like src/dry_lint/judges/jev.py::JevJudge.judge (candidate)
    similarity 0.98; pair 8b37533910fcfe44; if they are different concepts, add `# dry-lint: distinct-from ...`; ...
```

Note which folders the pairs come from. Tests, examples, vendored or generated code usually do not belong in scope.

## 3. Write the settings

Settings live in `.dry-lint.toml` at the repository root (top-level keys, `[budget]`, `[[patterns]]`). The same
keys work under `[tool.dry-lint]` in `pyproject.toml`; if both exist, `.dry-lint.toml` wins. Use `.dry-lint.toml`
unless the repository already configures dry-lint in `pyproject.toml`.

```toml
# .dry-lint.toml
preset = "jev"                    # see the table below; CI, the hook and the baseline all use this one preset
include = ["src/*"]               # the folders that ship: the package directories, not tests or docs
exclude = ["*/tests/*", "tests/*", "*/migrations/*", "*/scripts/*"]   # setting exclude replaces the defaults
[budget]
usd = 0.04                        # most judging one pull request may spend, across all its pushes
```

| Keys the repository has | `preset` | `--budget-usd` for the one-off sweep |
| --- | --- | --- |
| TypeSafe | `jev` (94% precision, 73% recall, about $0.0002 a pull request) | `1` (273 pairs cost $0.010) |
| TypeSafe and Anthropic | `jev+opus` (98% / 85%, about $0.005 a pull request) | `5` |
| Anthropic only | `sonnet` (97% / 63%) | `5` |
| Neither | stop at step 10 and ask for a TypeSafe key | |

**One preset everywhere.** The baseline records the preset's judges and thresholds, and any command that checks
against the baseline must use the same preset or it refuses to run. So the settings file names it, the workflows
take it from there (do not set the Action's `preset` input), and the hook passes it explicitly (step 7). If coding
agents write and fix most pull requests, `preset = "agent"` (Jev, failing from 0.6: more recall, more false
positives) is a valid choice; it is still the one preset for everything.

Check the scope:

```bash
dry-lint config
```

Expected, among other lines: `scope: include src/* - exclude ...` and `N source files in scope: src N`. If a folder
you did not mean appears, or a shipped one is missing, fix `include`/`exclude` and run it again.

## 4. Declare copies kept on purpose

Some repositories keep the same code in two places deliberately, for example a module that vendors a helper so it
can be copied on its own. Look for them: read the architecture docs and grep for words like `copied from`, `based on`,
`vendored`, `self-contained`. Each such pair is one concept, so `distinct-from` would be false. Declare it:

```toml
[[patterns]]
members = ["pkg/funcutils.py::_indent", "pkg/strutils.py::indent"]
reason = "funcutils vendors strutils.indent so it imports nothing (docs/architecture.rst)"
```

- A pair is in the pattern when **both** sides match: each side's `path::Qualified.name` (as `scan` prints it)
  is checked with fnmatch against `members`, which is one glob or a list of globs.
- Name the exact functions, or the narrowest glob that covers a whole vendored module
  (`pkg/urlutils.py::OrderedMultiDict.*` with `pkg/dictutils.py::OrderedMultiDict.*`). A broad glob such as `*::*`
  silences real duplicates too.
- Do not baseline these pairs instead. A baseline entry accepts the two functions exactly as they are today, so a
  later fix applied to both copies changes them and fails the check as new debt. A pattern keeps holding.
- Verify each pattern: `dry-lint explain pkg/funcutils.py::_indent pkg/strutils.py::indent` must print
  `rule: declared pattern: <reason>`. Run `explain` on a pair that must stay reported, too, and check it says
  `rule: none applies`.

## 5. Accept the existing backlog

This judges every candidate pair once and writes `.dry-lint/baseline.json`, `.dry-lint/progress.json` and a
progress block in the README (Markdown READMEs only; leave out `--readme` otherwise).

**With a local key** (`TYPESAFE_AI_API_KEY`, and `ANTHROPIC_API_KEY` for a Claude preset, in the environment):

```bash
dry-lint sweep --init --budget-usd 1 --readme README.md --repository OWNER/NAME --repository-id ID --branch DEFAULT
```

**Without a local key, in CI.** Fetch
[examples/dry-lint-bootstrap.yml](https://raw.githubusercontent.com/gigaverse-app/dry-lint/main/examples/dry-lint-bootstrap.yml)
into `.github/workflows/`, set its secret to `KEY_SECRET`, commit it together with `.dry-lint.toml`, and push. A push
that adds the file runs it on your branch; no default-branch registration is needed. Then:

```bash
gh run list --branch "$(git branch --show-current)" --json databaseId,name,status \
  --jq '.[] | select(.name == "dry-lint bootstrap")'
gh run watch RUN_ID --exit-status
OUT=$(mktemp -d) && gh run download RUN_ID --name dry-lint-baseline --dir "$OUT"
```

Copy `.dry-lint/` and `README.md` from `$OUT` into the repository, delete the bootstrap workflow, and commit.
Keep `sweep-report.json` out of Git; read it for the review below.

Expected, at the end of either route: `dry-lint: 0 pairs cleaned, N remaining, 0 dismissed; wrote .dry-lint/baseline.json`.

**Review the accepted pairs** before committing. Each is real debt someone will clean up later. If many come from
one deliberate copy, go back to step 4, add the pattern, delete the uncommitted `.dry-lint/` and run the sweep again.
That is allowed only while the baseline has never been merged. Do not refactor the pairs in this pull request.

The README block gets a `## Duplicate code` heading. Move or rename the heading to fit the README; later sweeps
only rewrite what is between the `dry-lint-progress` markers. dry-lint keeps each file's line endings.

## 6. Add the workflows

Fetch the examples, adapt them as listed, and save them in `.github/workflows/`:

| File | Purpose |
| --- | --- |
| [dry-lint.yml](https://raw.githubusercontent.com/gigaverse-app/dry-lint/main/examples/dry-lint.yml) | the `dry-lint` check on every pull request and default-branch push |
| [dry-lint-judge.yml](https://raw.githubusercontent.com/gigaverse-app/dry-lint/main/examples/dry-lint-judge.yml) | judges pull requests from forks with secrets, never running fork code (public repositories) |
| [dry-lint-audit.yml](https://raw.githubusercontent.com/gigaverse-app/dry-lint/main/examples/dry-lint-audit.yml) | weekly audit; opens a `dry-lint/ratchet` pull request when old debt is cleaned |

In each one:

1. Replace `secrets.TYPESAFE_AI_API_KEY` with `secrets.KEY_SECRET`. The Action input is always `typesafe-api-key`;
   a plain `run:` step passes the key as the environment variable `TYPESAFE_AI_API_KEY`, the only name the CLI reads.
   For a Claude preset, uncomment the `anthropic-api-key` lines too.
2. Replace `main` in `branches:` with `DEFAULT`.
3. In `dry-lint.yml`, uncomment `baseline: .dry-lint/baseline.json` and `require-complete: 'true'`. Keep its job
   `name:` expression: it names a fork's unjudged job `dry-lint detect`, so it can never satisfy a required
   `dry-lint` check.
4. Apply the pinning policy from step 1, and the parser version if it is not 3.13.
5. Keep the triggers, permissions and concurrency as they are: the comments explain why.

## 7. Add the hooks

If the repository uses pre-commit, merge this into `.pre-commit-config.yaml`, keeping every existing hook. If it does
not, add the file only when AGENTS.md or CONTRIBUTING welcomes new tooling; otherwise skip this step and say so in
the report.

```yaml
default_install_hook_types: [pre-commit, prepare-commit-msg]
default_stages: [pre-commit]       # other hooks must not also run at prepare-commit-msg
repos:
  - repo: https://github.com/gigaverse-app/dry-lint
    rev: v1
    hooks:
      - id: dry-lint
        args: [--preset, jev, --baseline, .dry-lint/baseline.json]   # the preset from .dry-lint.toml
      - id: dry-lint-trailers        # credits duplicates the hook kept out in the pull request's comment
```

- The hook defaults to the `agent` preset, so always pass the settings file's preset with the baseline.
- It reads `TYPESAFE_AI_API_KEY` from the shell or an untracked `.env`; add `.env` to `.gitignore`.
- `rev: v1` follows dry-lint's 1.x releases, but pre-commit caches the first install and warns that `v1` is a
  mutable reference. To pick up a newer 1.x release: `pre-commit clean && pre-commit install --install-hooks`.
  If the repository pins hooks to exact tags, use the latest `v1.x.y` tag and `pre-commit autoupdate` instead.
- Put the install command, `pre-commit install`, where contributors set up: CONTRIBUTING, or the README's
  development section if there is no CONTRIBUTING.

Check it: `uvx pre-commit validate-config` prints nothing and exits 0.

## 8. Open the pull request

Commit settings, baseline, progress file, README, workflows and hooks, following the repository's commit style.
Open a draft pull request that fills in the repository's template, or say what it adds, the accepted pairs with
their scores, the patterns with their reasons, and what you verified. Then:

```bash
gh pr checks --watch
```

Expected: a green `dry-lint` check and a sticky comment from dry-lint (with 0 changed functions it reports a clean
run). A red check on the adoption pull request means the key's secret is missing or misnamed, or the baseline and
settings disagree; read its log.

## 9. Prove it catches a copy

Pick a function of ten or more lines and copy it into a **different** file under a new name, renaming a few local
variables. Functions in the same file are never compared, so a same-file copy proves nothing.

```bash
git switch -c dry-lint-probe
# add the copy, then:
git add -A && git commit -m "test: dry-lint probe (do not merge)" && git push -u origin dry-lint-probe
gh pr create --draft --base ADOPTION_BRANCH --title "test: dry-lint probe (do not merge)" --body "Probe; will be closed."
gh pr checks --watch
```

Expected: the `dry-lint` check fails and the sticky comment names the pair with a judge score at or above the
preset's threshold. Then close it with `gh pr close --delete-branch`, switch back to the adoption branch and
delete the local probe branch.

The pair the comment names may be another existing copy rather than the function you copied, and the advice may be
to move callers to the new one: the judge picks the side it thinks should own the code, often the public one.

## 10. Stop for the human

Tell the human exactly what is left. These need repository admin rights or secrets, so you do not do them:

1. **Judge secret** (only if step 1 found none): add a repository or organization secret holding a TypeSafe API key
   ([TypeSafe](https://docs.typesafe.ai)) and tell you its name.
2. **Required check**: Settings, Rules, Rulesets, New branch ruleset; target the default branch; enable "Require
   status checks to pass"; add `dry-lint` with source GitHub Actions. Never add `dry-lint detect`. A workflow named
   `dry-lint` is not required until a rule says so.
3. **Ratchet token**: the audit opens its pull request with a secret `DRY_LINT_RATCHET_TOKEN`, a fine-grained token
   or GitHub App token with contents and pull-requests write on this repository. Until it exists, the audit fails
   visibly at its "Require ratchet PR authentication" step. That is expected, not a bug to fix.

## 11. Report

End with this report, in the pull request and to the human:

```text
dry-lint adoption: <PR URL>
Preset: <preset> (secret <KEY_SECRET>); scope: include <...>, <N> source files
Baseline: <N> accepted pairs (<route: local | CI run URL>, $<cost>)
Patterns: <each members list and reason>, each verified with dry-lint explain
Checks: adoption PR dry-lint <green/red>; probe PR <URL> red at <score> against <pair>, closed
Hooks: <added and validated | skipped because ...>
Left for you: <required check ruleset> <secret, if missing> <DRY_LINT_RATCHET_TOKEN>
Not verified: <anything you could not run, with the command and error>
```

## Optional, after the pull request

- **History replay** (needs a key; cheap with `jev`): `dry-lint bench --replay 50` shows which recent commits would
  have failed or warned, and what judging would have cost. Without a key, skip it and say so.
- **Audit before merge**: a new workflow cannot be dispatched until it is on the default branch, so the first audit
  runs after merge (`gh workflow run dry-lint-audit.yml`). With no cleanup it passes and opens no pull request.
- **Models**: model review is on by default. Leave `models.baseline` unset unless a human reviewed real model
  duplicates ([model adoption](https://dry-lint.readthedocs.io/en/latest/docs/model-adoption/)).

## Living with it

When a finding blocks, you are its final judge. Open both functions.

- **One concept:** delete the new copy and call the existing function, or extract a shared helper both use. Run the
  tests. If the finding says `drifted`, check which behavior callers need first.
- **Different concepts:** add `# dry-lint: distinct-from path::name` (`//` in TypeScript) inside the new function,
  with a comment saying how they differ.
- **One concept, two copies kept on purpose:** a `[[patterns]]` entry with a reason (step 4).
- **Generated code or a deliberate one-off:** `# dry-lint: ignore` in the function.
- **One pull request only:** the `dry-lint: override` label. It never waives widening the baseline.

To clean old debt: refactor a pair from the baseline, run the tests, then
`dry-lint sweep --update --budget-usd 1 --readme README.md --repository OWNER/NAME --branch DEFAULT`, and commit the
metadata with the refactor. Never edit the baseline by hand.

Thresholds come from measurements; change `fail_at` only after measuring on your own code
([judges and presets](https://dry-lint.readthedocs.io/en/latest/docs/judges/),
[benchmark](https://dry-lint.readthedocs.io/en/latest/docs/benchmark/)). The full manual path is the
[first-run tutorial](https://dry-lint.readthedocs.io/en/latest/docs/tutorials/first-run/); the CI design is in
[how CI runs dry-lint](https://dry-lint.readthedocs.io/en/latest/docs/ci/).
