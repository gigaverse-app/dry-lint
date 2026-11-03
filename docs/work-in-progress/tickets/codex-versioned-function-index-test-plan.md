# Versioned function indexes

Publish one extraction snapshot per repository commit and extraction contract. Consume peer snapshots as data,
retaining the existing candidate selection, contextual verdict invalidation and single sticky publisher.

- Compare checkout and serialized-index candidates, scores, filtering, tokens, calls, context and source links.
- Reject wrong repository/commit/schema/toolchain, corrupt content, duplicate identities and unsafe paths.
- Exercise empty corpora, deletions, renames and source-scope changes; judge policy changes preserve extraction.
- Verify trusted workflow provenance, pagination, expired/missing artifacts and exact-source recovery over HTTP.
- Run action publishing/consuming through the real CLI; no peer git invocation on an artifact hit.
- Keep existing sticky race/stale-head/legacy-duplicate regression tests passing.
- Run pytest with coverage, ruff, build, self dry-lint and actionlint; validate adoption runs and sticky counts on GitHub.
