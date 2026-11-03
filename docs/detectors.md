# Dryer comparer plugin

TF-IDF remains the default. Select [unclebob/dryer](https://github.com/unclebob/dryer) to find functions with similar
normalized syntax trees. Dryer implements dry-lint's existing `Comparer` protocol; extraction, rules, judging,
reports and storage stay in the shared pipeline. This plugin compares Python functions and skips other languages.

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
cache before offline use. TF-IDF needs none of these dependencies and never imports them.

Select it in `.dry-lint.toml` or under `[tool.dry-lint]` in `pyproject.toml`:

```toml
comparer = { use = "dryer", threshold = 0.82, min_lines = 4, min_nodes = 20 }
```

`--detector NAME` selects a comparer with its defaults, overriding the configured comparer and its options.
It works with `check`, `scan`, `detect` and `explain`, and with `bench --comparer`. Installed third-party comparer
names work through the same override. No new plugin slot or parallel ranking framework is introduced.
A missing extra produces exit code 2 with installation guidance; it does not silently substitute TF-IDF.

For the GitHub Action, select the comparer in repository configuration and install the upstream dependency via
the existing `plugins` input (there is no separate detector input):

```yaml
- uses: gigaverse-app/dry-lint@main
  with:
    plugins: dryer @ git+https://github.com/unclebob/dryer.git@66ff6d21a42c04afcad89c78a80066176d1294b0
```

Use the same dry-lint release in the detect and judge jobs so both understand schema 2's cache policy.
For pre-commit, add `additional_dependencies: ['.[dryer]']` and `args: [--detector, dryer]` to the hook.

## Shared policy, different scores

| Behavior | TF-IDF | Dryer |
| --- | --- | --- |
| Fingerprint | Calls, attributes, field/key identities, identifier words, control flow | Upstream normalized syntax subtree fingerprints |
| Similarity | Cosine over TF-IDF vectors | Upstream Jaccard over fingerprint sets |
| Default floor | 0.5; 0.3 below six source lines | 0.82 |
| Minimum size | Python extractor: two source lines | Four source lines and 20 normalized nodes |
| Query cost | Inverted-index search | Skip impossible fingerprint-size buckets, then compare eligible fingerprints |
| Default | Yes | Opt-in |

The comparer implements `index`, `neighbours` and `similarity` from [the plugin protocol](plugins.md#comparer).
`Detector` owns the cross-file policy, three-neighbour budget, dunder/call rules, patterns and inline suppression.
Both comparers exclude same-file functions before taking the neighbour limit, and the Python extractor omits
pure declaration stubs. `scan` returns mutual nearest neighbours. Equal Dryer scores break ties in corpus order.
`similarity` returns a raw score even below size gates, so `explain` can explain why a pair was not proposed.

The adapter calls upstream `entries_in_source` and `jaccard`; it does not copy the normalizer or scoring formula.
Source spans distinguish repeated declarations. Nested functions stay inside their canonical enclosing function.
Eligible entries are indexed by fingerprint count; Jaccard's exact set-size bound rejects impossible buckets
before scanning functions. Equal-score results still follow source order, independent of bucket traversal.
The comparison harness verifies every extracted fingerprint against full-file upstream extraction before timing.
It never invokes the standalone CLI or writes `.metrics/dry.edn` in the target repository.

Source-line minimums include docstrings and multiline signatures, just as upstream does. Boilerplate may pass
those gates. A score of 1 means fingerprints match, not that two functions have the same purpose. Neither comparer
replaces the judge. Dryer's identity includes the upstream revision and language-pack version.

## Cache compatibility

Schema 2 adds `similarity_reusable` to candidates and stored records. Comparers opt into that policy with an
optional attribute of the same name; absence means false. TF-IDF no longer opts in: its tokens leave out
literals, so the score can stay put while the logic converges.
Dryer leaves it false because normalization erases literals and fields: a flat Jaccard score does not justify
reusing a verdict about changed logic. Exact structure-hash reuse still works, including across comparers.

Schema 1 candidates and records remain readable and default to false. Their exact-hash matches still reuse the
verdict; changed code is rejudged once rather than guessing an old metric's policy. Existing same-comparer/version
checks remain in force when both sides opt in. The cache policy stays in core and survives detect/judge serialization.

## Reproduce the backend comparison

Use a clean detached checkout of the commit in [the comparison](dryer-comparison.md), then:

```bash
PYTHONUTF8=1 uv run --extra dryer python scripts/compare_detectors.py /path/to/frozen-backend \
  --base 9d5314c54bb3e7e15c825e8eac44e6960ab42d9d --runs 3 --output /outside/repository/evidence
```

The harness extracts one corpus, verifies upstream parity, alternates comparer order, records each duration and
pair count, and checks repeated runs return the same pairs. `summary.json` records source/base SHAs, versions,
settings and a corpus hash. Four candidate JSON files contain private source; keep them in private evidence
storage. No judge is called. Candidate counts measure review volume; quality requires labelled examples.
