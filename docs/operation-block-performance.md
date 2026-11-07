# Faster operation-block indexing with the same candidates

The complete-helper route recovers useful operations, but preparing overlapping syntax regions repeats work.
The optimization in PR109 shares statement preparation and keeps one prepared standalone query. It reduces
cold indexing by **16–21%** on the three measured backgrounds without changing retrieval scores or winners.
This is a runtime improvement; it adds no new recall claim.

## What changed

Suppose a helper contains setup statements, a `try` block and a return. The original index tokenizes those
statements for individual regions and again for the complete helper. It also prepares a changed function again
when trying the fallback route. The optimized code:

- Rejects oversized spans and duplicate helper boundaries before walking and tokenizing them.
- Counts at most 401 behavior nodes per statement: anything above the existing 400-node limit is ineligible.
- Reuses each statement's exact ordered token list within that function's preparation.
- Keeps one standalone source's prepared original and fallback regions, with independent retained anchors.

The cache is replaced on source changes and cleared on reindexing. It retains no AST or Function object.
Whole-function query tokens are still read afresh. Region limits, floors, corpus frequencies, callback order,
original-route priority, native function identities and floating-point summation order are unchanged.
The comparer identity remains `operation-blocks:2`.

## Paired measurements

Each value is the median of three paired runs. Query batches contain 1,000 deterministic queries.

| Background | Indexed documents | Cold construction, seconds | Indexed warm queries, seconds | Standalone queries, seconds |
| --- | ---: | ---: | ---: | ---: |
| LiteLLM | 37,604 | 43.52 → 36.02 | 5.07 → 4.95 | 9.04 → 7.09 |
| OpenHands SDK | 2,348 | 2.60 → 2.06 | 1.56 → 1.46 | 4.64 → 2.90 |
| Private Python application | 9,907 | 12.52 → 10.52 | 4.81 → 4.86 | 9.87 → 7.42 |

Standalone queries use fresh Function objects, as changed source outside the indexed snapshot would. They
improved by 22–38%. Indexed warm results are mixed, so there is no general warm-query speedup claim.
LiteLLM resident memory after queries fell from about 1,020 to 991 MiB; peak memory remained about 1,032 MiB
because loading the input dominated the peak.

Measurements used Python 3.14.4 on the shared Linux lab host. Construction runs used fresh processes and
alternating arm order; input loading was excluded. Standalone runs alternated equally warmed indexes in one
process. Other workloads were active, so these are paired engineering measurements, not isolated hardware
benchmarks. [Machine-readable measurements](assets/operation-block-performance.json) retain the repetitions.

## Correctness and reproduction

Exact comparison covered 24,135 recorded queries across ten backgrounds, including 536 labeled directional
rows and 211 distinct query identities within their backgrounds. All 197,731 region representations and both
posting maps matched. Returned candidate order, native object identity, hexadecimal float scores and shared
evidence matched. A further 103 executable source edits also matched. These are implementation-regression
checks; correlated queries and edits are not independent accuracy examples.

The source change and regression tests are in this PR. From the checkout:

```bash
uv run pytest -q tests/test_operation_blocks.py tests/test_operation_blocks_preparation.py
```

The [operation-block study](https://github.com/gigaverse-app/dry-lint/pull/115) contains the performance harness,
input identities, recorded runs and exact benchmark commands. Repeating the full timing/parity experiment
requires those frozen backgrounds, native function indexes and query selections; the unit-test command above
does not recreate it. Private background source is not distributed with the product.

Keep the route opt-in as described in [the method guide](operation-blocks.md). Faster preparation does not
remove its measured precision tradeoff or protect exploration candidates from budget displacement.
