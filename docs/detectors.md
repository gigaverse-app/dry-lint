# Detector plugins

TF-IDF remains the default. Select [unclebob/dryer](https://github.com/unclebob/dryer) to find functions with similar
normalized syntax trees. Both plugins feed the same candidate, suppression, judge, report and verdict-store flow.
This integration handles tracked Python functions, even though standalone Dryer supports other languages too.

## Install and select

From a dry-lint checkout:

```bash
uv sync --locked --extra dryer
uv run --extra dryer dry-lint check --root /path/to/project --detector dryer --judge none
uv run --extra dryer dry-lint scan --root /path/to/project --detector dryer --judge none --limit 50
```

For an isolated invocation:

```bash
uvx --from 'dry-lint[dryer] @ git+https://github.com/gigaverse-app/dry-lint' dry-lint scan --detector dryer --judge none
```

The extra installs upstream Dryer at commit `66ff6d21a42c04afcad89c78a80066176d1294b0`, plus tree-sitter and its
language pack. The first Dryer invocation downloads the Python grammar through the language pack; provision that
cache before offline use. TF-IDF needs none of these optional dependencies and never imports them.

Select the source in `.dry-lint.toml` or under `[tool.dry-lint]` in `pyproject.toml`:

```toml
detector = "dryer"
dryer_threshold = 0.82
dryer_min_lines = 4
dryer_min_nodes = 20
```

`--detector tfidf` or `--detector dryer` overrides configuration for either `check` or `scan`. A missing optional
installation produces exit code 2 with installation guidance; it does not silently substitute another detector.
In the GitHub Action, set `detector: dryer` to select and install the plugin. This input is required to install the
extra even if the repository already selects Dryer in its configuration. With pre-commit, add
`additional_dependencies: ['.[dryer]']` and `args: [--detector, dryer]` to the hook.

## Shared policy, different scores

| Behavior | TF-IDF | Dryer |
| --- | --- | --- |
| Fingerprint | Calls, attributes, identifier words, control flow | Upstream normalized syntax subtree fingerprints |
| Similarity | Cosine over TF-IDF vectors | Upstream Jaccard over fingerprint sets |
| Default floor | 0.5; 0.3 below six source lines | 0.82 |
| Minimum size | Canonical extractor: two source lines | Four source lines and 20 normalized nodes |
| Query cost | Inverted-index search | Compare eligible fingerprints, pruning impossible set-size ratios |
| Default | Yes | Opt-in |

A source implements `CandidateSource.similar(function, limit)` and is constructed by `make_source`. It returns
ranked corpus positions and scores. `Detector` owns cross-file selection, the three-neighbour budget, dunder/call
rules, declared patterns and inline suppression. `scan` still returns mutual nearest neighbours. As before, the
ranker first requests `neighbours + 8` results, then applies cross-file filtering; this can discard a match behind
many same-file neighbours. Equal Dryer scores break ties in canonical corpus order.

The adapter calls upstream `entries_in_source` and `jaccard`; it does not copy the normalizer or scoring formula.
Source spans distinguish overloaded signatures from their implementation. Nested functions stay with the enclosing
canonical function. The comparison harness verifies every extracted fingerprint against full-file upstream
extraction before timing. It never invokes the standalone CLI or creates Dryer's `.metrics/dry.edn` in the target.

Dryer source-line minimums include docstrings and multiline signatures, just as upstream does. Small abstract
methods and boilerplate can therefore pass its size gates. A score of 1 means the fingerprints match, not that two
functions have the same purpose. Neither source replaces the judge.

JSON candidates and stored records carry `detector`. Existing records default to `tfidf`. Unchanged structure
hashes can reuse a verdict across sources. After a logic change, a previous score can only support the existing
TF-IDF reuse heuristic when both old and new sources are TF-IDF. Dryer erases literals and field names, so a flat
Jaccard score cannot justify reusing a verdict about changed logic.

## Reproduce the backend comparison

Use a clean detached checkout of the commit recorded in [the comparison](dryer-comparison.md), then:

```bash
PYTHONUTF8=1 uv run --extra dryer python scripts/compare_detectors.py /path/to/frozen-backend \
  --base 9d5314c54bb3e7e15c825e8eac44e6960ab42d9d --runs 3 --output /outside/repository/evidence
```

The harness extracts one corpus, verifies upstream parity, alternates detector order, records every duration and
pair count, and checks that repeated runs return the same pairs. `summary.json` records source/base SHAs, versions,
settings and a corpus hash. The four candidate JSON files contain private source: keep them in private evidence
storage. No judge is called. Candidate counts measure review volume; quality requires labelled examples.
