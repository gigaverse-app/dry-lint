# Phase 2 replay harness

Answers, per reference case: if `dry-lint check --preset balanced` had run on the commit that introduced the later
copy (I), against I's first parent, what happened to the pair? The first loss is one of `never_proposed`,
`judged_no`, `not_funded` or `reported`, plus `judge_failed` and `not_replayable` so that harness failures are never
counted as product losses.

## Files

- `replay.py`: the harness. Input is a cases jsonl with `introduced_by`. Output is one JSON line per case, appended.
  Rerunning it skips case_ids already done; rows with an `error` are retried.
- `introduce.py`: a stand-in for the miner's blame field. It adds `introduced_by` to chosen cases from
  `history/confirm-in-*.jsonl` and joins the Opus label from `confirm-out-*.jsonl`.
- `run-full.sh`: one `replay.py` process per repository, each with its own output file and dollar cap.

The case files and result rows contain third-party source code and are not in this repository.

## Running

`ROOT` is a folder you choose. It holds one partial clone per repository in `ROOT/repos/<name>` (`litellm`,
`openhands`, `saleor`, `zulip`, `prefect`, `netbox`) and, for `introduce.py`, the confirmation files in
`ROOT/history/`. Pass it with `--root`, or set `DRY_LINT_REPLAY_ROOT`; the default is the current directory. The
Python that runs the harness must be able to import `dry_lint` (an environment with dry-lint and its `langchain`
extra installed, or `PYTHONPATH` set to the repository's `src`).

```sh
ROOT=$REPOS            # folder with repos/<name> clones
PY=python              # an environment where dry_lint imports
$PY introduce.py --root $ROOT cases.jsonl op-2c650950 li-2847ffab  # only until the miner's introduced_by lands
$PY replay.py --root $ROOT cases.jsonl detect.jsonl --detect-only   # mapping, candidates, disk, time; $0
$PY replay.py --root $ROOT cases.jsonl results.jsonl --max-usd 1.0  # judged; needs ANTHROPIC_API_KEY
ROOT=$REPOS PY=$PY bash run-full.sh                                 # all six repositories in parallel
```

The Anthropic API key is read from `ANTHROPIC_API_KEY` in the environment. Without it, `replay.py` refuses to run
unless `--detect-only` is given.

Options:
- `--labels yes,partial` is the default; pass `''` for all labels.
- `--only ID,ID` limits the run to those cases.
- `--max-usd` stops before the next case once the output file's total spend reaches it.
- The run also stops when the disk holding `ROOT/repos` has less than 3.3 GB free.

`introduced_by` can be a bare sha or `{"commit", "member", "path_at_commit", "lines_at_commit"}`. With the dict
form, the later member is found at I through its blamed lines. With a bare sha, the later member is the located member
that I changed, and `later_how` records how it was chosen. When several members changed, the first is taken and the
row says "ambiguous". Add `member` to name the later member. On the 6 test cases, bare shas gave the same pair
outcomes as the dict form.

## What a case does (the product path)

This mirrors `cli.check` and `cli.judged` with discovery on. Nothing is checked out; trees are read from git objects.

1. **Settings.** `.dry-lint.toml`, else `[tool.dry-lint]` in `pyproject.toml`, read at I (what `Settings.load` reads
   in a checkout of I). Then `--preset balanced` and `resolve()`. At startup the harness asserts preset `balanced`,
   the langchain judge on Haiku 5.5 at effort low, `report_at` 0.4, and exploration through `tfidf` plus
   `operation-blocks`.
2. **Prefetch.** One batched `git fetch --stdin` gets exactly the blobs the check reads: the product's `tree_blobs`
   predicate, plus both sides of every file in the diff. It runs with `gc.auto=0`, so the shared clone is never
   repacked.
3. **Candidates.** `Detector.for_tree(root, I)`, `touched(..., changed_lines(root, parent, head=I))`,
   `Detector.candidates`, then `.dry-lint-feedback.json` at I if it exists.
4. **Judging.** `Judging.configured(settings, store)` with a new temporary `DirectoryStore` and a new
   `CampaignStore` SQLite ledger, then `judging.findings` and `Report.build`. This is the shipped scheduler: baseline
   first, exploration credit, 50 calls per tree, a 4-worker batch and reservations. The temp folder is deleted
   afterwards.
5. **Members at I.**
   - The later member is the extracted function holding most of its blamed lines.
   - Other members are found by path plus qualname, resolved with `ast` to the `def` line and then to the
     containing extracted function. dry-lint keeps nested functions inside their parent.
   - If that fails, the harness takes the closest code (difflib ratio at least 0.6) among the same file's
     functions and same-named functions elsewhere. This covers renames such as `_is_projected_spend_over_limit`.
6. **Pair outcome.** The target pairs are the later member against each other member. Each outcome comes from the
   candidate list (lane, comparer, rule) and the product's `Finding` (`verdict`, `reported`, `budget_deferred`).
   - `never_proposed` covers three things, with the reason in `why`: no candidate, a candidate settled by a rule,
     and the `relative` lane. Campaign checks never judge relatives.
   - `reported` is the product's own `Finding.reported`. That needs the label not to be `separate` and a score of
     at least 0.4. Any disagreement with the score alone is written to `why`.
   - `not_funded` means `budget_deferred`, from either the dollar budget or a call cap. A deferral for any other
     reason is `judge_failed`.
   - The case outcome is the best outcome over its pairs, in this order: reported > judged_no > not_funded >
     judge_failed > never_proposed > not_replayable.
7. **Recorded per case.**
   - Route: `lane` plus `route`, the comparer id. TF-IDF exploration and operation blocks are both lane
     `exploration`; only `route` tells them apart.
   - Score, label, same-file, and whether each member changed at I.
   - Each member's code similarity between I and the consolidation parent.
   - Counts: changed functions, candidates by lane and route, judged attempts, reports and budget deferrals.
   - Cost and footprint: campaign dollars, seconds, and pack growth in MB from `git count-objects`.
   - Free disk before and after.

## How faithful it is

Identical to the shipped check:
- Code: `src` on current main. The detector, comparers, rules, feedback, the judge plugin and its prompt,
  `Judging.discover`, campaign admission and reservations, `Report.build` and thresholds all run unchanged.
- The judge is the real Anthropic call through the configured langchain judge, with no cached answers.
- Inputs: the source tree at I, the diff against I's first parent, and the target repository's own config at I.

Differs, and what it can bias:
- **Ledger and store are fresh.** This is the first push of a new branch or PR. It gets $0.015 exploration credit,
  50 calls on this tree, and nothing cached.
  - A real PR may have had earlier pushes. Those could already have judged the pair (found earlier) or spent the
    allowance (found less often). Credit accrues up to $0.025 over several trees.
  - LiteLLM and OpenHands squash-merge, so I is usually the whole PR diff, which is what a check on the PR's last
    head sees. Intermediate pushes are not replayed.
  - In real use, verdicts for unchanged pairs would be reused for free. A fresh store spends calls on them, which
    biases slightly toward `not_funded`.
- **The binding limit was the 50 calls per tree, not dollars.** Both judged cases stopped at 50 calls, having
  spent $0.017 and $0.025 of $0.04. Large commits (op-b03ff16c changed 45 functions and had 265 open candidates)
  run out of calls.
- **Blame picks the last big rewrite, not the birth.** For li-41279e73 the majority of the later copy (48%) comes
  from a 2026 fix of a function written in 2024, so I is a modifying commit. In general, majority blame can
  replay a commit where the pair already existed.
- **The pair at I can differ from the pair at the consolidation parent.** In li-9e0855b7 the code similarity is
  0.68, so a `judged_no` there may mean "not a duplicate yet". Read `code_similarity_to_parent` before blaming
  the judge.
- **Not run:**
  - The model-review lane. Its budget is separate and it never touches function pairs.
  - Families, which are off in balanced.
  - The `last-report` write and the commit trailers.
- **One draw per pair.** Judge variance is not measured.
- **Environment.** Python 3.14 and the structured-default venv's langchain-anthropic. That version warns that
  forced tool calling is unsupported on Haiku 5.5. This is the product as installed there; an adopter on another
  langchain version may differ.
- **Campaign identity.** A session instead of a PR number. It only names the ledger key.
- **Disk accounting.** The clones are shared with other agents, so the pack-growth figure can include their
  fetches. Free disk space is dominated by other processes.

## Cost, time and disk observed (6 test cases)

| Case | Outcome | Lane / route | Calls | USD | Seconds |
| --- | --- | --- | ---: | ---: | ---: |
| op-2c650950 | reported | baseline / tfidf | 50 | 0.0169 | 63 |
| op-b03ff16c | not_funded | exploration / tfidf | 50 | 0.0254 | 100 |
| op-09cdf54c | never_proposed | rule: python-special-method | 50 | 0.0213 | 78 |
| li-2847ffab | reported | baseline / tfidf | 4 | 0.0010 | 45 |
| li-41279e73 | reported | exploration / tfidf | 1 | 0.0004 | 26 |
| li-9e0855b7 | reported | exploration / tfidf | 31 | 0.0141 | 63 |

- **Judged run:** $0.0791 in total, about $0.013 and 63 s per case. Pack growth was at most 0.1 MB, because the
  detect-only run had already fetched the blobs.
- **Detect-only:** 8 to 44 s per case. Pack growth was 0.3 to 3.5 MB on a case's first run.
- **`introduce.py`:** 1 s for the 3 OpenHands cases. The 3 LiteLLM cases took 9.6 minutes, and the LiteLLM pack
  grew about 94 MB in that window, on a clone shared with other agents. Lazy fetches during `blame -C` are one
  object at a time.
- **Old rows.** The first two rows were written before `attempts_by_lane` and `caps_hit` existed. 50 calls means
  they hit `calls_per_revision`.
- **Duplicate rows.** A retried case that had an `error` leaves two rows for one `case_id`. The last row wins.
