# Share function indexes across repositories

Publish each repository's functions once from its trusted main commit. PR checks download the peer indexes and
rebuild the comparer over the combined corpus. They need no peer checkout, Git history, Bun install or peer-code
execution. A cache of previously judged pairs alone cannot discover a new function's neighbours.

## Publish

Put this workflow at **`.github/workflows/dry-lint-index.yml`** in every participating repository. Consumers verify
this path and the producing run, so another workflow cannot supply an index merely by choosing its artifact name.
Pin the same reviewed dry-lint commit and extraction options in publishers and consumers.

```yaml
name: dry-lint function index
on:
  push:
    branches: [main]
  workflow_dispatch:
  schedule:
    - cron: '17 4 * * 1'
permissions:
  contents: read
jobs:
  publish:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 1
          persist-credentials: false
      - uses: gigaverse-app/dry-lint@main # pin a reviewed commit in production
        with:
          mode: index
```

The artifact lives for 14 days; the weekly schedule refreshes unchanged repositories. Publishing requires no judge
key and posts no comment. Indexes contain source text, so private repositories require a token with **Actions read
and Contents read** access to all peers. Artifact access follows GitHub repository access.

## Consume

```yaml
- uses: gigaverse-app/dry-lint@main # pin the publisher's reviewed commit
  with:
    repository-indexes: |
      acme/mobile@main
      acme/frontend-common@main
    index-token: ${{ secrets.PEER_READ_TOKEN }}
    typesafe-api-key: ${{ secrets.TYPESAFE_AI_API_KEY }}
    warn-only: 'true'
```

The primary repository still needs a shallow checkout and enough targeted history to identify its changed
functions. Every peer ref is resolved once to an exact commit. Only that commit's compatible artifact is accepted,
from a successful push, scheduled or manual publisher run on the requested branch in the source repository.
Fork/PR artifacts, failed runs and artifacts from other workflow paths are rejected. Signed download redirects
do not receive the GitHub API token.

If no compatible trusted artifact exists, dry-lint downloads an exact-commit source archive and rebuilds the
index locally. It verifies files against the commit's Git tree and retrieves missing/modified blobs, covering
`export-ignore`, `export-subst` and LFS archive substitutions. This fallback never publishes PR-produced indexes
into the trusted artifact channel. It costs a source download and extraction until publishers are deployed or
refreshed. Incomplete trees, corrupt blobs, unavailable source and size limits fail the scope explicitly.

Every completed cross-repository markdown report includes repository, commit, function count, artifact/fallback
source and downloaded bytes. Missing indexes never become a clean empty corpus; an explicitly empty index is valid.

## Invalidation contract

| Change | Result |
| --- | --- |
| Source, source config, deletion or rename | Different source commit requires a new complete snapshot |
| Index schema | Different artifact namespace; unsupported schemas rejected |
| Built-in extraction implementation, parser versions, Python minor version/platform, extractor order/options/versions | Different extraction contract; regenerate or rebuild |
| Source include/exclude scope | Read from the indexed commit, recorded in the digest-protected snapshot |
| Judge, model/prompt, thresholds, consolidation destinations or guidance | No re-extraction; existing verdict-policy/context invalidation still applies |
| Peer corpus changes | Rebuild comparison statistics and rankings from the new combined function corpus |
| Expired, missing or corrupt artifact | Exact-commit source recovery; never use an older commit |

External extractor plugins must bump their declared version when extraction semantics or dependencies change,
as required by the plugin contract. Publishers and consumers must use compatible extraction options. A differing
configuration remains correct through fallback but loses artifact reuse until aligned.

The gzip JSON format has its own schema (`1`), repository and commit identity, extraction-contract fingerprint,
scope, functions and SHA-256 content digest. Unlike candidate files, functions retain behavior tokens and syntax
tree call names as well as code, line ranges, bounded context and full-source context digest. No serialized Python
objects or precomputed pair scores are loaded. Snapshots replace the entire corpus, so deleted functions cannot linger.

## CLI and audit reuse

```bash
dry-lint index --root ../shared --repository acme/shared --out functions.json.gz
dry-lint check --repo acme/web=. --repo-index acme/shared@FULL_COMMIT_SHA=functions.json.gz
```

`mode: fetch-indexes` downloads peers without checking or judging. Its `index-arguments` output points to a JSON
array of CLI arguments that an audit can pass to `scan` together with its primary `--repo`. The existing path-based
`--repo` mode remains supported and can be combined with indexes.

For local and cross-repository checks in one PR workflow, set both actions to `comment: 'false'`, preserve each
report, and call `python -m dry_lint.sticky --body local.md --body cross-repository.md` once under serialized PR
concurrency. Keep audits and index publishing out of that comment channel. The sticky publisher updates the one
canonical comment and deletes legacy duplicates; cache keys do not create separate stickies.
