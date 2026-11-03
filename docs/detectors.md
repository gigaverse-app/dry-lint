# Detector plugins

The native TF-IDF detector stays the default. The Dryer integration will provide an optional structural candidate
source using [unclebob/dryer](https://github.com/unclebob/dryer), while sharing dry-lint's tracked-file selection,
cross-file neighbour budget, suppression rules, mutual-nearest backlog scan, judges and verdict store.

## Verification plan

- Exercise the optional source through `check` and `scan` in a real temporary git repository.
- Verify renamed structural twins, minimum sizes, score thresholds, exclusions and suppression rules.
- Keep verdict reuse safe when switching between cosine and Jaccard similarity.
- Compare both sources on one frozen gigaverse-backend snapshot: identical eligible functions and neighbour
  policy, construction/scan time, candidate counts, pair overlap, and reviewed examples unique to each source.
- Run the full test suite, lint, package build and dry-lint on its own changes.

Candidate counts measure review volume, not precision or recall. A score of 0.82 from Dryer and 0.82 from TF-IDF
does not have the same interpretation. Any quality claims must be supported by labelled examples.
