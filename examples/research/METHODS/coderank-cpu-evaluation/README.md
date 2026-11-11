# CodeRank CPU matrices: the allocated batch is complete, quality remains separate

The setup README is stale: BATCH-STATUS now records complete allocation through all 58 backgrounds, 174 matrix receipts, 151,481 unique source bodies and no recorded batch errors. Elapsed batch time is 49,235.44 seconds and inference time 44,625.00 seconds. These are shared-batch execution measurements, not per-repository sums or retrieval accuracy.

A code-trained encoder with a longer input limit might retain overlaps lost by short prefix embeddings. This study establishes a precise local inference contract and cached matrices for that comparison.

## What was tested

Pin nomic-ai/CodeRankEmbed at 3c4b60807d71f79b43f3c4363786d9493691f8b1. Symmetric code inputs have no prefix. Use reviewed local NomicBert, CLS pooling and FP32 L2 normalization; the selected variant is CPU BF16, SDPA, four threads, canonical singleton input. Limits 1024/2048/4096 include special tokens. Reuse only exact token inputs under the bound model/runtime contract.

A longer cap can reuse a short function’s identical token input. Reusing the whole matrix by cap alone would be wrong when longer functions change; receipts retain exact token/cache identity.

## Recorded comparison

| Recorded scope | Matrices | Unique source bodies | Quality meaning |
|---|---:|---:|---|
| Allocated complete batch, 58 backgrounds | 174 | 151,481 | Inference completion only |
| Recovery replay, one 1K background | 1 | Not an independent sample | 84/84 saved directional ranks reproduced |

## Decision and limits

Preserve both the original setup snapshot and the later completion receipt. Use the completed matrices in matched-background ranking; no model-quality or deployment promotion claim follows from completing the batch.

This is recovery of an existing frozen experiment. No providers, new encoder inference, new mining or new experiments ran during packaging. Source-positive labels, provider answers, retrieval ranks and emitted reports retain their separate meanings. The original report and earlier failures remain in the private archive; this recovery report corrects interpretation without overwriting them.

## Implementation and recorded replay

Recovered entry points: [`batch_runner.py`](implementation/batch_runner.py), [`cache_corpus.py`](implementation/cache_corpus.py), [`coderank_adapter.py`](implementation/coderank_adapter.py), [`cpu_variant.py`](implementation/cpu_variant.py), [`preflight.py`](implementation/preflight.py), [`publish_matrices.py`](implementation/publish_matrices.py). [Provenance](PROVENANCE.json) binds every original and public implementation SHA256. Explicit evidence-root path substitution, formatting and documented legacy lint exceptions preserve the original algorithm AST; numerical recipes are unchanged. [Frozen recipe and source hashes](recipe.json) identify the input and result files.

From this method directory, with a materialized private evidence tree preserving `jobs/` and `reports/`, and a new output filename:

```bash
python ../replay.py --method coderank-cpu-evaluation --evidence-root "$EVIDENCE_ROOT" --out "$OUTPUT/coderank-cpu-evaluation.json" --receipt jobs/coderank-cpu-evaluation/.lab-results/openhands-ebd00315/matrix-1024.json
```

Replay cosine scores/raw ranks from a completed matrix; weights and CPU inference are not invoked. The replay output declares its exact scope. Aggregating recorded events is not rerunning a scheduler; aggregating saved ranks is not re-extracting source. Matrix replays need NumPy; other shared replay modes use the standard library. Original model-fitting scripts require the frozen scientific runtime, and native scripts require the pinned dry-lint source, rather than whichever product version happens to be installed.

The evidence tree is intentionally required. Obtain authorized access to [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens), then use the exact recovery dataset/commit receipt in [ACCESS.md](../ACCESS.md). An absent dataset receipt or missing artifact is a reproduction gap; hashes alone do not substitute for inputs. The public package contains no private source, rendered private prompts, raw private answers or model weights. Recorded replay consumes existing answers and matrices without provider cost. A fresh source/encoder/judge run is a different experiment: it requires the full pinned inputs, an explicit new output location, and any provider credentials and costs supplied by the adopting repository.

The original full-workflow entry points can require sibling workers, complete source backgrounds, saved arrays, graph caches and byte-exact request recordings. Some original manifests still contain historical absolute locations. The shared replay maps those locations into the caller's explicit evidence root without editing originals. Direct legacy workflow execution requires a portable materialization of those manifests; merely setting an environment variable is not enough. Full-workflow relocation is **not claimed** unless a validation receipt explicitly records it.

Recovery verification is recorded in `research/coderank-cpu-evaluation/validation.json` in [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens) (private; see [ACCESS.md](../ACCESS.md)). Numerical/queue/scheduler reproduction and aggregate-only checks are labeled separately there. Original implementations retain targeted legacy lint exceptions; public wrappers use normal repository lint.
