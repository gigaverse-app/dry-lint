# An independent broader reference reverses the original recall win

The earlier panel reproduces fusion 74/82 versus sparse 71/82. The additional panel gives fusion 56/77 versus sparse 63/77. Combined: 130/159 versus 134/159, six gains and ten losses. The full inventory has 826 rows and 79 backgrounds; the measured nonreserved mapped function inventory is 754 rows. Those are different counting units.

A small selected panel can favor a combined ranker while hiding losses in other repositories. This independent reference fixes source groups and denominators before comparing the same background ranks.

## What was tested

Join exact endpoint bodies and repository-qualified identities into conservative source components. Keep revisions/scopes separate and reserve all OpenCode-connected rows. Compare TF-IDF, MiniLM and equal RRF60 at fixed ranks, collapsing row aliases to pair-cases and preserving accepted binary labels separately from utility assessments.

The apparent three-case gain on the original 82 positives is outweighed by seven losses on 77 additional positives. Appending these measurements does not turn the development corpus into unseen validation.

## Recorded comparison

| Accepted positive pair-case cohort | TF-IDF at four | Fixed RRF60 at four |
|---|---:|---:|
| Previously evaluated | 71/82 | 74/82 |
| Additional development cases | 63/77 | 56/77 |
| Combined, correlated development sample | 134/159 | 130/159 |

## Decision and limits

Do not replace sparse ordering with fixed fusion. Preserve complementary candidates for budgeted evaluation. The source-followup reviews and paid observations are separate private evidence, not training truth.

This is recovery of an existing frozen experiment. No providers, new encoder inference, new mining or new experiments ran during packaging. Source-positive labels, provider answers, retrieval ranks and emitted reports retain their separate meanings. The original report and earlier failures remain in the private archive; this recovery report corrects interpretation without overwriting them.

## Implementation and recorded replay

Recovered entry points: [`audit_configuration.py`](implementation/audit_configuration.py), [`inventory.py`](implementation/inventory.py), [`reference.py`](implementation/reference.py), [`summarize_reference.py`](implementation/summarize_reference.py), [`verify_reference.py`](implementation/verify_reference.py). [Provenance](PROVENANCE.json) binds every original and public implementation SHA256. Explicit evidence-root path substitution, formatting and documented legacy lint exceptions preserve the original algorithm AST; numerical recipes are unchanged. [Frozen recipe and source hashes](recipe.json) identify the input and result files.

From this method directory, with a materialized private evidence tree preserving `jobs/` and `reports/`, and a new output filename:

```bash
python ../replay.py --method cross-repo-recall-audit --evidence-root "$EVIDENCE_ROOT" --out "$OUTPUT/cross-repo-recall-audit.json"
```

Recompute the broader pair-case table from frozen independent-reference ranks. The replay output declares its exact scope. Aggregating recorded events is not rerunning a scheduler; aggregating saved ranks is not re-extracting source. Matrix replays need NumPy; other shared replay modes use the standard library. Original model-fitting scripts require the frozen scientific runtime, and native scripts require the pinned dry-lint source, rather than whichever product version happens to be installed.

The evidence tree is intentionally required. Obtain authorized access to [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens), then use the exact recovery dataset/commit receipt in [ACCESS.md](../ACCESS.md). An absent dataset receipt or missing artifact is a reproduction gap; hashes alone do not substitute for inputs. The public package contains no private source, rendered private prompts, raw private answers or model weights. Recorded replay consumes existing answers and matrices without provider cost. A fresh source/encoder/judge run is a different experiment: it requires the full pinned inputs, an explicit new output location, and any provider credentials and costs supplied by the adopting repository.

The original full-workflow entry points can require sibling workers, complete source backgrounds, saved arrays, graph caches and byte-exact request recordings. Some original manifests still contain historical absolute locations. The shared replay maps those locations into the caller's explicit evidence root without editing originals. Direct legacy workflow execution requires a portable materialization of those manifests; merely setting an environment variable is not enough. Full-workflow relocation is **not claimed** unless a validation receipt explicitly records it.

Recovery verification is recorded in [validation.json](validation.json). Numerical/queue/scheduler reproduction and aggregate-only checks are labeled separately there. Original implementations retain targeted legacy lint exceptions; public wrappers use normal repository lint.
