# Fixed fusion adds complementary positives but loses more under replacement ranking

At four candidates, TF-IDF finds 134/159 accepted positive pair-cases; fixed fusion finds 130/159 (six additions, ten losses); conditional fusion finds 132/159 (seven additions, nine losses). The union of the TF-IDF and fixed-fusion top-four hit sets covers 140/159 positives: six complementary positives beyond sparse alone, when both lists are inspected. This union is not a four-candidate budget-matched result. The bank covers 58 exact backgrounds and 354,936 directional candidates. Only ten positive residual training directions in four components support the learned ranker; the only evaluable held-out positive outside an abstaining fold falls from rank 1 to 146.

Sparse retrieval can miss operations visible to complete-statement embeddings or structural features. This study asks whether combining those signals improves ordering across the broader exact-source development inventory.

## What was tested

The bank retains up to 100 raw and cross-file neighbors per sparse/dense arm, guarded blocks and qualified containment. Fixed fusion adds equal 1/(60+rank) terms. The conditional route admits TF-IDF ≥ .35, prefix ≥ .65, tail ≥ .80, guarded blocks or containment; prefix and tail get one maximum-rank vote. Containment requires eight shared tokens, three call/attribute/key tokens, overlap mass ≥ .75 and cosine ≥ .1. Corrected v2 sorts token accumulation deterministically. Residual fitting uses standardized logistic regression C=.1, repository-lineage holdout and source-component purging; unlabeled candidates never become negatives.

A public settings-writer pair ranks second under sparse retrieval, 423rd in the prefix embedding direction and 15th under fixed fusion. The tail view ranks it second, but the conditional combination reaches only sixth. Retaining a useful signal does not guarantee that the combined ordering retains its success.

## Recorded comparison

| Raw top-four method | Accepted positives | Added / lost pair-cases | Covered source components |
|---|---:|---:|---:|
| TF-IDF | 134/159 | 0 / 0 | 115/121 |
| Fixed RRF60 | 130/159 | 6 / 10 | 112/121 |
| Conditional union | 132/159 | 7 / 9 | 115/121 |

Inspecting both top-four orderings covers **140/159** accepted positive pair-cases (124 shared, six fusion-only, ten sparse-only). The exact v2 union calculation, recorded in `research/complementary-signal-learning/complementarity.json` in [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens) (private; see [ACCESS.md](../ACCESS.md)), binds the frozen outcome input. Extra inspection count, native settled cost and new-report yield are not measured by this set union. The useful complementarity finding survives; the failed claim is that fixed fusion should replace sparse ordering at the same top-four cap.

## Decision and limits

Retain the candidate bank; reject replacement ordering and this under-supported fitted recipe. These are retrieval measurements, not newly useful reports. Original and deterministic-v2 outputs remain distinct.

This is recovery of an existing frozen experiment. No providers, new encoder inference, new mining or new experiments ran during packaging. Source-positive labels, provider answers, retrieval ranks and emitted reports retain their separate meanings. The original report and earlier failures remain in the private archive; this recovery report corrects interpretation without overwriting them.

## Implementation and recorded replay

Recovered entry points: [`bank_loader.py`](implementation/bank_loader.py), [`build_bank.py`](implementation/build_bank.py), [`build_bank_deterministic.py`](implementation/build_bank_deterministic.py), [`fit_residual.py`](implementation/fit_residual.py), [`prepare_residual.py`](implementation/prepare_residual.py), [`summarize_bank.py`](implementation/summarize_bank.py), [`transport_controls_v3.py`](implementation/transport_controls_v3.py). [Provenance](PROVENANCE.json) binds every original and public implementation SHA256. Explicit evidence-root path substitution, formatting and documented legacy lint exceptions preserve the original algorithm AST; numerical recipes are unchanged. [Frozen recipe and source hashes](recipe.json) identify the input and result files.

From this method directory, with a materialized private evidence tree preserving `jobs/` and `reports/`, and a new output filename:

```bash
python ../replay.py --method complementary-signal-learning --evidence-root "$EVIDENCE_ROOT" --out "$OUTPUT/complementary-signal-learning.json"
```

Frozen case-rank aggregation; feature construction and fitted residual predictions are separate original entry points. The replay output declares its exact scope. Aggregating recorded events is not rerunning a scheduler; aggregating saved ranks is not re-extracting source. Matrix replays need NumPy; other shared replay modes use the standard library. Original model-fitting scripts require the frozen scientific runtime, and native scripts require the pinned dry-lint source, rather than whichever product version happens to be installed.

The evidence tree is intentionally required. Obtain authorized access to [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens), then use the exact recovery dataset/commit receipt in [ACCESS.md](../ACCESS.md). An absent dataset receipt or missing artifact is a reproduction gap; hashes alone do not substitute for inputs. The public package contains no private source, rendered private prompts, raw private answers or model weights. Recorded replay consumes existing answers and matrices without provider cost. A fresh source/encoder/judge run is a different experiment: it requires the full pinned inputs, an explicit new output location, and any provider credentials and costs supplied by the adopting repository.

The original full-workflow entry points can require sibling workers, complete source backgrounds, saved arrays, graph caches and byte-exact request recordings. Some original manifests still contain historical absolute locations. The shared replay maps those locations into the caller's explicit evidence root without editing originals. Direct legacy workflow execution requires a portable materialization of those manifests; merely setting an environment variable is not enough. Full-workflow relocation is **not claimed** unless a validation receipt explicitly records it.

Recovery verification is recorded in `research/complementary-signal-learning/validation.json` in [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens) (private; see [ACCESS.md](../ACCESS.md)). Numerical/queue/scheduler reproduction and aggregate-only checks are labeled separately there. Original implementations retain targeted legacy lint exceptions; public wrappers use normal repository lint.
