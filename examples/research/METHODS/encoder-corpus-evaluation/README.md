# Exact-background encoder comparison infrastructure, with bounded coverage claims

The setup verifies 79 backgrounds with 747,115 document occurrences and 158,657 distinct bodies. Of 826 rows, 822 are function rows and 816 map; 593 accepted function rows map. An independent saved audit agrees on 424 directional scores/ranks with zero mismatches. This is not an encoder quality conclusion, and raw matrix availability does not establish reviewed report utility.

Comparing encoders on different source scopes or incomplete background matrices can invent recall gains. This harness binds complete source order, revisions, labels and matrices before ranking or native funding.

## What was tested

Raw full-background cosine ranks exclude self, use deterministic source-identity ties and apply no inherited similarity floor. Retain both directions and cross-file/language eligibility separately. Native comparison uses the pinned product stack, RRF60 priority, and .04 funding. Receipts bind actual query/document matrix hashes, source hashes and background hash; missing matrices leave comparisons pending.

Two revisions of the same public repository are separate backgrounds. A one-pair pilot at one revision cannot stand in for complete-corpus ranking or a later revision’s results.

## Recorded comparison

| Verification unit | Covered | Unavailable / separate |
|---|---:|---|
| Full backgrounds in setup | 79/79 | Later encoder completion is a separate receipt |
| Function rows mapped | 816/822 | Six unmapped function rows |
| Original independent rank audit | 424/424 directional scores/ranks | Not all later matrices |
| Recovery replay of selected completed matrix | 84/84 directional ranks | Other matrices not rerun during recovery |

## Decision and limits

Retain the reusable rank/native harness and exact coverage. Preserve corrected host-status receipts and failures. Do not represent incomplete source review or live watcher progress as a completed accuracy study.

This is recovery of an existing frozen experiment. No providers, new encoder inference, new mining or new experiments ran during packaging. Source-positive labels, provider answers, retrieval ranks and emitted reports retain their separate meanings. The original report and earlier failures remain in the private archive; this recovery report corrects interpretation without overwriting them.

## Implementation and recorded replay

Recovered entry points: [`build_panel.py`](implementation/build_panel.py), [`common.py`](implementation/common.py), [`native_harness.py`](implementation/native_harness.py), [`rank_harness.py`](implementation/rank_harness.py), [`tail_cache.py`](implementation/tail_cache.py). [Provenance](PROVENANCE.json) binds every original and public implementation SHA256. Explicit evidence-root path substitution, formatting and documented legacy lint exceptions preserve the original algorithm AST; numerical recipes are unchanged. [Frozen recipe and source hashes](recipe.json) identify the input and result files.

From this method directory, with a materialized private evidence tree preserving `jobs/` and `reports/`, and a new output filename:

```bash
python ../replay.py --method encoder-corpus-evaluation --evidence-root "$EVIDENCE_ROOT" --out "$OUTPUT/encoder-corpus-evaluation.json" --receipt jobs/coderank-cpu-evaluation/.lab-results/openhands-ebd00315/matrix-1024.json
```

Recompute scores and exact raw ranks from one explicitly selected completed cached matrix; no encoder inference or paid judging. The replay output declares its exact scope. Aggregating recorded events is not rerunning a scheduler; aggregating saved ranks is not re-extracting source. Matrix replays need NumPy; other shared replay modes use the standard library. Original model-fitting scripts require the frozen scientific runtime, and native scripts require the pinned dry-lint source, rather than whichever product version happens to be installed.

The evidence tree is intentionally required. Obtain authorized access to [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens), then use the exact recovery dataset/commit receipt in [ACCESS.md](../ACCESS.md). An absent dataset receipt or missing artifact is a reproduction gap; hashes alone do not substitute for inputs. The public package contains no private source, rendered private prompts, raw private answers or model weights. Recorded replay consumes existing answers and matrices without provider cost. A fresh source/encoder/judge run is a different experiment: it requires the full pinned inputs, an explicit new output location, and any provider credentials and costs supplied by the adopting repository.

The original full-workflow entry points can require sibling workers, complete source backgrounds, saved arrays, graph caches and byte-exact request recordings. Some original manifests still contain historical absolute locations. The shared replay maps those locations into the caller's explicit evidence root without editing originals. Direct legacy workflow execution requires a portable materialization of those manifests; merely setting an environment variable is not enough. Full-workflow relocation is **not claimed** unless a validation receipt explicitly records it.

Recovery verification is recorded in [validation.json](validation.json). Numerical/queue/scheduler reproduction and aggregate-only checks are labeled separately there. Original implementations retain targeted legacy lint exceptions; public wrappers use normal repository lint.
