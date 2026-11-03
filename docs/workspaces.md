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
TF-IDF index. Same-repository neighbours are excluded **before** selecting nearest neighbours, so local copies
cannot hide a cross-repository match. As with a regular backlog scan, proposals are mutual nearest neighbours,
not an exhaustive clone inventory. `--limit` bounds the number of pairs sent to the judge.

Repository-qualified identities prevent identical paths and function names colliding. Every function carries its
own repository and exact commit into JSON, the verdict store and Markdown links. Code changes invalidate verdicts
under the normal rules. Schema 1/2 files remain readable. Use text, JSON or Markdown for workspace scans; GitHub
annotations and code-scanning uploads are tied to one repository and are not workspace destinations.

Use `--judge none --format json` for offline candidate discovery. Similarity alone is not a duplication verdict.
The normal `check` and Action remain scoped to changed functions within the current repository. A workspace scan
is an explicitly separate backlog audit; it does not claim that an existing duplicate was introduced by a PR.

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
