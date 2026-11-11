# History reference miner

`mine_history.py` finds commits in which maintainers removed duplicated Python functions. It is Phase 1 of the
research program (`docs/research-program.md`): a reference of real duplicates that dry-lint did not propose.

It uses only the standard library (`ast`, `difflib`, `subprocess` to `git`) and Python 3.11+. It does not call any
model.

## Running it

Each stage reads the files the previous stage wrote in `--out`.

```sh
python mine_history.py log    --out OUT --repo CLONE --name litellm --commits 3000   # trees only, no blobs
python mine_history.py fetch  --out OUT --repo CLONE --name litellm --floor-gb 4     # batch-fetch the blobs
python mine_history.py mine   --out OUT --repo CLONE --name litellm                  # all candidates, with features
python mine_history.py select --out OUT litellm openhands                            # thresholds -> cases-*.jsonl
python mine_history.py sample --out OUT litellm openhands --n 30 --seed 20261111     # print a sample to read
```

- `CLONE` can be a `--filter=blob:none --no-checkout` partial clone. `log` reads commits and blob ids with
  `git log --raw --no-renames`, which needs only trees, so it fetches nothing.
- `fetch` fetches the blobs that `mine` will read, in batches of 2,000, over `git fetch --stdin`. It checks free
  disk before each batch and stops below `--floor-gb`. Fetching about 50,000 blobs for 12,000 LiteLLM and OpenHands
  commits took about 1.5 minutes and about 300 MB.
- `mine` reads blobs with `GIT_NO_LAZY_FETCH=1`. A blob that was not fetched is counted (`blob_missing`) and
  skipped; it is never fetched one at a time. It writes `candidates-<name>.jsonl`, `mine-<name>.json` (counters,
  commit range, HEAD) and `missing-<name>.txt`.
- `select` applies the thresholds below, drops repeats, splits off test-file cases and writes `cases-<name>.jsonl`
  and `summary.json`. It only reads files, so thresholds can be changed and re-applied in seconds.
- Several candidate files can be merged by concatenating them newest first; `select` reads every
  `commits-<name>*.json` in `--out` for the full commit messages.

The case files contain third-party source code. Keep them out of this repository.

## What counts as a case

Only commits with one parent are mined. Only `.py` files changed by the commit are parsed, at the parent P and at the
commit C. Files under `vendor/`, `third_party/`, `site-packages/`, `node_modules/`, `migrations/`, `generated/`,
`*_pb2.py` and `setup.py` are ignored. Commits that change more than 80 non-test Python files are skipped
(`skip_mega`).

A function is identified by its file path and its qualified name (`Class.method`, `outer.inner`). Names defined twice
in one file (overloads, property setters, conditional definitions) are skipped. A function's *own lines* are its
non-blank, non-comment source lines without its docstring and without nested functions and classes, so a change to
a nested function is attributed to the nested function only. Its statement count is counted the same way.

Calls are resolved statically, at the version that contains them:

- `f()`: a top-level function `f` in the same file, or `from m import f` resolved to a file in the repository
  (relative imports included; one hop through a re-export such as a package `__init__`);
- `self.f()` / `cls.f()`: a method `f` of the enclosing class in the same file (inherited methods are not resolved);
- `m.f()`: `m` imported as a module of the repository.

Any other call (`obj.f()`, a name imported from outside the repository) is unresolved and never matches. A "new
call" is a resolved target that the function at C calls and the same function at P did not.

**Moved or renamed.** A removed function is *moved* when some function in any added or modified file at C has the
same token sequence up to small edits (`difflib` ratio >= 0.8). A new helper is moved when some function at P in a
changed file is near-identical to it. Moved functions are not cases.

### pair-delete

1. Function A exists at P and is gone at C (no function at C with the same path and qualified name), and is not moved.
2. A function F that survives the commit called A at P, and at C makes a new call to B.
3. B exists at P (read from the file the import points at, at P). B is not A.
4. A and B each have at least 3 statements.
5. A did not already call B (otherwise the commit inlined a wrapper; dropped as `wrapper_inlined`).
6. Similarity: identifier-set Jaccard of A's and B's bodies >= 0.3, **or** at least half of A's identifiers occur in
   B (`a_in_b >= 0.5`; a small A replaced by a larger B that covers it).

Case: A at P and B at P. `callers` lists the redirected call sites.

### pair-shrink

1. Function A exists at P and at C, loses at least 5 own lines (difflib on own lines) and loses more than it gains.
2. A at C makes a new call to B, B exists at P and at C, and B is not A.
3. A and B each have at least 3 statements.
4. Similarity of the removed lines to B: at least half of B's identifiers occur in the removed lines
   (`containment >= 0.5`) **and** identifier-set Jaccard of removed lines vs B's body >= 0.2.

Case: A at P and B at P. A's member record carries `removed_lines`.

### family (extract-helper)

1. The commit adds a function H (path and qualified name not present at P in that file, and not moved) with at least
   3 statements.
2. At least two functions that exist at P and at C each lose at least 3 own lines, lose more than they gain, have at
   least 3 statements at P, and make a new call that resolves to H.
3. Each site's removed lines contain at least 40% of H's identifiers (`site_vs_helper_containment >= 0.4`). Sites
   below that are dropped from the family; the family needs two sites left.

Case: the sites at P (each with `removed_lines`) and H at C. The sites at P duplicate each other in the region they
lost.

### Thresholds

Identifiers are the names in the code minus Python keywords and `self`, `cls`, `None`, `True`, `False`, `str`, `int`,
`dict`, `list`, `len`, `isinstance`. The thresholds were set by reading every candidate from the newest 3,000 commits
of each repository with all thresholds at zero:

- Without them, pair-shrink is dominated by API migrations: LiteLLM and OpenHands commits that make many functions
  call one new-style accessor (`a_session_maker`, `call_sync_from_async`, `get_jwt_service`). Their removed lines
  share almost no identifiers with B (containment 0 to 0.25). Cases where the removed lines were B's logic scored
  containment 0.6 to 1.0.
- Pair-delete without them is mostly callers redirected to an unrelated function during a refactor (Jaccard < 0.1).
  The real ones scored Jaccard 1.0 (an exact copy deleted in favour of a shared one) or `a_in_b` >= 0.7.
- Families whose sites share less than about 40% of the helper's identifiers were mostly new generic utilities
  (a Redis client getter, a logging helper) called from functions that changed for other reasons.

### Other rules

- **Tests.** Functions in test files (`tests/`, `test/`, `testing/`, `test_*.py`, `*_test.py`, `conftest.py`) are
  mined like the rest. A case with any member in a test file is counted in `summary.json` under
  `test_cases_skipped` and left out of `cases-*.jsonl`.
- **Repeats.** A case with the same kind, members and code as an earlier one (a cherry-pick or backport) is kept
  once, at its oldest commit.
- **Keyword signal.** `keyword_signal` is true when the full commit message matches dedup, duplicat, consolidat, DRY,
  refactor, extract, reuse, shared helper, use existing, common helper, unify or single source. It is recorded, not
  required.

## Output record

```json
{"repo": "litellm", "kind": "pair-shrink", "commit": "...", "parent": "...", "date": "...",
 "message": "first line", "keyword_signal": false, "is_test": false,
 "members": [{"path": "...", "qualname": "...", "rev": "<sha>", "start_line": 1, "end_line": 9,
              "statements": 6, "code": "def ...", "removed_lines": ["..."]}],
 "helper": {"...": "family only, at the commit"},
 "callers": ["pair-delete only: path::qualname"],
 "features": {"jaccard": 0.5, "containment": 0.8, "...": "..."}}
```

`code` is the function's own source (decorators included), never a whole file. Line numbers are 1-based and refer to
the member's `rev`.

## First run (2026-11-11)

| Repository | Commits mined | Range | pair-delete | pair-shrink | family | test-file cases set aside |
| --- | --- | --- | --- | --- | --- | --- |
| LiteLLM (HEAD `7bcc462`) | newest 9,000 non-merge `.py` commits | 2026-07-16 .. 2026-11-10 | 10 | 30 | 106 | 47 |
| OpenHands (HEAD `b759f8a`) | all 3,468 non-merge `.py` commits | 2024-03-17 .. 2026-11-11 | 2 | 4 | 14 | 2 |

A fixed-seed sample of 30 cases (`sample --seed 20261111`), read by hand, held 26 real consolidations of
duplicated logic, 3 that were not duplicates and 1 unclear: family 11 of 13, pair-delete 5 of 7, pair-shrink 10 of 10.

## Known limits

- Calls through instances (`obj.method()`), inherited methods and names imported from outside the repository are not
  resolved, so cases that go through them are missed.
- The similarity measures are identifier sets, not aligned code. They separate "the removed lines were the helper's
  logic" from "the function now calls an unrelated helper", but they do not prove the two were duplicates.
- The commit that introduced the later copy (asked for by the research program) is not computed.
