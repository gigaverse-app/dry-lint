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

- Work on a new branch and open a draft pull request right after its first push (step 5's CI route, else step 8).
  Follow the repository's AGENTS.md, CONTRIBUTING and pull request template; they win over this file on style. Fill
  in every field of the template; for one that does not apply to a tooling change (an issue link, a changelog entry,
  a test plan for code), write `N/A:` and the reason rather than deleting it.
- Never print, log or commit a secret. Refer to secrets by name only.
- Stop and tell the human, with the exact step, when something needs a secret or a repository setting. Do not change
  repository settings, rulesets or secrets yourself.
- If a command fails, report the exact command and its error. Do not work around a failure by editing
  `.dry-lint/baseline.json` by hand, raising thresholds, or adding broad ignores.

## 1. Preflight

Run these and note the answers. Every later step uses them.

```bash
REPO=OWNER/NAME     # the repository you will open the pull request in: check `git remote -v`; in a fork, the fork
gh repo view "$REPO" --json defaultBranchRef,visibility -q '"\(.defaultBranchRef.name) \(.visibility)"'
grep -rhE '^\s*-?\s*uses:' .github/workflows 2>/dev/null | sort | uniq -c    # how actions are pinned
ls AGENTS.md CLAUDE.md README* .pre-commit-config.yaml .dry-lint.toml .dry-lint/config.toml .dry-lint/baseline.json 2>/dev/null
git ls-files | grep -iE 'contributing|pull_request_template'                 # in any folder (.github/, docs/) or case
grep -n "rev:" .pre-commit-config.yaml 2>/dev/null                           # how hooks are pinned
grep -n "tool.dry-lint" pyproject.toml 2>/dev/null; grep -rln "dry-lint" .github/workflows 2>/dev/null
gh secret list --repo "$REPO"                                                # repository secrets
gh api "repos/$REPO/actions/organization-secrets" --jq '.secrets[].name'     # organization secrets it can use
```

Name the repository in every `gh` command in this file: `--repo "$REPO"` for `gh pr`, `gh run`, `gh secret` and
`gh workflow`, the positional argument for `gh repo view "$REPO"`, and the path for `gh api repos/$REPO/...`. In a
clone of a fork, `gh` otherwise picks the upstream repository, and runs, secrets and pull requests silently go to
the wrong place.

- **Default branch.** Use it wherever this file says `DEFAULT`. Do not assume `main`.
- **One version of dry-lint.** Everything you add uses dry-lint 1.x: the CLI as `'dry-lint[anthropic]>=1,<2'` (here and in
  the bootstrap workflow), the Action as `gigaverse-app/dry-lint@v1`, the hook as `rev: v1`, and the example
  workflows from the `v1` tag (the links below), so the examples match the CLI you installed. If the hooks
  already in `.pre-commit-config.yaml` pin exact tags (`rev: v4.6.0`, not `rev: v4`), pin dry-lint's hook the
  same way, to its latest release:
  `gh release view --repo gigaverse-app/dry-lint --json tagName -q .tagName` (for example `rev: v1.8.1`).
- **Pinning policy.** The repository's workflows decide, whatever this file's examples show:
  - For an action the repository already uses, copy its existing reference exactly, tag or SHA. If it uses
    `actions/setup-python@v6` and an example says `@v7`, write `@v6`.
  - If the workflows pin actions to 40-character commit SHAs, pin every other action you add the same way, with the
    tag as a comment (`uses: OWNER/REPO@<sha> # TAG`). Resolve the tag to its commit with
    `gh api repos/OWNER/REPO/commits/TAG --jq .sha` (for example `repos/gigaverse-app/dry-lint/commits/v1`); this
    works for annotated tags too, where `git/ref/tags/TAG` returns the tag object rather than the commit.
  - Otherwise use the tags shown in this file.
- **Judge key.** Use `ANTHROPIC_API_KEY` for balanced function review. Find its actual secret name in the repository
  and organization secret lists; call it `KEY_SECRET` below. Never print its value. A 403 listing org secrets does
  not prove no key exists. Finish work that needs no key before asking for missing credentials.
- **Existing adoption.** If `.dry-lint/baseline.json` exists, you are resuming: never delete it or run
  `sweep --init` again. Preserve debt and README markers. Migrate legacy function presets to balanced with `baseline-migrate`, remove hook preset overrides, and document any compelling exception. Never reinitialize debt.
- **Python syntax.** If the code uses syntax newer than Python 3.13, use that version for the parser below
  (`--python 3.14`, the Action's `python-version`, the hook's `language_version`).

## 2. Look at the repository, no key needed

```bash
uv tool install --upgrade --no-config --python 3.13 'dry-lint[anthropic]>=1,<2'   # or: pipx install --force 'dry-lint[anthropic]>=1,<2'
dry-lint --version                 # expected: dry-lint 1.8.1 or later
dry-lint config                    # the scope: which folders' source files it reads
dry-lint scan --judge none --limit 30
```

`--upgrade` matters: without it, an older dry-lint already on the machine stays in place ("already installed").
If the shell then says `dry-lint: command not found`, the tool folder is not on `PATH` yet: run
`export PATH="$(uv tool dir --bin):$PATH"` (or `uv tool update-shell` and a new shell) and try again.

Expected: pairs like the following, then a summary line `dry-lint: N candidate pair(s), ...` and
`judging: no judge · look-alikes are listed; nothing is judged, reported or failed`. When there are more than 30
pairs, a first line `dry-lint: showing the 30 closest of N look-alike pairs; raise --limit to see more` says so;
with 30 or fewer it is absent. Nothing is judged and nothing fails.

```text
src/dry_lint/judges/http.py:49: HttpJudge.judge looks like src/dry_lint/judges/jev.py::JevJudge.judge (candidate)
    similarity 0.98; pair 8b37533910fcfe44; if they are different concepts, add this pair as a distinct entry with a reason in .dry-lint/ignore.yaml; ...
```

Read `config`'s `N source files in scope: <folder> <count>, ...` line before the pairs: by default everything
tracked is in scope except tests, migrations and scripts, so folders such as `misc/`, `docs/` (a Sphinx `conf.py`) or
`examples/` show up there first. Note which folders the pairs come from, too. Tests, examples, docs, vendored or
generated code usually do not belong in scope; step 3 narrows it.

## 3. Write the settings

Settings live in `.dry-lint/config.toml` at the repository root (top-level keys, `[budget]`, `[[patterns]]`). The same
keys work under `[tool.dry-lint]` in `pyproject.toml`; if both exist, `.dry-lint/config.toml` wins. Use `.dry-lint/config.toml`
unless the repository already configures dry-lint in `pyproject.toml`. Legacy `.dry-lint.toml` is readable;
move it to `.dry-lint/config.toml` without changing its contents. Both dedicated locations together are an error.
Keep the whole `.dry-lint/` directory committed. Settings are global; do not create subdirectory overrides.
For reviewed pair exceptions, use only `.dry-lint/ignore.yaml`, never `.dry-lint-ignore.toml`.
Preserve entry order and comments. Edit only the relevant entry, put each target on its own line,
and use folded multiline reasons for longer explanations. Do not sort or rewrite the whole ignore file.

```toml
# .dry-lint/config.toml
# Recommended function policy. CI, the hook and the baseline all use it; models require agent review.
preset = "balanced"
# The folders that ship: the package directories, not tests or docs.
include = ["src/*"]
# The defaults, restated: setting exclude replaces them, so keep them in the list.
exclude = ["*/tests/*", "tests/*", "*/migrations/*", "*/scripts/*"]
[budget]
# The most judging one pull request may spend, across all its pushes.
usd = 0.04
```

To leave out a folder inside an included one, such as vendored or generated code, add it to `exclude` after the
defaults: `exclude = ["*/tests/*", "tests/*", "*/migrations/*", "*/scripts/*", "src/pkg/_vendor/*"]`. Patterns are
fnmatch over the repository-relative path, and `*` also matches `/`, so `src/pkg/_vendor/*` covers every file below
it. Exclude wins over include. Without the four defaults the list would bring tests, migrations and scripts back
into scope.

Use balanced for functions and agent source review for models. An Anthropic key selects balanced automatically,
but pin it in repository settings so a missing key cannot quietly downgrade enforcement. A Claude subscription may
use `balanced-subscription`; TypeSafe-only function judging requires a documented exception. Do not equate the legacy
function preset named `agent` with the separate model review lane.

**One policy everywhere.** CI, hooks, audits and the baseline inherit repository settings. Remove hook `--preset`
arguments and leave the Action preset input unset. For existing debt, run `dry-lint baseline-migrate` after changing
settings; verify it preserves every pair, hash and settled state. Then check with `--require-complete`. Migration
accepts no new debt and earns no cleanup credit. See [the policy](https://github.com/gigaverse-app/dry-lint/blob/main/docs/judges.md).

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
- Name the exact functions, or the narrowest glob that covers a whole vendored class
  (`pkg/urlutils.py::OrderedMultiDict.*` with `pkg/dictutils.py::OrderedMultiDict.*`). A broad glob such as `*::*`
  silences real duplicates too.
- A method is named after the class that defines it, so `Class.*` does not cover a subclass that overrides the same
  methods: `FastIterOrderedMultiDict.__init__` is not `OrderedMultiDict.*`. If `scan` still pairs the copy with a
  subclass, widen that side to `*OrderedMultiDict.*`, then `explain` one subclass pair as well.
- Do not baseline these pairs instead. A baseline entry accepts the two functions exactly as they are today, so a
  later fix applied to both copies changes them and fails the check as new debt. A pattern keeps holding.
- Verify each pattern: `dry-lint explain pkg/funcutils.py::_indent pkg/strutils.py::indent` must print
  `rule: declared pattern: <reason>`. Run `explain` on a pair that must stay reported, too, and check it says
  `rule: none applies`.

## 5. Accept the existing backlog

This judges every candidate pair once and writes `.dry-lint/baseline.json`, `.dry-lint/progress.json` and, for a
Markdown `README.md`, a progress block in it. `progress.json` is the shields.io endpoint behind the backlog badge;
commit it in every case, since the weekly audit keeps it current. A README in another format (`README.rst`) gets no
block, and you leave it alone.

**With a local key** (`ANTHROPIC_API_KEY` in the environment):

```bash
ID=$(gh api "repos/$REPO" --jq .id)   # the README's counter sign is keyed by a hash of this id, never the name
dry-lint sweep --init --budget-usd 5 --readme README.md --repository "$REPO" --repository-id "$ID" --branch DEFAULT
```

Without a Markdown `README.md`, leave out `--readme README.md` and `--repository-id "$ID"`: the id serves only the
README block.

**Without a local key, in CI.** Fetch
[examples/dry-lint-bootstrap.yml](https://raw.githubusercontent.com/gigaverse-app/dry-lint/v1/examples/dry-lint-bootstrap.yml)
into `.github/workflows/`, set its secret to `KEY_SECRET`, apply the pinning policy, commit it together with
`.dry-lint/config.toml`, and push. It runs on every push that changes either file, on your branch; no default-branch
registration is needed. It passes the repository id itself and writes the README block only when there is a
`README.md`. This is the first push: open the draft pull request now (the body can say "work in progress"):

```bash
gh pr create --repo "$REPO" --draft --base DEFAULT --head "$(git branch --show-current)" --title "..." --body "..."
```

Then:

```bash
BRANCH=$(git branch --show-current)
gh run list --repo "$REPO" --branch "$BRANCH" --json databaseId,name,status,headSha \
  --jq '.[] | select(.name == "dry-lint bootstrap")'          # take the run for your latest commit
gh run watch RUN_ID --repo "$REPO" --exit-status
OUT=$(mktemp -d) && gh run download RUN_ID --repo "$REPO" --name dry-lint-baseline --dir "$OUT"
```

Copy `.dry-lint/`, and `README.md` if the artifact has one, from `$OUT` into the repository. Keep
`sweep-report.json` out of Git; read it for the review below. To run it again, for example after adding a pattern,
do not commit the downloaded files yet: commit and push the `.dry-lint/config.toml` change and the push starts a new run.
Once the baseline is right, delete the bootstrap workflow and commit it together with the files.

Expected, at the end of either route: `dry-lint: 0 pairs cleaned, N remaining, 0 dismissed; wrote .dry-lint/baseline.json`.

**Review the accepted pairs** before committing. Each is real debt someone will clean up later. If many come from
one deliberate copy, go back to step 4, add the pattern, remove only the uncommitted generated
`baseline.json`, `progress.json` and `models.json` under `.dry-lint/`, then run the sweep again.
Preserve `config.toml`, `ignore.yaml` and `feedback.json`; never delete the whole directory.
That is allowed only while the baseline has never been merged. Do not refactor the pairs in this pull request.

The sweep judges more pairs than `scan` listed: `scan` shows only pairs that are each other's closest look-alike,
while a sweep asks about every function's three closest (the `neighbours` setting), so expect a larger count.

**Judge scores vary slightly.** Two identical runs can differ by about 0.01, so a pair within a few hundredths of the
preset's threshold can be reported in one run and not the next. Do not chase it: never change thresholds to settle
one pair, and do not re-run the sweep hoping for a different answer. Decide such a pair on its merits, as you would
any finding: it stays in the baseline as debt, or gets a pattern or reviewed `distinct` exception with a reason. Verdicts are cached
per pair, so later checks reuse the same answer until the code changes.

The README block gets a `## Duplicate code` heading. Move or rename the heading to fit the README; later sweeps
only rewrite what is between the `dry-lint-progress` markers. dry-lint keeps each file's line endings.

## 6. Add the workflows

Fetch the examples, adapt them as listed, and save them in `.github/workflows/`:

| File | Purpose |
| --- | --- |
| [dry-lint.yml](https://raw.githubusercontent.com/gigaverse-app/dry-lint/v1/examples/dry-lint.yml) | the `dry-lint` check on every pull request and default-branch push |
| [dry-lint-judge.yml](https://raw.githubusercontent.com/gigaverse-app/dry-lint/v1/examples/dry-lint-judge.yml) | judges pull requests from forks with secrets, never running fork code (public repositories) |
| [dry-lint-audit.yml](https://raw.githubusercontent.com/gigaverse-app/dry-lint/v1/examples/dry-lint-audit.yml) | weekly audit: calls dry-lint's reusable `audit.yml@v1`, which opens a `dry-lint/ratchet` pull request when old debt is cleaned. Keep it a caller: never paste the audit's steps into the repository |

In each one:

1. Replace `secrets.ANTHROPIC_API_KEY` values with `secrets.KEY_SECRET`. Keep the audit's left-hand
   `ANTHROPIC_API_KEY` secret name and the Action input `anthropic-api-key`. TypeSafe credentials are optional for
   model ranking; model candidates still require agent review with or without them.
2. Replace `main` in `branches:` with `DEFAULT`.
3. In `dry-lint.yml` **and** `dry-lint-judge.yml`, uncomment `baseline: .dry-lint/baseline.json` and
   `require-complete: 'true'`: both post the judged check, so both enforce the baseline. Keep `dry-lint.yml`'s job
   `name:` expression: it names a fork's unjudged job `dry-lint detect`, so it can never satisfy a required
   `dry-lint` check.
4. Apply the pinning policy from step 1, and the parser version if it is not 3.13. The examples keep their
   explanations on lines of their own, so a SHA pin's `# TAG` is the only comment after a `uses:`.
5. Keep the triggers, permissions and concurrency as they are: the comments explain why. The README handling
   needs no edit: the audit, like the bootstrap, writes the progress block only when there is a `README.md`.

Two of them cannot run on this pull request. `dry-lint-judge.yml` starts from `workflow_run`, which GitHub reads
only from the default branch, so it first judges a fork's pull request after this one merges. The audit is
scheduled or dispatched, which also needs it on the default branch (see Optional, after the pull request). Say so
under "Not verified" in the report.

Lint them, with the repository's own workflow linter if it has one, otherwise:

```bash
uvx --from actionlint-py actionlint .github/workflows/dry-lint*.yml
```

Expected: no output. (`uvx actionlint` does not work: the PyPI package is `actionlint-py`.)

## 7. Add the hooks

Decide by the first rule that matches:

1. The repository has `.pre-commit-config.yaml`: merge the block below into it, keeping every existing hook.
2. It has no pre-commit config, but AGENTS.md or a CONTRIBUTING file (wherever step 1 found it, `.github/` or
   `docs/` included) invites new developer tooling or pre-commit: add the file with the block below.
3. Otherwise, including a repository with neither AGENTS.md nor CONTRIBUTING, or one whose README asks for no
   automated or tooling-only changes: add no hook file. Write `Hooks: skipped: <which of these applied>` in the
   report, and go to step 8.

```yaml
default_install_hook_types: [pre-commit, prepare-commit-msg]
# Other hooks must not also run at prepare-commit-msg.
default_stages: [pre-commit]
repos:
  - repo: https://github.com/gigaverse-app/dry-lint
    # v1, or the latest v1.x.y tag when the other hooks pin exact tags (step 1).
    rev: v1
    hooks:
      # The preset from .dry-lint/config.toml, with the baseline.
      - id: dry-lint
        args: [--baseline, .dry-lint/baseline.json, --require-complete]
      # Records findings no longer reported, without claiming they were removed.
      - id: dry-lint-trailers
```

- The hook inherits repository settings. Never force a lower-precision preset for local function checks.
- It reads `ANTHROPIC_API_KEY` from the shell or an untracked `.env`; add `.env` to `.gitignore`.
- It needs the key only when the staged change has a pair to judge. With nothing staged, no supported source
  file staged, or no look-alike, it passes and prints `no pair to judge, so no judge ran`. So
  `pre-commit run --all-files` in a tox or nox lint session, a CI lint job or pre-commit.ci passes without a key,
  because a clean checkout stages nothing: add no `SKIP=dry-lint`, `ci: skip` or key there. The required `dry-lint`
  check judges pull requests. A contributor's commit whose staged code has a look-alike still needs the key, and
  fails without it.
- With `rev: v1`, pre-commit caches the first install and warns that `v1` is a mutable reference. To pick up a
  newer 1.x release: `pre-commit clean && pre-commit install --install-hooks`. With an exact tag, run
  `pre-commit autoupdate --repo https://github.com/gigaverse-app/dry-lint` instead.
- Put the install command, `pre-commit install`, where contributors already read how to set up: the CONTRIBUTING
  file step 1 found, wherever it lives (`.github/CONTRIBUTING.md`, `docs/contributing.rst`), in its format; the
  README's development section only if there is none. Do not add a second CONTRIBUTING at the root.

Check it: `uvx pre-commit validate-config` prints nothing and exits 0.

## 8. Open the pull request

Commit settings, baseline, progress file, README (if the sweep changed it), workflows and hooks, following the
repository's commit style, and push. If step 5 did not already open the draft pull request, open it now:
`gh pr create --repo "$REPO" --draft --base DEFAULT --head "$(git branch --show-current)" ...`. Its body fills in
the repository's template, or says what it adds, the accepted pairs with their scores, the patterns with their
reasons, and what you verified.

Wait for the `dry-lint` run only. The repository's other workflows may take far longer, and nothing is required
until step 10, so do not wait on them with `gh pr checks --watch`:

```bash
for _ in $(seq 30); do   # the run appears a few seconds after the push
  RUN=$(gh run list --repo "$REPO" --workflow dry-lint.yml --commit "$(git rev-parse HEAD)" --json databaseId \
    --jq '.[0].databaseId')
  [ -n "$RUN" ] && break; sleep 5
done
gh run watch "$RUN" --repo "$REPO" --exit-status
```

Once `dry-lint` is a required check, `gh pr checks PR_NUMBER --repo "$REPO" --watch --required` does the same.

Expected: a green `dry-lint` check and a sticky comment from dry-lint (with 0 changed functions it reports a clean
run). The comment counts only the pushes dry-lint checked, so a push before `dry-lint.yml` existed is not in its
history. A red check on the adoption pull request means the key's secret is missing or misnamed, or the baseline
and settings disagree; read its log.

Other checks may fail for reasons outside this change, most often in a fork: an upstream workflow that requires a
pull request label ("Require PR label", a changelog label) fails because the fork has none of upstream's labels,
and deploy or publish jobs lack upstream's secrets. Do not create labels, edit those workflows or rerun them to
make them pass. Name each under "Left for you" in the report, with the check and the reason.

## 9. Prove it catches a copy

Pick a function of ten or more lines and copy it into a **different** file under a new name. Keep its body and its
docstring exactly as they are, and rename only one or two local variables. Functions in the same file are never
compared, so a same-file copy proves nothing. A copy with a shortened docstring and many renames looks like
a different function: one such probe fell to similarity 0.36 and was never proposed.

Before pushing, check that the detector proposes the pair at all:

```bash
dry-lint explain path/to/new_file.py::new_name path/to/original.py::original_name
```

Expected: `proposed: #1 of the N look-alike(s)` (or `#2`, `#3`) and `rule: none applies`. If it says
`not among`, undo renames until it is proposed, and do not push before it is.

```bash
git switch -c dry-lint-probe
# add the copy, then:
git add -A && git commit -m "test: dry-lint probe (do not merge)" && git push -u origin dry-lint-probe
gh pr create --repo "$REPO" --draft --base ADOPTION_BRANCH --head dry-lint-probe \
  --title "test: dry-lint probe (do not merge)" --body "Probe; will be closed."
for _ in $(seq 30); do   # the run appears a few seconds after the push
  RUN=$(gh run list --repo "$REPO" --workflow dry-lint.yml --commit "$(git rev-parse HEAD)" --json databaseId \
    --jq '.[0].databaseId')
  [ -n "$RUN" ] && break; sleep 5
done
gh run watch "$RUN" --repo "$REPO" --exit-status   # expected to exit non-zero: the check fails
```

Expected: the `dry-lint` check fails and the sticky comment names the pair with a judge score at or above the
preset's threshold. The comment's "Functions" findings mark the pair 🔴 blocking, and its "History and check
stats" list the same pair as 🟡 still reported: the latest checked push reports it. Then close the probe with
`gh pr close PROBE_NUMBER --repo "$REPO" --delete-branch`, switch back to the adoption branch and delete the local
probe branch.

The pair the comment names may be another existing copy rather than the function you copied. The advice names the
function to keep: the judge picks the side it thinks should own the code, often the public one.

## 10. Stop for the human

Keep the adoption pull request a draft until its `dry-lint` check is green and the probe proved red, then mark it
ready for review: `gh pr ready PR_NUMBER --repo "$REPO"`. If either is missing, for example because there is no key
yet, leave it a draft and say why in the report.

Tell the human exactly what is left. These need repository admin rights or secrets, so you do not do them:

1. **Judge secret** (only if step 1 found none): add a repository or organization secret holding an Anthropic API key
   ([Anthropic](https://console.anthropic.com)) and tell you its name.
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
Checks: adoption PR dry-lint <green/red>, <ready | draft: why>; probe PR <URL> red at <score> against <pair>, closed
Hooks: <added and validated | skipped: which step 7 rule applied>
Left for you: <required check ruleset> <secret, if missing> <DRY_LINT_RATCHET_TOKEN> <other failing checks: which, why>
Not verified: <anything you could not run, with the command and error>; the judge and audit workflows (run
  only from DEFAULT)
```

## Optional, after the pull request

- **History replay** (needs a key; cheap with `jev`): `dry-lint bench --replay 50` shows which recent commits would
  have failed or warned, and what judging would have cost. Without a key, skip it and say so.
- **Audit before merge**: a new workflow cannot be dispatched until it is on the default branch, so the first audit
  runs after merge (`gh workflow run dry-lint-audit.yml --repo "$REPO"`). With no cleanup it passes and opens no pull request.
- **Models**: model review is on by default. Leave `models.baseline` unset unless a human reviewed real model
  duplicates ([model adoption](https://dry-lint.readthedocs.io/en/latest/docs/model-adoption/)).

## Living with it

When a finding blocks, you are its final judge. Open both functions.

- **One concept:** delete the new copy and call the existing function, or extract a shared helper both use. Run the
  tests. If the finding says `drifted`, check which behavior callers need first.
- **Different concepts:** add a reviewed `distinct` entry to `.dry-lint/ignore.yaml`, with the exact
  `symbol`, a `from` list and a reason explaining their independent ownership. Start a new file with `schema: 1` and `distinct:`.
  Prefer this committed file over adding tool directives to source. Inline `distinct-from` remains an alternative
  when the explanation belongs beside the code. See [configuration and migration](https://dry-lint.readthedocs.io/en/latest/docs/configuration/).
- **One concept, two copies kept on purpose:** a `[[patterns]]` entry with a reason (step 4).
- **Generated code or a deliberate one-off:** `# dry-lint: ignore` in the function.
- **One pull request only:** the `dry-lint: override` label. It never waives widening the baseline.

To clean old debt: refactor a pair from the baseline, run the tests, then
`dry-lint sweep --update --budget-usd 1 --readme README.md --repository OWNER/NAME --branch DEFAULT` (without
`--readme README.md` when there is no Markdown README), and commit the metadata with the refactor. Never edit the
baseline by hand.

Thresholds come from measurements; change `fail_at` only after measuring on your own code
([judges and presets](https://dry-lint.readthedocs.io/en/latest/docs/judges/),
[benchmark](https://dry-lint.readthedocs.io/en/latest/docs/benchmark/)). The full manual path is the
[first-run tutorial](https://dry-lint.readthedocs.io/en/latest/docs/tutorials/first-run/); the CI design is in
[how CI runs dry-lint](https://dry-lint.readthedocs.io/en/latest/docs/ci/).
