# A seed endpoint is a cheaper inspection order, but finds fewer known siblings

At five reviews per positive-seed scenario, both queues spend 510 review occurrences. Fixed ranking finds 85 positive, 102 negative and 323 unknown occurrences; endpoint-first finds 14, 76 and 420. Recorded source-character burden falls from 1,068,555 to 689,113. At cap 20, whole-queue stopping reaches 35 distinct existing positive pairs versus 43 with continuation.

After a useful pair is found, shared endpoints might make nearby source cheaper to inspect. The experiment tests whether this produces better known-operation coverage than unchanged ranking.

## What was tested

Select one pair per source component by stable hash before revealing its label: 102 positive oracle seeds and 192 intentionally false controls. Compare fixed TF-IDF/MiniLM ordering against seed-endpoint-first ordering. Hide sibling labels until evaluation. Replay bounded continuation, whole-queue stopping and branch-local stopping. Earlier SVM/calibration work is exploratory and is preserved separately after the direction was corrected to spectral/SVD methods.

Stopping after one rejected sibling suppresses later useful branches. Unknown responses can change the stopping trajectory, so these traces do not validate an automatic stopping rule.

## Recorded comparison

| Five-review queue, 102 positive-seed scenarios | Positive occurrences | Negative | Unknown | Source characters |
|---|---:|---:|---:|---:|
| Fixed ranking | 85/510 | 102/510 | 323/510 | 1,068,555 |
| Seed endpoints first | 14/510 | 76/510 | 420/510 | 689,113 |

## Decision and limits

Keep outcome authority and inspection cost separate. Do not infer population precision or deploy endpoint-first ordering. The verified milestone is a single-seed non-model queue replay; spectral partitioning belongs to the separate method.

This is recovery of an existing frozen experiment. No providers, new encoder inference, new mining or new experiments ran during packaging. Source-positive labels, provider answers, retrieval ranks and emitted reports retain their separate meanings. The original report and earlier failures remain in the private archive; this recovery report corrects interpretation without overwriting them.

## Implementation and recorded replay

Recovered entry points: [`analyze.py`](implementation/analyze.py), [`audit_history.py`](implementation/audit_history.py), [`collect_milestone.py`](implementation/collect_milestone.py), [`graph_reference.py`](implementation/graph_reference.py), [`ingest_seeds.py`](implementation/ingest_seeds.py), [`one_seed.py`](implementation/one_seed.py), [`prepare.py`](implementation/prepare.py). [Provenance](PROVENANCE.json) binds every original and public implementation SHA256. Explicit evidence-root path substitution, formatting and documented legacy lint exceptions preserve the original algorithm AST; numerical recipes are unchanged. [Frozen recipe and source hashes](recipe.json) identify the input and result files.

From this method directory, with a materialized private evidence tree preserving `jobs/` and `reports/`, and a new output filename:

```bash
python ../replay.py --method cluster-calibration --evidence-root "$EVIDENCE_ROOT" --out "$OUTPUT/cluster-calibration.json"
```

Recompute actual queue order and all frozen stopping decisions from recorded labels; does not fit the exploratory models. The replay output declares its exact scope. Aggregating recorded events is not rerunning a scheduler; aggregating saved ranks is not re-extracting source. Matrix replays need NumPy; other shared replay modes use the standard library. Original model-fitting scripts require the frozen scientific runtime, and native scripts require the pinned dry-lint source, rather than whichever product version happens to be installed.

The evidence tree is intentionally required. Obtain authorized access to [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens), then use the exact recovery dataset/commit receipt in [ACCESS.md](../ACCESS.md). An absent dataset receipt or missing artifact is a reproduction gap; hashes alone do not substitute for inputs. The public package contains no private source, rendered private prompts, raw private answers or model weights. Recorded replay consumes existing answers and matrices without provider cost. A fresh source/encoder/judge run is a different experiment: it requires the full pinned inputs, an explicit new output location, and any provider credentials and costs supplied by the adopting repository.

The original full-workflow entry points can require sibling workers, complete source backgrounds, saved arrays, graph caches and byte-exact request recordings. Some original manifests still contain historical absolute locations. The shared replay maps those locations into the caller's explicit evidence root without editing originals. Direct legacy workflow execution requires a portable materialization of those manifests; merely setting an environment variable is not enough. Full-workflow relocation is **not claimed** unless a validation receipt explicitly records it.

Recovery verification is recorded in `research/cluster-calibration/validation.json` in [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens) (private; see [ACCESS.md](../ACCESS.md)). Numerical/queue/scheduler reproduction and aggregate-only checks are labeled separately there. Original implementations retain targeted legacy lint exceptions; public wrappers use normal repository lint.
