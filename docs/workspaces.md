# Find duplication across repositories

Index related repositories together when an implementation in one app might already exist in a sibling app or
shared library. Run from the repository whose judge, comparer, extractor and reporting settings should apply:

```bash
dry-lint scan --root ../frontend-common \
  --repo gigaverse-app/gigaverse-web-app=../gigaverse-web-app \
  --repo gigaverse-app/gigaverse-mobile=../gigaverse-mobile \
  --repo gigaverse-app/frontend-common=../frontend-common \
  --judge jev --limit 20 --warn-only --report workspace.json --output workspace.md
```

Each checkout must have committed tracked files. Each repository's own include/exclude rules select its source;
the scanner's extractor plugins read those files without importing or running them. All functions enter one
TF-IDF index. Neighbours are selected separately for each peer repository, excluding same-repository copies.
The backlog scan proposes mutual nearest neighbours per repository pair, not an exhaustive clone inventory.
Ranking reserves turns for each repository pair and alternates source-file families, with configured shared
destinations first. A large app-to-app family cannot take every review slot ahead of shared-library matches.
`--limit` bounds the number of proposals assessed; `max_judgements` bounds uncached primary-judge calls.

Repository-qualified identities prevent identical paths and function names colliding. Every function carries its
own repository and exact commit into JSON, the verdict store and Markdown links. Code changes invalidate verdicts
under the context-aware reuse rules below. Schema 1/2/3 files remain readable. Use text, JSON or Markdown for workspace scans; GitHub
annotations and code-scanning uploads are tied to one repository and are not workspace destinations.

Use `--judge none --format json` for offline candidate discovery. Similarity alone is not a duplication verdict.
`check` and `detect` accept the same `--repo OWNER/NAME=PATH` arguments. They query only changed functions in
`--root`, which must be one of the supplied repositories, against the peer index. Their annotations belong to
that primary repository; links to matches use each peer's commit. Run a separate ordinary check for local
duplication. A workspace `scan` is a backlog audit, not a claim that a PR introduced every finding.

## Tell the judge where consolidated code belongs

In `.dry-lint.toml` (or under `tool.dry-lint` in `pyproject.toml`):

```toml
max_judgements = 30
judge = { use = "jev", model = "jev-1.14.0", context = true }

[[consolidation]]
sources = ["org/web/*", "org/mobile/*", "org/common/*"]
repository = "org/common"
path = "src/domain"
guidance = "Share portable domain rules. Keep web/native SDK providers and UI adapters in their apps. Reuse existing public exports before adding helpers."
```

For two source trees in one repository, omit `repository` and use repository-relative source globs:

```toml
[[consolidation]]
sources = ["apps/web/*", "apps/native/*", "packages/domain/*"]
path = "packages/domain/src"
guidance = "Shared domain behavior; platform storage stays in the apps."
```

| Setting | Meaning |
| --- | --- |
| `sources` | Globs matched against both functions' paths. Workspace paths include `OWNER/NAME/`; ordinary paths do not. Default `['*']` matches all pairs. |
| `repository` | Optional repository identity for the preferred destination. Omit for a local destination. |
| `path` | Required repository-relative directory, such as `src/domain` or `.`. Parent traversal and absolute paths are rejected. |
| `guidance` | Architecture constraints sent to the judge with the pair. |

All matching rules are retained as possible homes. Scope rules narrowly when different domains have different
owners. A destination need not exist yet. It guides ranking, judging and reported advice; it never forces two
different concepts to merge, imports one application into another, or moves code automatically.

Use the contextual judge's `guidance` option for repository-wide architecture constraints, independently of
destination rules. For example, `judge = { use = "jev", context = true, guidance = "Keep independent platform
providers and UI adapters in their apps." }` (on one line in TOML). This guidance applies even when no destination
matches. Changing it changes the judge identity and reopens cached answers. Destination-specific `guidance`
still applies only to matching pairs. For example, `sources = ["*.ts"]` avoids directing JSX components into a
shared domain directory without losing the judge's global platform constraints.

## Source context, cache and cost

Contextual Jev judging is opt-in; the legacy Python `reuse-v2` prompt remains unchanged. The TypeScript extractor
adds referenced imports, local declarations followed for up to three hops, and adjacent policy comments. It
parses source without executing it. Context and function bodies are bounded at 8,000 characters each. Imported
files and callers are not resolved, so a dependency contract may still need human review.

The contextual judge asks separately whether the concept is duplicated, whether an explicit platform/schema
boundary requires separation, where it belongs, and why. A probable separation or non-reuse reason suppresses
the recommendation. Uncertainty about the destination alone does not lower the duplication score. Reports
distinguish behavior drift from an identical copy. Keep initial adoption warning-only; see the measured
[diagnostic probe](context-probe.md) and its remaining errors.

Verdicts reopen when context, the full TypeScript source-file digest, a matching consolidation rule, or the
contextual model/prompt version changes. Hashing the full file also catches edits beyond truncated context.
An unchanged file at a new commit can reuse its verdict. This is conservative: an unrelated edit in the same
file can cause re-judging. The cache does not claim to detect changes inside unresolved imported files.

`max_judgements = 30` permits at most 30 uncached primary assessments per run. Cached answers do not consume
that budget. Remaining proposals are marked **deferred**, not clean, and can be assessed on a subsequent run
with the same store. Optional escalation is an additional call per selected pair. `max_findings` limits display
only and is not a cost control.

## Changed-function checks in GitHub Actions

Check out peers at trusted refs using a token with read access, then pass their paths to the action:

```yaml
- uses: gigaverse-app/dry-lint@main # Pin a reviewed commit in production.
  with:
    typesafe-api-key: ${{ secrets.TYPESAFE_AI_API_KEY }}
    warn-only: "true"
    sticky-key: cross-repository
    repositories: |
      org/web=.
      org/mobile=references/mobile
      org/common=references/common
```

The action does not fetch peers. Paths are resolved from the runner's working directory, independently of
`working-directory`, which selects the primary repository. Each checkout must be clean and committed; nested
peer checkouts may be untracked. Use `fetch-depth: 0` for the primary checkout and
`persist-credentials: false` everywhere. Skip private-peer checkout for fork PRs without the read token; retain
the ordinary secret-free local detect workflow for those PRs. Do not claim cross-repo coverage when that job skips.

## Turn a finding into one maintained implementation

1. Check both implementations and their callers. Shared syntax can hide different platform contracts, lifetime,
   authorization or error handling. Look for a common domain concept and identify the existing owner first.
2. If the shared package already owns the concept, extend that API and replace the copies. Otherwise extract a
   portable core into the shared package, with web/native behavior supplied at the app boundary. Avoid moving
   platform UI into a package just because the JSX looks similar.
3. Pin observable behavior with focused tests, including intentional differences. Publish a prerelease and test
   the exported package in both consumers. Source-only tests do not verify package entry points or compatibility.
4. Merge the shared implementation, publish a compatible stable version, then migrate each consumer and remove
   its copy. Check unrelated changes in the selected package version before upgrading either app.
5. Repeat the workspace audit against the resulting revisions. For deliberately separate concepts, record a
   `dry-lint: distinct-from <repository/path::function>` decision next to the code, with its reason.

For private repositories, run the audit from a trusted workflow with a read-capable checkout token. Keep tokens
out of Git credentials after checkout (`persist-credentials: false`), and never run package installation, scripts
or plugins supplied by the analyzed repositories with those credentials. A manual or scheduled default-branch
audit is separate from the secret-free PR detect / trusted `workflow_run` judge boundary.
