# Settling recorded usage completes budgets but does not earn adaptive promotion

The initial 550-query normal-estimate screen funds 3,926 baseline versus 4,883 expanded directional occurrences; accepted duplicate rows rise from 81/84 to 82/84, but all expanded sets fit, so this cannot distinguish the ordering policies. The final completion receipt supersedes the early pending frontier: 16/16 core arms complete, one report retained, zero lost, zero new reports, zero newly useful families, zero remaining frontier questions. Core distinct recorded usage is $0.00879094.

Maximum-output reservations can censor a campaign even when actual answers would release money. Candidates should compete for available cost under the actual scheduler, with prior baseline reports protected.

## What was tested

Retain the captured current stack and add candidates with sparse rank ≤50, MiniLM rank ≤10 and at least eight nonblank lines. Keep priority and query fairness; rank by averaged 61/(60+rank), double the two-channel agreement term, divide by estimated cost and 1 plus previously proposed targets of the same structure hash. Compare uniform and cost-only controls. Replay exact answers through normal estimated and native reservation/settlement accounting separately, at .04 per campaign.

Across three historical regressions, individual reservations sum to $0.1627884, while settled replay charges total $0.0461302 across three separate .04 budgets. Summing sequential reservations is not simultaneous spend.

## Recorded comparison

| Completed recipe, four campaigns each | Settled questions | Emitted report occurrences | Added / lost reports | Native settled USD |
|---|---:|---:|---:|---:|
| Fixed | 6 | 1 | 0 / 0 | 0.00271410 |
| Uniform expanded | 18 | 1 | 0 / 0 | 0.00760190 |
| Cost expanded | 18 | 1 | 0 / 0 | 0.00760190 |
| Adaptive expanded | 18 | 1 | 0 / 0 | 0.00760190 |

Each amount sums four independent campaign ledgers. Reusing the same recordings in four arms is not four times the physical provider spend.

## Decision and limits

Keep current policy. Preserve the accounting correction and the completed negative result; do not leave the final report at the earlier “needs answers” milestone.

This is recovery of an existing frozen experiment. No providers, new encoder inference, new mining or new experiments ran during packaging. Source-positive labels, provider answers, retrieval ranks and emitted reports retain their separate meanings. The original report and earlier failures remain in the private archive; this recovery report corrects interpretation without overwriting them.

## Implementation and recorded replay

Recovered entry points: [`compare_returned.py`](implementation/compare_returned.py), [`core_receipt_costs.py`](implementation/core_receipt_costs.py), [`historical_regressions.py`](implementation/historical_regressions.py), [`policy.py`](implementation/policy.py), [`replay_captures.py`](implementation/replay_captures.py), [`replay_completion.py`](implementation/replay_completion.py), [`summarize_completed_core.py`](implementation/summarize_completed_core.py). [Provenance](PROVENANCE.json) binds every original and public implementation SHA256. Explicit evidence-root path substitution, formatting and documented legacy lint exceptions preserve the original algorithm AST; numerical recipes are unchanged. [Frozen recipe and source hashes](recipe.json) identify the input and result files.

From this method directory, with a materialized private evidence tree preserving `jobs/` and `reports/`, and a new output filename:

```bash
python ../replay.py --method adaptive-judge-budget --evidence-root "$EVIDENCE_ROOT" --out "$OUTPUT/adaptive-judge-budget.json"
```

Recompute settled usage and censoring from final recorded events. Full normal/native scheduler replay remains in the recovered original implementation. The replay output declares its exact scope. Aggregating recorded events is not rerunning a scheduler; aggregating saved ranks is not re-extracting source. Matrix replays need NumPy; other shared replay modes use the standard library. Original model-fitting scripts require the frozen scientific runtime, and native scripts require the pinned dry-lint source, rather than whichever product version happens to be installed.

The evidence tree is intentionally required. Obtain authorized access to [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens), then use the exact recovery dataset/commit receipt in [ACCESS.md](../ACCESS.md). An absent dataset receipt or missing artifact is a reproduction gap; hashes alone do not substitute for inputs. The public package contains no private source, rendered private prompts, raw private answers or model weights. Recorded replay consumes existing answers and matrices without provider cost. A fresh source/encoder/judge run is a different experiment: it requires the full pinned inputs, an explicit new output location, and any provider credentials and costs supplied by the adopting repository.

The original full-workflow entry points can require sibling workers, complete source backgrounds, saved arrays, graph caches and byte-exact request recordings. Some original manifests still contain historical absolute locations. The shared replay maps those locations into the caller's explicit evidence root without editing originals. Direct legacy workflow execution requires a portable materialization of those manifests; merely setting an environment variable is not enough. Full-workflow relocation is **not claimed** unless a validation receipt explicitly records it.

For the stronger original scheduler replay, using the frozen runtime and source manifests that already resolve:

```bash
python ../stage_replay.py --method adaptive-judge-budget --evidence-root "$EVIDENCE_ROOT" --out "$OUTPUT/adaptive-judge-budget-staged"
```

This stages writes in a new directory, blocks networking, and preserves the original inputs. It does not fit a new model or obtain new answers.

Recovery verification is recorded in `research/adaptive-judge-budget/validation.json` in [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens) (private; see [ACCESS.md](../ACCESS.md)). Numerical/queue/scheduler reproduction and aggregate-only checks are labeled separately there. Original implementations retain targeted legacy lint exceptions; public wrappers use normal repository lint.
