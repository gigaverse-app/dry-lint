# Learned allocation preserves the original prefix but misses its new-family bar

Eight core arms finish allocation; seven have complete outcomes. Learned arms report 37 pairs versus 40 in deeper raw, with five added report pairs and eight displaced relative to deeper raw. All 23 original raw-prefix report flags remain. Learned core usage totals $0.1499895 versus deeper raw $0.1503886 across four distinct campaigns each. One paid unknown affects two arm occurrences and was charged once physically.

Fixed extra slots ignore candidate cost and evidence diversity. This study fits and freezes an allocation policy, then tests whether it improves useful discovery after a protected raw prefix.

## What was tested

Use held-repository/lineage models and frozen candidate feature matrices, preserving explicit source-component isolation. Compare raw-prefix-plus-deeper-raw against raw-prefix-plus-learned ordering under .04 native budgets. Keep normal estimated allocation separate from settled native allocation. Dynamic residual updates use exact recorded answers; failures remain unknown and are not retried.

The learned additions all occur in one repository; another repository’s learned report sets are subsets of deeper raw. These four campaigns therefore cannot establish the original requirement of new useful families in two repositories. Added member/owner utility requires the separate source-review join.

## Recorded comparison

| Four campaigns per core arm | Complete outcomes | Report occurrences | Settled native USD | Paid failed occurrences |
|---|---:|---:|---:|---:|
| Raw prefix + deeper raw | 3/4 | 40 | 0.1503886 | 1 |
| Raw prefix + learned | 4/4 | 37 | 0.1499895 | 0 |

Relative to deeper raw, learned has five reported additions and eight displacements. All 23 original raw-prefix report flags remain. Report counts do not establish useful-family novelty.

## Decision and limits

Do not promote the frozen recipe under its original new-family bar. Preserve offline efficiency and raw-prefix protection without asserting that learned combinations generally fail. Worker FINAL-CLAIMS leaves family review pending; root/corpus reviews must supply later authority.

This is recovery of an existing frozen experiment. No providers, new encoder inference, new mining or new experiments ran during packaging. Source-positive labels, provider answers, retrieval ranks and emitted reports retain their separate meanings. The original report and earlier failures remain in the private archive; this recovery report corrects interpretation without overwriting them.

## Implementation and recorded replay

Recovered entry points: [`allocate_policy.py`](implementation/allocate_policy.py), [`complete_subset.py`](implementation/complete_subset.py), [`dynamic_residual.py`](implementation/dynamic_residual.py), [`fit_policy.py`](implementation/fit_policy.py), [`freeze_campaign.py`](implementation/freeze_campaign.py), [`guard_policy.py`](implementation/guard_policy.py), [`policy_common.py`](implementation/policy_common.py), [`prepare_policy.py`](implementation/prepare_policy.py), [`replay_campaigns.py`](implementation/replay_campaigns.py), [`reproduce_policy.py`](implementation/reproduce_policy.py), [`source_only.py`](implementation/source_only.py). [Provenance](PROVENANCE.json) binds every original and public implementation SHA256. Explicit evidence-root path substitution, formatting and documented legacy lint exceptions preserve the original algorithm AST; numerical recipes are unchanged. [Frozen recipe and source hashes](recipe.json) identify the input and result files.

From this method directory, with a materialized private evidence tree preserving `jobs/` and `reports/`, and a new output filename:

```bash
python ../replay.py --method learned-budget-policy --evidence-root "$EVIDENCE_ROOT" --out "$OUTPUT/learned-budget-policy.json"
```

Recorded native-event aggregation; the supplied staged command additionally recomputes cached-model predictions and exact frozen allocation orders. The replay output declares its exact scope. Aggregating recorded events is not rerunning a scheduler; aggregating saved ranks is not re-extracting source. Matrix replays need NumPy; other shared replay modes use the standard library. Original model-fitting scripts require the frozen scientific runtime, and native scripts require the pinned dry-lint source, rather than whichever product version happens to be installed.

The evidence tree is intentionally required. Obtain authorized access to [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens), then use the exact recovery dataset/commit receipt in [ACCESS.md](../ACCESS.md). An absent dataset receipt or missing artifact is a reproduction gap; hashes alone do not substitute for inputs. The public package contains no private source, rendered private prompts, raw private answers or model weights. Recorded replay consumes existing answers and matrices without provider cost. A fresh source/encoder/judge run is a different experiment: it requires the full pinned inputs, an explicit new output location, and any provider credentials and costs supplied by the adopting repository.

The original full-workflow entry points can require sibling workers, complete source backgrounds, saved arrays, graph caches and byte-exact request recordings. Some original manifests still contain historical absolute locations. The shared replay maps those locations into the caller's explicit evidence root without editing originals. Direct legacy workflow execution requires a portable materialization of those manifests; merely setting an environment variable is not enough. Full-workflow relocation is **not claimed** unless a validation receipt explicitly records it.

For the stronger original cached-model prediction/allocation replay, using the frozen runtime and source manifests that already resolve:

```bash
python ../stage_replay.py --method learned-budget-policy --evidence-root "$EVIDENCE_ROOT" --out "$OUTPUT/learned-budget-policy-staged"
```

This stages writes in a new directory, blocks networking, and preserves the original inputs. It does not fit a new model or obtain new answers.

Recovery verification is recorded in `research/learned-budget-policy/validation.json` in [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens) (private; see [ACCESS.md](../ACCESS.md)). Numerical/queue/scheduler reproduction and aggregate-only checks are labeled separately there. Original implementations retain targeted legacy lint exceptions; public wrappers use normal repository lint.
