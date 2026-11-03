# Design

dry-lint has three parts, and keeps them apart on purpose. The detector is cheap, local and stateless. The judge
is the expensive part, so it is pluggable and asked as little as possible. The verdict store remembers its answers.

## Detector

`functions.py` turns every tracked Python file into functions: top-level functions and methods, with nested
functions kept in their parent. Declaration-only stubs (docstrings, `pass`, `...`, and bare or zero-argument
`raise NotImplementedError`) are omitted before indexing so they do not consume neighbour or judge slots.
Abstract methods with implementations, other exceptions, and methods that do work before raising remain eligible.
Each remaining function gets two fingerprints:

- **Behaviour tokens** describe what the function does, as a bag of tokens:
  - `call:` for each name it calls;
  - `attr:` for each attribute it touches;
  - `w:` for each word in its executable identifiers, split from snake_case, camelCase and acronym boundaries
    (`parseHTTPHeader` becomes `parse`, `http`, `header`), with generic words dropped;
  - `fn:` for the words in its own name, counted twice;
  - `key:` for keyword argument names, string dictionary/subscript keys, literal keys passed to `get`, `pop` or
    `setdefault`, and the first literal option name passed to `add_argument`;
  - `ctl:` for loops, `try` blocks and `await`s.

  Type annotations and type parameters are excluded from behavior tokens. Arbitrary strings, comments and
  docstrings do not contribute prose tokens. Executable class identifiers are split like other identifiers;
  the enclosing class name is not added as context, because that displaced real cross-class duplicates in the
  [backend evaluation](benchmark.md#backend-follow-up-more-signals-are-not-always-better).

  Two functions that solve the same problem share many of these even when their names and structure differ.
  Field identities keep unrelated schemas from receiving identical fingerprints merely because both use
  `dict` and `get`. Different field names lower similarity; they never hard-suppress a candidate.
- **Structure hash** is the AST with docstrings, annotations and the function's own name removed, and every name the
  function binds itself renumbered in order of first use (`v0`, `v1`, …). Comments, formatting and renames do not
  change it; any change to the logic does.

`index.py` is a TF-IDF index over the behaviour tokens in plain Python, with an inverted index:
- sublinear term frequency, smoothed IDF and L2 normalisation;
- tokens found in more than 30% of all functions are dropped.

On gigaverse-ai (about 10,000 functions) parsing takes 3 s, tokenizing 1.6 s and building the index 0.2 s. A query
takes about 2 ms. That keeps it usable as a pre-commit hook without numpy or a model download.

`detector.py` works in five steps:

1. Read the changed lines from `git diff -U0 base...HEAD`, or from the staged diff.
2. Map those lines to the functions they touch.
3. For each touched function, take its three nearest neighbours **in other files** above a floor: 0.5, or 0.3 for
   functions shorter than six lines. Tiny helpers share few tokens, so their real twins score lower.
   Exclude all functions in the same file before limiting the results; a file with many similar methods must not
   crowd out eligible neighbours elsewhere.
4. Drop the pairs a rule settles:
   - both are dunders;
   - one calls the other (call names come from AST call nodes, never declarations, comments or strings; names
     remain a heuristic, without import or receiver resolution);
   - both match a declared `pattern`;
   - one carries `# dry-lint: distinct-from <qualified name suffix>`.
5. Return the rest as candidate pairs.

`scan` uses the same index for the backlog: pairs that are each other's nearest neighbour across files.

## Judge

A judge turns a candidate pair into a `Verdict`:

| Field | Meaning |
| --- | --- |
| `label` | `duplicate`, `drifted` or `separate` |
| `score` | 0–1: how sure the judge is that this is one concept |
| `behaves_differently` | 0–1: whether callers would notice a difference |
| `owner` | which side should own the single implementation |
| `why` | the reason, in one sentence |

`report_at` and `drop_below` apply to `score`. See [judges.md](judges.md).

## Verdict store

The store has one JSON line per pair a judge decided. It is keyed on the two qualified names, sorted, and records:
- both structure hashes;
- the detector similarity at the time;
- the behavior fingerprint version used to measure that similarity;
- the verdict.

A stored verdict is reused when:

- **both structure hashes match**: nothing that matters changed; or
- **the verdict was `separate`, the fingerprint version matches, and the pair is not more than
  `reopen_margin` (0.05) closer than when it was judged.**
  Changes that move two different concepts further apart cannot make them one concept.

A `duplicate` or `drifted` verdict reopens on any logic change, because that change might be the fix, or more drift.
Legacy records remain readable, and matching structure hashes still reuse their verdict. A logic change reopens
a record from an older/unknown fingerprint version instead of comparing distances from incompatible tokenizations.
Increment `BEHAVIOUR_FINGERPRINT_VERSION` whenever behavior-token semantics change; structure hashes are separate.

So a pair costs a judge call when it is first seen, and again only when it changes in a way that could change the
answer. The store is a cache of machine answers, not a reviewed file:
- locally it lives in `.git/dry-lint/verdicts.jsonl`, never committed;
- the GitHub Action keeps it in the Actions cache.

Losing it only costs re-judging. For all of gigaverse-ai it would hold about 1,900 pairs in 0.75 MB.

Human decisions are different: they belong in the code (`distinct-from`) or in configuration (`patterns`), where
they are reviewed, versioned and visible to the next reader.

## Why TF-IDF, not embeddings?

The spike compared this fingerprint with two code-embedding models on 7,195 functions
([benchmark](benchmark.md#detector-tf-idf-and-embeddings)):

- **Both find candidates.** Their top pairs overlap only about 40%, and each found real duplicates the other missed.
- **Embeddings rank better.** They separated real duplicates from false alarms better (AUC 0.86 against 0.66), but
  their candidate lists were no cleaner.
- **Embeddings cost more.** TF-IDF needs no model and indexes the repository in seconds on a CPU. The smaller
  embedding model is 311 MB and takes about 80 minutes on a CPU, or a GPU.

dry-lint uses TF-IDF for the detector so that it stays stateless and fast enough for pre-commit, and leaves ranking
to the judge, which reads the code. An embedding neighbour list is a natural second candidate source, behind an
option, for teams with a GPU in CI.
