# A reference of duplicates maintainers removed

Every label so far covers a pair the detector proposed, so recall is unknown. This directory measures it against
duplication people actually fixed: Phase 1 mines git history for duplicates that maintainers later merged, and
Phase 2 replays the shipped `balanced` preset at the commit that introduced each later copy. The plan is in
`docs/research-program.md`.

## Phase 1: what it found

557 cases mined from the full history of six public repositories (LiteLLM, OpenHands, Saleor, Zulip, Prefect,
NetBox; 95,177 non-merge Python commits): 227 pairs and 330 families.

- Opus labelled each case at the commit before the consolidation: 453 yes, 60 partial, 42 no, 2 unclear.
- 184 of the 513 real cases had copies that already behaved differently before the maintainers merged them.
- Confirmed real pairs: 199 (LiteLLM 100, Zulip 43, Saleor 38). The program's bar of 200 pairs with 50 in each of
  two repositories is just missed. Families (314 real) far exceed their bar of 40.
- The miner's own hand-read of samples: 26 of 30 real (first two repositories) and 18 of 20 real (the other four).
- 402 records are exported after the size rules (at most 150 lines and less than half the file per snippet). 111 real
  cases were dropped by those rules; none were truncated.

The labels are Opus's; human review is pending.

## Where the reference lives

The reference is in the private repository
[gigaverse-app/dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens), folder `history-reference/`:
402 exported records. It holds only the judged functions, never whole files or repositories, so the third-party code
stays out of this repository.

## Running

Both tools are standard-library Python (the replay also imports `dry_lint`). Paths below are placeholders: `$OUT` is the miner output folder, `$CLONES` holds the miner's clones, `$REPOS` is the replay root.

```sh
# Phase 1: mine one repository (stages in order; see "Miner reference" below)
python mine_history.py log   --out $OUT --repo $CLONES/litellm --name litellm
python mine_history.py fetch --out $OUT --repo $CLONES/litellm --name litellm
python mine_history.py mine  --out $OUT --repo $CLONES/litellm --name litellm
python mine_history.py select --out $OUT litellm
python mine_history.py blame --out $OUT --repo $CLONES/litellm --name litellm

# Phase 2: replay the shipped preset (needs ANTHROPIC_API_KEY in the environment)
python replay/replay.py --root $REPOS cases.jsonl results.jsonl --detect-only   # no spend
python replay/replay.py --root $REPOS cases.jsonl results.jsonl --max-usd 1.0
```

The replay expects its clones in `$REPOS/repos/<name>` (see
[replay/README.md](replay/README.md) for the layout, options, cost and faithfulness notes).

## Phase 2 results: running

The full replay is running. Results will be added in a later commit.

# Miner reference

`mine_history.py` finds commits in which maintainers removed duplicated Python functions. It is Phase 1 of the
research program (`docs/research-program.md`): a reference of real duplicates that dry-lint did not propose.

It uses only the standard library (`ast`, `difflib`, `subprocess` to `git`) and Python 3.11+. It does not call any
model.

## Running it

Each stage reads the files the previous stage wrote in `--out`.

```sh
python mine_history.py log    --out OUT --repo CLONE --name litellm --commits 3000   # trees only, no blobs
python mine_history.py fetch  --out OUT --repo CLONE --name litellm --floor-gb 4     # batch-fetch the blobs
python mine_history.py mine   --out OUT --repo CLONE --name litellm --jobs 12        # all candidates, with features
python mine_history.py select --out OUT litellm openhands                            # thresholds -> cases-*.jsonl
python mine_history.py blame  --out OUT --repo CLONE --name litellm                  # introducing commits
python mine_history.py sample --out OUT litellm openhands --n 30 --seed 20261111     # print a sample to read
```

- `CLONE` can be a `--filter=blob:none --no-checkout` partial clone. `log` reads commits and blob ids with
  `git log --raw --no-renames`, which needs only trees, so it fetches nothing.
- `fetch` fetches the blobs that `mine` will read, in batches of 2,000, over `git fetch --stdin`. It checks free
  disk before each batch and stops below `--floor-gb`. The first run fetched about 59,000 blobs for 12,468 LiteLLM and
  OpenHands commits; the LiteLLM `.git` grew from 465 MB to 706 MB and the OpenHands clone is 48 MB. The first 34,000
  blobs took about one minute.
- `mine` reads blobs with `GIT_NO_LAZY_FETCH=1`. A blob that was not fetched is counted (`blob_missing`) and
  skipped; it is never fetched one at a time. It writes `candidates-<name>.jsonl`, `mine-<name>.json` (counters,
  commit range, HEAD) and `missing-<name>.txt`.
- `mine --jobs N` mines commits in N worker processes, in contiguous chunks so each worker's parse cache stays useful.
  The output is identical to a single-process run.
- `select` keeps one B per deleted function, applies the thresholds below, drops repeats, splits off test-file cases,
  adds `case_id` and any introducing commits already blamed, and writes `cases-<name>.jsonl` and `summary.json`. It
  only reads files, so thresholds can be changed and re-applied in seconds.
- `blame` finds the introducing commits (below) and caches them in `blame-<name>.json`, keyed by member revision,
  path and line range, so `select` can be re-run without blaming again.
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
   B (`a_in_b >= 0.5`; a small A replaced by a larger B that covers it). Bodies exclude decorators, signature and
   docstring.

Every new call in a redirected caller is tried as B; `select` keeps only the most similar B for each deleted A
(similarity = max(Jaccard, `a_in_b`)), and only then applies the thresholds.

Case: A at P and B at P. `callers` lists the redirected call sites.

### pair-shrink

1. Function A exists at P and at C, loses at least 5 own lines (difflib on own lines) and loses more than it gains.
2. A at C makes a new call to B, B exists at P and at C, and B is not A.
3. A and B each have at least 3 statements.
4. Similarity of the removed lines to B: at least half of B's identifiers occur in the removed lines
   (`containment >= 0.5`) **and** identifier-set Jaccard of removed lines vs B's body >= 0.2.

Case: A at P and B at P. A's member record carries `removed_lines`; `callers` is A itself.

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

Identifiers are the word tokens of the code (names, attribute names and also words inside string literals, such as
log messages) minus Python keywords and `self`, `cls`, `None`, `True`, `False`, `str`, `int`,
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

### Recorded checks

- `callers_call_b` (pairs): every listed caller, as it stands at C, has a call that resolves to B, **and** B is
  defined at C (in the commit's after-version of its file, or unchanged from P). It is recorded, not a filter.
- `case_id`: `repo[:2] + "-" + sha1(repo + commit + "|".join(member qualnames) + helper qualname)[:8]` (helper
  qualname is empty for pairs).

### Introducing commits

For each member at P, `git blame --porcelain -w -M -C -L start,end P -- path` gives the commit of every line; the
member's `introduced_by` is the commit that owns most lines (`lines` of `total`). The case's `introduced_by` is the
member whose introducing commit has the newest committer time: the later copy. Family helpers are not blamed (they
did not exist at P). A case whose blame fails or times out gets `blame_skipped` with the reason.

Blame in a blob-less clone fetches every blob it reads, one round trip at a time, and `-C` reads every file changed
by each commit the lines come from (not only `.py`). `blame --prefetch` batch-fetches first, skipping binary and
bundled assets (images, fonts, source maps, `dist/`, `*.min.js`, lock files):

- `full`: every version of each blamed file, plus every file changed by those commits (`log --full-diff`);
- `commits` (default): every version of each blamed file; then a blame without `-C` names the commits the lines come
  from, and the files those commits changed are fetched. Origins that only `-C` finds are fetched lazily.

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

`date` is the commit's author date. `code` is the function's own source (decorators included), never a whole file. Line numbers are 1-based and refer to
the member's `rev`.

## Results

### Second run (2026-11-11)

All six repositories mined with the rules above; thresholds unchanged from the first run. Every case has a `case_id`,
and every case was blamed (557 of 557; 2 of 1,335 member blames fell back to `-w -M` after `-C` timed out).

| Repository | Non-merge `.py` commits mined | Range | pair-delete | pair-shrink | family | pairs with `callers_call_b` |
| --- | --- | --- | --- | --- | --- | --- |
| LiteLLM (HEAD `7bcc462`) | all 31,214 | 2023-07-26 .. 2026-11-10 | 19 | 90 | 184 | 109 of 109 |
| OpenHands (HEAD `b759f8a`) | all 3,468 | 2024-03-17 .. 2026-11-11 | 2 | 4 | 14 | 6 of 6 |
| Saleor | all 12,290 | 2013-02-13 .. 2026-11-10 | 12 | 34 | 49 | 46 of 46 |
| Zulip | all 29,154 | 2012-08-28 .. 2026-11-10 | 13 | 36 | 50 | 49 of 49 |
| Prefect | all 9,360 | 2021-07-14 .. 2026-11-09 | 3 | 10 | 14 | 13 of 13 |
| NetBox | all 9,691 | 2016-03-01 .. 2026-11-10 | 1 | 3 | 19 | 4 of 4 |
| **Total** | 95,177 | | 50 | 177 | 330 | 227 of 227 |

Against the research program's bar: 227 pairs (>= 200), 330 families (>= 40), six repositories (>= 4), but only one
repository with 50 or more pairs (LiteLLM 109; Zulip 49, Saleor 46). Every listed history was mined in full, so the
second 50 cannot come from more commits of these repositories under the same rules.

A fixed-seed sample of 20 cases from the four new repositories (`sample --seed 20261112`), read by hand: 18 real, 1
not a duplicate, 1 unclear.

### First run

Newest 9,000 LiteLLM and all 3,468 OpenHands commits: 166 cases. A fixed-seed sample of 30 (`--seed 20261111`) held
26 real consolidations, 3 not duplicates and 1 unclear. Of those 166 `case_id`s, 164 are unchanged in the second run;
the 2 that went are pair-delete cases whose deleted function now keeps a more similar B.

## Known limits

- Files that do not parse under Python 3 (Python 2 code, commits that left a syntax error) are skipped on that side,
  and a function is never called removed or new because its file failed to parse (`parse_failed` in `mine-*.json`;
  3,343 file versions in Zulip, mostly its Python 2 years).

- Calls through instances (`obj.method()`), inherited methods and names imported from outside the repository are not
  resolved, so cases that go through them are missed.
- The similarity measures are identifier sets, not aligned code. They separate "the removed lines were the helper's
  logic" from "the function now calls an unrelated helper", but they do not prove the two were duplicates.
- `git blame -M -C` follows moves inside a file and copies from files changed in the same commit; a copy pasted from a
  file the commit did not touch is attributed to the pasting commit, which is what "later copy" should mean here.
