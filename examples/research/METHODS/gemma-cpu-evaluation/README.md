# EmbeddingGemma CPU preflight and completed matrices, with the archive still running

The 108-function stratified FP32 sample takes 269.48 seconds at 1K. On the fixed 12-function numerical panel, BF16/four threads takes 11.759 seconds versus 30.286 FP32, with minimum cosine .999901 and unchanged top-one/top-three sets. Six complete OpenHands matrices cover 2,348 and 2,349 rows at three limits. The broader archive remains in progress at recovery time; no total-completion claim is made.

Longer native context could expose source omitted by prefix and tail views. The experiment first verifies numerical behavior and CPU costs before any retrieval-quality claim.

## What was tested

Pin google/embeddinggemma-2 at f9972ac22e696a105c482202646979e33e4b5a1e. Use text-only towers, the symmetric sentence-similarity prefix, projected last-hidden-state mean pooling over nonpadding tokens and FP32 normalization. The selected CPU variant uses BF16/four threads. Limits include native BOS/EOS; cache identity binds actual token IDs, masks, model, runtime, precision and pooling.

For the two-background union, increasing 1K to 2K reuses 2,297/2,309 inputs; 4K reuses 2,306/2,309. Each arm’s shared union time must not be counted separately for both matrices. Numerical parity on twelve selected functions is not full-background ranking parity.

## Recorded comparison

| Fixed 12-function numerical panel | Inference seconds | Minimum cosine to FP32 | Top-1 / top-3 sets unchanged |
|---|---:|---:|---:|
| FP32, two threads | 30.286 | 1.0 | 12/12; 12/12 |
| BF16, four threads | 11.759 | 0.999901 | 12/12; 12/12 |

Recovery recomputes 84/84 directional ranks for one completed 2,348-row 1K matrix. The six completed OpenHands matrices and the running broader archive are distinct coverage units.

## Decision and limits

Preserve verified completed matrices and the exact contract. Keep throughput, truncation, numerical drift and recall separate. This recovery neither restarts nor changes the active archive encoder.

This is recovery of an existing frozen experiment. No providers, new encoder inference, new mining or new experiments ran during packaging. Source-positive labels, provider answers, retrieval ranks and emitted reports retain their separate meanings. The original report and earlier failures remain in the private archive; this recovery report corrects interpretation without overwriting them.

## Implementation and recorded replay

Recovered entry points: [`archive_runner.py`](implementation/archive_runner.py), [`full_openhands.py`](implementation/full_openhands.py), [`gemma_adapter.py`](implementation/gemma_adapter.py), [`gemma_batch_adapter.py`](implementation/gemma_batch_adapter.py), [`gemma_variants.py`](implementation/gemma_variants.py), [`throughput.py`](implementation/throughput.py). [Provenance](PROVENANCE.json) binds every original and public implementation SHA256. Explicit evidence-root path substitution, formatting and documented legacy lint exceptions preserve the original algorithm AST; numerical recipes are unchanged. [Frozen recipe and source hashes](recipe.json) identify the input and result files.

From this method directory, with a materialized private evidence tree preserving `jobs/` and `reports/`, and a new output filename:

```bash
python ../replay.py --method gemma-cpu-evaluation --evidence-root "$EVIDENCE_ROOT" --out "$OUTPUT/gemma-cpu-evaluation.json" --receipt jobs/gemma-cpu-evaluation/.lab-results/openhands/bfloat16-t4/bg-ebd0031534c954e5/receipt-1024.json
```

Replay a completed cached matrix only; no inference and no reading an incomplete matrix. The replay output declares its exact scope. Aggregating recorded events is not rerunning a scheduler; aggregating saved ranks is not re-extracting source. Matrix replays need NumPy; other shared replay modes use the standard library. Original model-fitting scripts require the frozen scientific runtime, and native scripts require the pinned dry-lint source, rather than whichever product version happens to be installed.

The evidence tree is intentionally required. Obtain authorized access to [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens), then use the exact recovery dataset/commit receipt in [ACCESS.md](../ACCESS.md). An absent dataset receipt or missing artifact is a reproduction gap; hashes alone do not substitute for inputs. The public package contains no private source, rendered private prompts, raw private answers or model weights. Recorded replay consumes existing answers and matrices without provider cost. A fresh source/encoder/judge run is a different experiment: it requires the full pinned inputs, an explicit new output location, and any provider credentials and costs supplied by the adopting repository.

The original full-workflow entry points can require sibling workers, complete source backgrounds, saved arrays, graph caches and byte-exact request recordings. Some original manifests still contain historical absolute locations. The shared replay maps those locations into the caller's explicit evidence root without editing originals. Direct legacy workflow execution requires a portable materialization of those manifests; merely setting an environment variable is not enough. Full-workflow relocation is **not claimed** unless a validation receipt explicitly records it.

Recovery verification is recorded in `research/gemma-cpu-evaluation/validation.json` in [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens) (private; see [ACCESS.md](../ACCESS.md)). Numerical/queue/scheduler reproduction and aggregate-only checks are labeled separately there. Original implementations retain targeted legacy lint exceptions; public wrappers use normal repository lint.
