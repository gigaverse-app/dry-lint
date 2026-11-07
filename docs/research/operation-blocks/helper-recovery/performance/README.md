# Faster preparation, identical operation-block results

The helper fallback adds useful retrieval, but it used to tokenize overlapping statements repeatedly and prepare an unindexed changed function again for the fallback. Sharing exact ordered statement preparation and retaining one query's prepared regions reduces cold index construction by **16–21%** and standalone query time by **22–38%** in these paired measurements. It changes neither the method nor its measured precision tradeoff.

For example, setup statements inside a helper can occur in a candidate region and again in its complete-helper fallback. The optimized code prepares those statement tokens once within the function. It rejects spans already known to exceed limits before tokenization, caps the behavior-node count at 401 for the unchanged 400-node limit, and caches at most one standalone query's original/fallback regions. Reindexing or changed source replaces that cache. No AST or native Function is retained by the query cache. The [safety argument](SAFETY-ARGUMENT.txt) records why order, weights, boundaries and eligibility are preserved.

| Background | Documents | Cold index, seconds | Indexed warm 1,000 queries, seconds | Standalone 1,000 queries, seconds |
| --- | ---: | ---: | ---: | ---: |
| LiteLLM | 37,604 | 43.52 → 36.02 | 5.07 → 4.95 | 9.04 → 7.09 |
| OpenHands SDK | 2,348 | 2.60 → 2.06 | 1.56 → 1.46 | 4.64 → 2.90 |
| Private Python application | 9,907 | 12.52 → 10.52 | 4.81 → 4.86 | 9.87 → 7.42 |

Numbers are medians of three paired repetitions, not best runs. Warm indexed results are mixed. LiteLLM query RSS fell from about 1,020 to 991 MiB; peak RSS stayed about 1,032 MiB because loading dominated it. These are shared-host Python 3.14.4 measurements, not isolated hardware benchmarks. [metrics.json](metrics.json) includes the actual repetitions, standalone protocol and bounded-cache measurements. No provider was called.

Exact parity covered 24,135 recorded queries over ten backgrounds, 197,731 region representations, both posting maps, native object identity, candidate order, hexadecimal floating-point scores and shared evidence. This includes 536 labeled directional rows and 211 query identities within backgrounds, not 536 independent examples. Another 103 verified edits insert an executable statement *inside* the parsed function and also match. Earlier 274 source-text probes included some method edits outside the body; they are not counted as those 103 executable edits.

## Reproduce

[bench.py](bench.py) is the actual cold/indexed-query benchmark. [parity.py](parity.py) compares the fitted representations and all recorded queries, and times standalone queries with alternating equally warmed indexes. [novel_edits.py](novel_edits.py) validates executable edits after parity. Formatting/import cleanup and immediately bound query predicates are the only publication changes; [origin.json](origin.json) identifies original scripts. Source is the optimized implementation in [PR109](https://github.com/gigaverse-app/dry-lint/pull/109); baseline is commit `5583bb1d3ad8deb22ab45642782988f6deae79e3`.

The full frozen input files are kept in the separate lab corpus, **not included in this PR**. [inputs.json](inputs.json) gives public repository pins, scopes, exact background/native-index/query-selection hashes, sizes and lab paths. Obtain those files before running the full experiment. The hashes alone are not a reproducer; regenerating from a repository with a different selection creates a different benchmark. Private application source is not redistributed.

Use a scratch copy of this directory so that outputs do not modify the published evidence. Put the baseline package under `before-src/dry_lint`, the PR109 package under `src/dry_lint`, and the four files for each selected public background under `inputs/<background-id>/`. Use an environment installed from PR109's lockfile. Then, from that scratch directory:

```bash
export PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python bench.py --arm before --cohort bg-ebd0031534c954e5 --label r1
python bench.py --arm after --cohort bg-ebd0031534c954e5 --label r1
python bench.py --arm after --cohort bg-ebd0031534c954e5 --label r2
python bench.py --arm before --cohort bg-ebd0031534c954e5 --label r2
python bench.py --arm before --cohort bg-ebd0031534c954e5 --label r3
python bench.py --arm after --cohort bg-ebd0031534c954e5 --label r3
python parity.py --cohort bg-ebd0031534c954e5
python novel_edits.py
```

`novel_edits.py` uses the three original timed cohort IDs; to run it unchanged provide all three corresponding parity outputs and inputs, including the private background. A public-only executable-edit run can use the `run("bg-ebd0031534c954e5")` entry point instead; that is a subset of the 103-edit result. Repeat benchmark/parity commands with `bg-7489aa1946c16153` for LiteLLM. Run timing and parity phases sequentially, not concurrently. `--profile` records separate cProfile runs; those are not the timing samples.

The formatted publication benchmark was run again on OpenHands and reproduced the exact 1,000-query output hash `440db98adf9eda6316179d4429abf8b0e34590cf532ebe8539fa08fdefbe5fb1`. Timing naturally differs between runs. Product regression tests are self-contained: `uv run pytest -q tests/test_operation_blocks.py tests/test_operation_blocks_preparation.py`. They do not recreate the full-corpus benchmark.

**Decision:** include the optimization in PR109. Keep operation-block recovery opt-in because its additional reports still carry the usefulness and budget tradeoffs documented in the [parent study](../README.md). Faster execution is not evidence of higher recall.
