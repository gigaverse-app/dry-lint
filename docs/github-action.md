# GitHub Action

Use `gigaverse-app/dry-lint@v1`, and published major-version tags for established Actions, such as
`actions/checkout@v7`. If your repository pins actions to commit SHAs, follow that policy instead:
`gigaverse-app/dry-lint@<sha> # v1`, with the SHA from `gh api repos/gigaverse-app/dry-lint/commits/v1 --jq .sha`.

Create `.github/workflows/dry-lint.yml` using the [complete quick start](../README.md#add-it-to-github-actions)
or copy [the extended workflow](../examples/dry-lint.yml), which also handles default-branch pushes and
override-label changes. To add dry-lint to an existing job, these are the only steps needed:

```yaml
- uses: actions/checkout@v7
  with:
    ref: ${{ github.event.pull_request.head.sha || github.sha }}
    fetch-depth: 1
- uses: gigaverse-app/dry-lint@v1
  with:
    typesafe-api-key: ${{ secrets.TYPESAFE_AI_API_KEY }}
```

Give that job `contents: read` and `pull-requests: write` permissions. You can run it before creating any
secrets: it lists look-alikes without model calls, PR comments, or failures on findings. To enable judging, store
your TypeSafe API key as a repository or organization secret and pass it to `typesafe-api-key:`; the secret can have
any name, and the examples call it `TYPESAFE_AI_API_KEY`. To start with advisory findings, set `warn-only: "true"`.

The action manages Python 3.13 and its dependencies in a separate environment, ignoring project uv settings
in `pyproject.toml` and `uv.toml`. It does not install your application or change its virtual environment.
Python, TypeScript and TSX projects use the same setup; no Python project file or application build is needed.
Explicit uv environment variables still apply, for example to configure a private package index or proxy.

If you also accept pull requests from forks, add [the judge workflow](../examples/dry-lint-judge.yml) to judge
their candidates with your secrets. Without it, fork PRs still get the local candidate scan.

Check out the PR head from the event. GitHub can refresh its synthetic merge ref with newer base-branch commits
after the event was created. Comparing that merged checkout with the event's older base SHA can report functions
the PR never changed. The head ref above keeps detection and source links on the same commit; push events use
their event SHA. As a backstop, PR detection takes a temporary detached snapshot of the event head when
the checkout differs, including the head's settings and reviewed feedback. It leaves the caller's checkout
and index unchanged and removes the snapshot on success or failure. The separate trusted judge workflow still checks out the default branch for its settings.

## What a pull request gets

For existing repositories, [sweeps and ratchets](sweeps.md) add a shrinking duplication baseline and README badge.
Set `baseline: .dry-lint/baseline.json` and `require-complete: 'true'` for enforcement. `mode: sweep` runs a read-only
repository audit for a scheduled/manual workflow.

- **Annotations** on the changed functions that re-implement existing code, with the function they duplicate
  and what to do about it.
- **One sticky comment**, found again by its `<!-- dry-lint -->` marker and edited in place on every push:
  - The cleanup basket and a single blocking, advisory or overridden status stay visible. Each scan has a
    collapsed summary naming its result; blocking counts and incomplete assessments are visible in that summary.
  - Expand a scan for one row per pair: a severity dot, the concept, both copies linked at the analyzed commit (short file names,
    the full path on hover, GitHub Enterprise included) and the verdict with the judge's fix.
  - Fold-outs hold each judge reason with a copy-paste `distinct-from` line, and every scope of override.
  - A `dry-lint scan` report reads as an audit of existing code that never blocks, not as a pull request review.
  - A clean scan shows its counts in one compact horizontal row, with judge decisions and the closest call below.
    Counts are not repeated in badges and explanatory paragraphs. Opt out with
    `comment-on-clean: "false"`.
  - When findings are fixed, the comment says so instead of going stale.
  - **Cleanup progress above the findings**: a basket of pairs cleaned up, still tangled, and dismissed, with a
    small celebration when the latest analyzed commit clears a pair. **History and check stats** folds the accounting,
    counting rules, commit history and repository totals together.
    See [the ledger](#the-ledger).
  - Old keyed comments are removed on the next publish. Serialize publishers to prevent creation races.
  - Once dry-lint's repository is public, the comment carries the banner. The action checks first, so it never
    shows a broken image. The banner comes from the action's own revision (`@v1`, a tag or a SHA), never from a
    moving branch.
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

### Comparison links

The cleanup basket includes a collapsed comparison table with immutable **A** and **B** source links, a GitHub
diff from the last reported commit to the current head, and the recorded judgment. Pairs are grouped by outcome,
each group headed by what it means: **Still duplicated**, **Cleaned up**, **Near misses** (judged one concept but
under the reporting bar, named in the heading), **Not judged yet**, **Different concepts** (judged separate,
whatever the score) and **Dismissed**. Only the first counts as still tangled. Each row gives the **duplicate
score** (the judge's 0 to 1 estimate that the two are one concept, marked when the copies already drifted), the
model that **decided** it (with the first judge it rechecked, for an escalation), and its reason with both
functions named. Up to five judged pairs are shown, the groups in that order; pairs a rule settled without a
judge are listed after them with the rule. The table uses the existing report decision, including any first-judge
threshold, without rejudging or changing the counts.

- **Private, internal, unknown visibility, or GitHub Enterprise Server:** GitHub links only. No external viewer
  link, source payload or additional source fetch is generated. A public repository with a private or unverifiable
  peer also stays on GitHub. Visibility is checked through the GitHub API; failed checks preserve the GitHub links.
- **Public repositories:** the table additionally links to the [static viewer](https://gigaverse-app.github.io/dry-lint/compare/).
  The viewer reads public source at fixed commit SHAs directly from GitHub, without authentication. It verifies
  that every source repository is still public before fetching code. It has no backend, analytics, credentials,
  or model calls. Source coordinates and the existing judgment travel in the link fragment; source code is not
  embedded in the URL or stored in the sticky ledger.

After a pair stops being reported, dry-lint parses both original paths at the current commit. If exactly one
original symbol still exists and both reads completed, the viewer offers all three columns: original A, original
B, and the remaining implementation. **This is evidence of a surviving symbol, not proof of consolidation.**
For a remaining Python function, direct bare-name calls to unique top-level definitions in the same file are
resolved through the syntax tree and compiler symbol tables. Local shadowing, rebindings and ambiguous names
are excluded. Up to five helpers, each at most 600 lines, are referenced at the same commit using the already-read
file. The viewer starts with the first helper in the After column, offers a selector for its caller and other
helpers, and shows the call site and helper definitions below. No additional judge or source API calls are needed
to record these references. This is static call evidence; it does not prove both original callers migrated or
account for runtime monkey-patching. Imports, attributes, nested scopes, other languages and recursive traversal
are not followed. Missing helper evidence leaves the remaining function and full GitHub diff usable.

Review the caller diff and any extracted helpers. A moved/renamed result, two surviving originals, unsupported
language or failed read leaves the result unidentified; the viewer shows A and B with an explicit explanation.
No model is asked to infer a destination. Dismissals never get a presumed consolidation result. A pair with no
recorded cleanup (below threshold, open, dismissed, deferred or unjudged) is shown as A and B only, with no After
column. Each card is headed by the qualified name (`Owner.method`), since overrides share a method name. The
viewer's "full GitHub diff" runs from the finding's commit to the head, or, for a pair found at the head, over the
pull request's own base...head; when neither range has changes, there is no link.
New links use viewer schema 2 with bounded helper coordinates; schema 1 links remain readable and explicitly say
that they did not record helper references. No source bodies are included in either link format.

Comparison links are bounded to 12,000 characters, the comparison section limits viewer links to a 20,000-character
budget, and the viewer accepts up to 600 lines per function. Oversized links keep their GitHub source links;
unavailable or oversized source shows an error with usable GitHub links. Historic ledgers without source
coordinates keep their accounting; dry-lint does not invent past evidence. Retained evidence has a 16,000-byte
budget: older source/judgment details can be dropped while every pair's cleanup counts and state remain intact.

Use `viewer-url: ''` to disable interactive links. To host the same static viewer in the repository owner's Pages
site, copy `viewer/index.html`, `style.css`, `app.mjs`, and `diff.mjs` into that site's `/dry-lint/` directory in its
existing deployment, then configure:

```yaml
- uses: gigaverse-app/dry-lint@v1
  with:
    typesafe-api-key: ${{ secrets.TYPESAFE_AI_API_KEY }}
    viewer-url: https://OWNER.github.io/REPOSITORY/dry-lint/
```

This input cannot enable the viewer for a private repository. For manual sticky publication use
`python -m dry_lint.sticky ... --viewer-url https://OWNER.github.io/REPOSITORY/dry-lint/`.
Enable Pages once in the hosting repository's settings; no GitHub App is needed. Preserve an existing site's
deployment rather than replacing it with the example publisher in `.github/workflows/viewer.yml`.

## When it fails, and false positives

Two thresholds decide what a finding does: `report_at` and `fail_at`, both in `.dry-lint.toml`. The `fail-at`
action input (or `--fail-at` on the command line) overrides `fail_at` for one workflow.

| Judge score | Finding | Check |
| --- | --- | --- |
| below `report_at` (0.8) | not shown | green |
| `report_at` up to `fail_at` | warning annotation, listed in the comment | green |
| `fail_at` and above | error annotation, listed first as **blocking** | **red** |

The thresholds come from the judging preset, which the keys you pass choose ([judges](judges.md)):

| Keys passed | Preset | Fails at | Precision / recall | Red pull requests |
| --- | --- | --- | --- | --- |
| `typesafe-api-key` + `anthropic-api-key` | `jev+opus` | 0.55 | 98% / 85% | |
| `typesafe-api-key` + `claude-code-oauth-token` | `jev+claude-code` (Opus, through the subscription) | 0.55 | same model as `jev+opus` | |
| `typesafe-api-key` only | `jev` | 0.8 | 94% / 73% | 15% of 600 |

A red check is a real duplicate about 60 times in 61 with `jev+opus`, 17 in 18 with `jev`; the overrides below
handle the rest. To fail only on near-certain duplicates, raise `fail-at` (with `jev`, 0.9 is 100% precise and
45% recall); findings between `report_at` and `fail-at` then only warn ([benchmark](benchmark.md)). `warn-only`
does not fail on findings. Operational failures still fail the action and appear in the log and job summary.
Advisory findings and overridden findings use warning annotations. Required model reviews and budget-deferred
pairs are counted separately from confirmed duplicates in the text summary.

**When dry-lint is wrong**, record the decision where it belongs:

| Scope | How | Where it lives |
| --- | --- | --- |
| this pair | `# dry-lint: distinct-from src/text.py::shorten_text` in the new function | next to the code it explains |
| this function | `# dry-lint: ignore` in the function | next to the code |
| a family of deliberate look-alikes, or copies kept on purpose | a `[[patterns]]` entry (`members`, `reason`) in `.dry-lint.toml` ([how patterns match](../README.md#when-it-is-right-not-to-merge-them)) | configuration, reviewed |
| whole paths | `exclude` in `.dry-lint.toml` | configuration, reviewed |
| this pull request only | the `dry-lint: override` label | the pull request; the comment says it was overridden |

The code and configuration routes are permanent and reviewed like any change: the pair is never proposed again.
The label is for an urgent merge or a call you don't want to write down. It lets blocking findings through for this
pull request only, and the comment records that it did. Adding or removing the label re-runs dry-lint (the example
workflow listens for `labeled` and `unlabeled`), and the verdicts come from the cache, so that re-run costs no
judge calls.

## When the judge budget runs out

An unresolved candidate is a review task for the coding agent, not a confirmed duplicate or an infrastructure
failure. The check stays red and lists the exact pairs, source locations and any provisional first judgment.
The coding agent inspects both implementations and their callers, then either consolidates the duplicated
behavior or records a reasoned, pair-specific dismissal using the existing `distinct-from` comment or
`dry-lint feedback dismiss <pair> --from report.json --reason "..." --reviewer "..."` command. Commit that
review alongside the code; a rerun verifies it against the current source. Do not raise the budget or bypass
the whole check merely to clear an unresolved pair.

No new judge credentials or automated model calls are needed for that fallback. A missing extractor/runtime,
unreadable input or an unavailable judge with no reviewable evidence remains a separate operational failure.

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
| `anthropic-api-key` | | Enables escalation: with `typesafe-api-key`, Claude Opus re-judges the Jev scores it is least sure of (preset `jev+opus`), about $0.005 a pull request on average ([judges](judges.md)). Empty: no escalation. |
| `claude-code-oauth-token` | | A Claude subscription token (`claude setup-token`): the `claude-code` judge runs on the subscription. The `claude` CLI is installed only when this is set. |
| `claude-code-version` | `2.1.311` | The `@anthropic-ai/claude-code` version installed for it. |
| `preset` | | Judging preset; `dry-lint config` lists them. Empty: dry-lint picks one from the keys it has (jev+opus, jev+claude-code, jev, ...). |
| `budget-usd` | `0.04` from the settings | Most judging spends on a pull request, all pushes together, at list price, subscriptions included. The verdict cache carries the running total from push to push. |
| `judge` | `auto` | `auto` leaves the choice to the preset. An explicit `jev`, `command`, `none` or installed plugin replaces it (preset `custom`). |
| `judge-command` | | For `judge: command`: reads the prompt on stdin, prints a JSON verdict ([judges](judges.md)). |
| `plugins` | | Extra packages to install, one per line. |
| `mode` | `auto` | See above. |
| `base` | the PR's base commit, or the previous push, or the default branch | What to compare with. |
| `working-directory` | `.` | The repository, or the package within a monorepo. |
| `repositories` | | One `OWNER/NAME=PATH` per line, including the primary checkout. Enables changed-function checks against committed peers in `single`/`detect` mode. Checkout and credentials remain the workflow's responsibility. See [workspaces](workspaces.md). |
| `comment` | `true` | Keep the sticky comment. |
| `comment-on-clean` | `true` | Comment on a clean pull request too; `false` comments only once there are findings. |
| `share-totals` | `true` | On the default branch, add each merged pull request's counts to [the global counter](#the-global-counter); `false` opts out. |
| `share-goldens` | `false` | Opt in to [dry-lint's benchmark](#sharing-goldens-opt-in): keep each merged pull request's settled pairs as a `dry-lint-goldens` artifact for collection. |
| `check-run` | `true` | In judge mode, post a `dry-lint` check run on the pull request's head; failure for blocking findings, neutral for advisory findings. |
| `sticky-key` | | Legacy marker label, and the suffix that tells apart the verdict saves of several steps in one job; all keys share one PR comment. |
| `fail-at` | the preset's (0.55 with `jev+opus`, 0.8 with `jev`) | Judge score at or above which a duplicate fails the check. |
| `warn-only` | `false` | Report findings as warnings without failing; operational errors still fail. |
| `override-label` | `dry-lint: override` | The pull request label that lets blocking findings through. |
| `github-token` | `github.token` | Needs `pull-requests: write`; in judge mode also `actions: read` and `checks: write`. |

The outputs are `mode`, `findings` (duplicates and required reviews), `blocking` (required reviews or findings at `fail_at`, before advisory mode or an override),
`overridden` and `exit-code`: 0 for nothing blocking, 1 for blocking findings, 2 when dry-lint could not run. Exit
code 2 always fails the step, including subprocess crashes and report-rendering failures. Errors produce an
error annotation and a job-summary message even with `comment: false` or `warn-only: true`. Each invocation
discards its previous report before scanning, so a failed scan cannot reuse an earlier successful report.

Thresholds and exclusions live in a `.dry-lint.toml` at the repository root, or under `[tool.dry-lint]` in
`pyproject.toml` (`.dry-lint.toml` wins when both exist), so that the action, the pre-commit hook and the command
line all agree ([README](../README.md#settings)). Prefer `.dry-lint.toml`; it also avoids rerunning every test in
repositories whose CI treats any `pyproject.toml` change as global.

## Verdict cache

Verdicts are kept in the Actions cache:
- Caches are partitioned by job, so concurrent jobs never race to save different verdict sets under one key.
- Several dry-lint steps in one job share one store, and so one pull request budget: the first step restores it,
  later steps add to it rather than restoring over it, and each step saves under its own `sticky-key` suffix. The
  newest save holds all of them, and it is what the next run restores.
- A pull request's run restores the newest verdicts it can see, so a later push only judges pairs whose logic
  changed.
- Runs on the default branch, that is pushes to `main` and judge-mode runs, save their verdicts where every pull
  request can read them.

Losing the cache only costs re-judging.

## The ledger

The sticky keeps a running account across a pull request's pushes, and the repository keeps one across its merged
pull requests.

The basket separates **Baseline reduced**, **Still reported**, **Dismissed**, and **No longer reported**.
Absence from the next scan cannot establish removal: reverting an extraction, renaming code or changing retrieval
can all produce it. It never earns cleanup credit or a positive gold label. Deferred/unjudged pairs and scopes
that did not complete remain open.

Baseline reductions require the existing evidence contract: a side present at the merge base is removed, or the
revisited pair is explicitly judged separate. A moved side whose partner still duplicates a survivor earns no
credit. Each check restates the full list, so returning debt revokes its credit. The baseline badge changes only
through the repository audit. A fork's judge-only run has no source tree and claims no baseline cleanup.

The optional hook trailers use `Dry-Lint-Not-Reported` and `Dry-Lint-Dismissed`; CI findings take precedence.
Legacy `Dry-Lint-Kept-Out` trailers and sticky states are read as absence. The ledger retains run costs, counts,
source evidence and push history, but no longer exports absence as removed duplicates to the global counter.
Already published global totals are historical and require a separate historical recomputation.

Runs are deduplicated by id/attempt. Only completed scopes settle findings. The repository ledger folds each
merged PR once and lives in the Actions cache. Losing the cache starts a new accounting period; it invents no
history. Skipped or unobserved pushes receive no cleanup credit.

The fold needs the default branch to run dry-lint on push, as [the example workflow](../examples/dry-lint.yml)
does, and a token that can read pull requests.

### The global counter

After folding, the run sends each newly merged pull request's counts to dry-lint's public counter, a
[Cloudflare Worker](../counter) at `https://dry-lint-counter.gigaverse-oss.workers.dev`, so [the sign in the README](../README.md#the-counter) counts every
repository that shares. A contribution holds the repository's counter key, the pull request number, the counts
the ledger keeps (kept out, caught, dismissed, still open at merge, pushes, runs, judgments, functions checked,
look-alikes compared, verdicts reused, spend; and of the duplicates kept out, how many had drifted, how many were
rewrites rather than copies, and their lines) and the dry-lint version: no code, names, paths or people.

- **Pseudonymous, not anonymous.** The counter key is the SHA-256 of the repository's numeric GitHub id
  (`GITHUB_REPOSITORY_ID`), never of its name. It ties the repository's pull requests together, but a name does not
  lead to it: a private repository's id is visible only to people who can see the repository, and the counter
  refuses to look a repository up by name. The key survives renames and transfers. A run without a repository id
  sends nothing. The run on the default branch prints the key, for a repository that wants
  [its own sign](../README.md#the-counter).
- **Opt out** with `share-totals: "false"`. Nothing is sent, and anything waiting is dropped.
- **Counted once.** The counter keys contributions on the repository's key and pull request number, so a resend
  changes nothing. A send that fails waits in the repository's ledger (`outbox`) for the next push, and never
  fails the run.
- **Bounded.** Counts are self-reported; the counter refuses a pull request claiming implausible figures.

### Sharing goldens (opt-in)

A reviewed dismissal can supply a negative label with its reason. A disappeared finding cannot supply a positive
label: a revert and a real consolidation can look identical to retrieval. With `share-goldens: "true"`, the fold
keeps eligible dismissals as pointers; legacy disappearance-based positive labels require re-adjudication.

- **Pointers, not code.** Each record holds the repository, the pinned revision, both functions' paths, names and
  line spans, the judge's verdict, and how the label was learned. Model pairs, pairs settled by the pre-commit
  hook, accepted-backlog cleanups and pairs still open at merge are left out.
- **Nothing is sent.** The records stay in your repository as a 30-day `dry-lint-goldens-RUN-ATTEMPT` artifact.
- **Collected only from registered public repositories.** dry-lint's maintainers run
  [`scripts/collect_goldens.py`](../scripts/collect_goldens.py) over the repositories listed, by pull request, in
  [`docs/goldens/adopters.toml`](goldens/adopters.toml), with the license that allows their code in a public
  panel. It refuses a private repository and fetches each function at its pinned revision.
- **Weak labels, staged.** "Kept out" is inferred and a dismissal can be wrong, so collected goldens become
  diagnostic panels in the `examples/*-gold.toml` format, never part of the population estimates, which use blind
  three-vendor labels.

To opt in, set `share-goldens: "true"` on the dry-lint job that runs on pushes to your default branch, and add
your repository to the registry in a pull request to dry-lint.

## Running it in a monorepo, or more than once

Run local and cross-repository checks in one job, with `comment: "false"` on both steps.
Give the second step a distinct `sticky-key`; both use the same verdict store and budget. Copy
`$RUNNER_TEMP/dry-lint/comment.md` and `report.json` after each step to `$RUNNER_TEMP/local.{md,json}` and
`$RUNNER_TEMP/cross-repository.{md,json}`. Then publish once, passing only the reports that exist:

```bash
python -I -m dry_lint.sticky \
  --report "local=$RUNNER_TEMP/local.json" --report "cross-repository=$RUNNER_TEMP/cross-repository.json" \
  --body "$RUNNER_TEMP/local.md" --body "$RUNNER_TEMP/cross-repository.md" \
  --pull-request "$PR_NUMBER" --expect-head "$HEAD_SHA" --findings "$TOTAL_FINDINGS"
```

Repeated `--body` arguments combine the scopes under headings derived from their filenames. Name each
`--report` by its scope: the ledger then leaves a scope's earlier duplicates open on a run where that scope did
not report, instead of counting them as kept out. Sum findings from both step outputs. If either scope fails,
include an explicit incomplete-scope warning; do not call it clean. Keep repository/backlog audits in job summaries
and artifacts, with no separate comment publisher. On an incomplete run, pass the named reports of the scopes that
completed: the missing scope's findings stay open instead of counting as cleaned up. Markdown alone does not start
a ledger, because it cannot identify pairs reliably.
A single publisher per PR, workflow concurrency, and `--expect-head` prevent concurrent or stale reports.
GitHub has no atomic comment upsert, so several independent jobs must not each publish. Legacy keyed comments
are reconciled into the one current report. A key no longer creates an independent comment.

## Shallow source checkouts

Use `fetch-depth: 1` and `persist-credentials: false` for every source checkout. Only the primary repository
needs ancestry to identify changed functions: the action fetches just its base/head refs, starting at depth 2
and increasing to 32, 128, 512 and at most 2048 until their merge base is available. It never fetches all branches
or runs `--unshallow`. If ancestry exceeds that bound, it reports an error rather than comparing the wrong
commits. Supply more history explicitly or rebase that branch. The token is passed only to the fetch process
through its environment, never persisted in Git configuration or added to the command line.

Peers require only one trusted commit's source tree. Full audits and installation-only action steps can use
`base: HEAD`, avoiding any ancestry fetch. Frozen probes check out their exact labelled revisions at depth 1.

The semantic judge needs only `candidates.json` and trusted configuration; it does not need source clones.
Discovery still needs all eligible functions to find new matches. Previously judged pairs cannot stand in
for that corpus: they omit functions that have never been paired. A future portable function index should
carry repository/commit, extractor version, include/exclude policy, tokens/calls and source context. Until
that format and invalidation contract exist, shallow peer snapshots are the simpler correct input.
