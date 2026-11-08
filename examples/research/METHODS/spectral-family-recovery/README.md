# Sparse spectral cuts reduce a small frontier without added known recovery

On the selected oracle baseline, known sibling recovery remains 1/2 while leads fall from 438 to 418 and known negatives from two to zero. Thirty-two complete queues differ, but selected top-ten useful counts and source burden do not improve over cheap operation ranking. Fixed SVD controls yield no known useful sibling gain.

Graph expansion can mix operations and generic hubs. Low-conductance partitions might focus inspection, but a function can contain more than one operation and must not be assigned a single semantic truth.

## What was tested

Build mutual, union, tighter-threshold and hub-removed sparse affinity graphs. Use normalized-Laplacian Fiedler sweeps, minimum side size three, maximum recursion depth four, conductance ≤ .20, and ≥ .90 agreement under deterministic ±5% edge perturbation. Preserve native leads. Overlapping groups require common bounded-region signatures. Separate fixed SVD/ridge/residual controls test whether low-rank projection removes noise.

The retained synthetic control has pagination, retry and one mixed function containing both. A hard partition loses an overlapping member; operation-signature membership retains it in both groups. This is a mechanism check, not evidence of real graph accuracy.

## Recorded comparison

| Oracle baseline, 21 scenarios, full frontier | Known sibling recovery | Leads | Known negatives | Unknowns | Source-token proxy |
|---|---:|---:|---:|---:|---:|
| Bounded diffusion | 1/2 | 438 | 2 | 435 | 90,897 |
| Mutual spectral region | 1/2 | 418 | 0 | 417 | 86,830 |

## Decision and limits

Do not ship or tune from this saturated/unknown smoke. Preserve overlapping membership and prohibit hard suppression. The negative conclusion concerns these fixed controls, not spectral methods generally.

This is recovery of an existing frozen experiment. No providers, new encoder inference, new mining or new experiments ran during packaging. Source-positive labels, provider answers, retrieval ranks and emitted reports retain their separate meanings. The original report and earlier failures remain in the private archive; this recovery report corrects interpretation without overwriting them.

## Implementation and recorded replay

Recovered entry points: [`continue.py`](implementation/continue.py), [`freeze.py`](implementation/freeze.py), [`prepare_svd.py`](implementation/prepare_svd.py), [`spectral.py`](implementation/spectral.py), [`svd_control.py`](implementation/svd_control.py), [`validate_native.py`](implementation/validate_native.py). [Provenance](PROVENANCE.json) binds every original and public implementation SHA256. Explicit evidence-root path substitution, formatting and documented legacy lint exceptions preserve the original algorithm AST; numerical recipes are unchanged. [Frozen recipe and source hashes](recipe.json) identify the input and result files.

From this method directory, with a materialized private evidence tree preserving `jobs/` and `reports/`, and a new output filename:

```bash
python ../replay.py --method spectral-family-recovery --evidence-root "$EVIDENCE_ROOT" --out "$OUTPUT/spectral-family-recovery.json"
```

Aggregate frozen per-seed real-data measurements; the additional toy command executes the original graph-cut implementation. The replay output declares its exact scope. Aggregating recorded events is not rerunning a scheduler; aggregating saved ranks is not re-extracting source. Matrix replays need NumPy; other shared replay modes use the standard library. Original model-fitting scripts require the frozen scientific runtime, and native scripts require the pinned dry-lint source, rather than whichever product version happens to be installed.

The evidence tree is intentionally required. Obtain authorized access to [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens), then use the exact recovery dataset/commit receipt in [ACCESS.md](../ACCESS.md). An absent dataset receipt or missing artifact is a reproduction gap; hashes alone do not substitute for inputs. The public package contains no private source, rendered private prompts, raw private answers or model weights. Recorded replay consumes existing answers and matrices without provider cost. A fresh source/encoder/judge run is a different experiment: it requires the full pinned inputs, an explicit new output location, and any provider credentials and costs supplied by the adopting repository.

The original full-workflow entry points can require sibling workers, complete source backgrounds, saved arrays, graph caches and byte-exact request recordings. Some original manifests still contain historical absolute locations. The shared replay maps those locations into the caller's explicit evidence root without editing originals. Direct legacy workflow execution requires a portable materialization of those manifests; merely setting an environment variable is not enough. Full-workflow relocation is **not claimed** unless a validation receipt explicitly records it.

The original synthetic mechanism control is fully public and needs only NumPy and SciPy:

```bash
python replay_toy.py --out "$OUTPUT/spectral-toy"
```

It recomputes sparse cuts, mixed-function membership and the generic-clique control and compares every recorded field except elapsed time. It is not a real-source recall experiment.

Recovery verification is recorded in [validation.json](validation.json). Numerical/queue/scheduler reproduction and aggregate-only checks are labeled separately there. Original implementations retain targeted legacy lint exceptions; public wrappers use normal repository lint.
