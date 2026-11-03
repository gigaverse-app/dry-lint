# Cross-repository TypeScript probe, 2026-11-03

Use contextual judging in warning-only mode for the initial rollout. It fixes the five observed form/provider
false positives while preserving most useful matches, but it still needs a reviewer. These results do not
replace the independent Python benchmark in [benchmark.md](benchmark.md).

## Frozen-pair judge comparison

Both arms used `jev-1.14.0`, the same 44 function pairs, exact source commits and verified body hashes, four
workers, and the same reporting threshold (0.8). The sample contains 10 labelled consolidation candidates,
25 labelled negatives and 9 borderline cases. It was selected diagnostically from real web/mobile/common
retrieval results and reviewed by one agent, then used to refine the context prompt. It is a calibration set,
not an independent test set or a population precision estimate. Borderline cases are excluded from TP/FP counts.

| Measurement | Function-only `reuse-v2` | Contextual `reuse-context-v3` |
| --- | ---: | ---: |
| Useful matches retained / 10 | 9 | 8 |
| False positives / 25 | 18 | 7 |
| Known form/provider false positives / 5 | 5 | 0 |
| API input tokens, 44 requests | 39,015 | 74,043 |
| Judge batch wall time | 1.19 s | 1.38 s |
| Estimated model charge | $0.00164 | $0.00311 |

The five regression cases comprise a form wrapper closing over different schemas and four accessors tied to
separate SDK/provider contexts. Bounded imports, local declarations and policy comments make that evidence
available to the judge. No function names or repository-specific exceptions are hardcoded in the library.

Seven negative cases still report: a constructor, a trivial SDK selector, a persistence projection, a single SDK
enum comparison, unrelated truncation contracts, sorting versus timestamp projection, and different view-model
adapters. Two positives are missed: a mutation/invalidation wrapper and an SDK-to-logger mapping. Some negatives
are low-value extraction suggestions rather than different semantics. The current judge does not reliably
distinguish those; grouping whole families and richer caller/import resolution remain useful future work.

The initial context prompt suppressed every positive and was rejected. Version 2 retained seven positives and
was also rejected. Version 3 separates duplication confidence from uncertainty over ownership, then suppresses
probable explicit separation or non-reuse reasons. The unchanged acceptance gate requires all five regressions
to clear, at least eight positives to remain, and fewer false positives than the baseline. Model outputs vary:
earlier baseline runs retained 10/10, while the paired run above retained 9/10. Keep rerunning the frozen probe
when changing the prompt/model, and obtain independent labels before claiming broader precision or blocking CI.

## Retrieval and review budget

An offline comparison using the same three checkout source trees and exclusions selected 30 proposals:

| Shared-library proposals | Global nearest/similarity order | Per-peer retrieval + destination/family ranking |
| --- | ---: | ---: |
| First 20 | 0 | 14 |
| First 30 | 0 | 24 |

The new run indexed 9,053 functions and completed in about 38 seconds on the local Windows machine. This is
source discovery time, not model time. Reciprocal matches are now computed separately for each repository pair;
ranking gives repository pairs and file families turns instead of letting app-to-app clones fill every slot.
These counts measure exposure of shared-library candidates, not the correctness of those candidates.

At the observed mean context request size, 30 uncached judgments cost approximately $0.00212 in model charges,
or $2.12 per 1,000 such runs. That is an extrapolation, not a bill or a hard monetary cap. Request sizes vary,
and runner time, checkout/setup, optional escalation and subsequent runs cost extra. TypeSafe currently charges
$0.042 per million input tokens with output tokens free; checked on 2026-11-03 against its
[model pricing](https://docs.typesafe.ai/models). The configuration limits primary requests to 30 and explicitly
reports deferred work. Reuse the verdict store and keep the weekly backlog audit bounded.

## Reproduce

`scripts/probe_context.py` accepts a JSON array of reviewed cases. Each case supplies `id`, `label` (`duplicate`,
`separate` or `borderline`), `regression`, `similarity`, and `new`/`existing` sides. Each side supplies
`repository`, `revision`, `path`, `name`, `owner` and the SHA-256 `code_hash` of the extractor's function body.
The script reads the exact revisions with `git show`, checks body hashes, adds context, and calls both judges:

```bash
python scripts/probe_context.py --cases reviewed-pairs.json --root ../mobile \
  --repo org/web=../web --repo org/mobile=../mobile --repo org/common=../common \
  --output /tmp/context-probe
```

Set `TYPESAFE_AI_API_KEY` in the process environment. `--prepare-only` validates the snapshots without model
calls. The output contains private source text and raw model answers; keep it in the source repositories'
private artifacts. Each arm is saved before starting the next, so a later failure preserves useful evidence.
The three-repository adoption keeps its reviewed cases and live workflow in the private mobile repository.
