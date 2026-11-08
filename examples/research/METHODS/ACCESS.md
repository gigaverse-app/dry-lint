# Private evidence access

Authorized access to [dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens) is required. The final evidence commit is [`f430b9ade685a4125c8eb66ef785da32f9d1c30c`](https://github.com/gigaverse-app/dry-lint-goldens/commit/f430b9ade685a4125c8eb66ef785da32f9d1c30c), merged in [corpus PR #11](https://github.com/gigaverse-app/dry-lint-goldens/pull/11). Its tree exactly matches tested data head `1573260772a1e499a617a32ca841bb61dd13c588`. Private source, rendered prompts, raw answers, labels and matrices stay in that repository.

| Dataset | Contents and use |
|---|---|
| `worker-evidence-v1` | Original worker implementations, recipes, reports, source artifacts and recorded responses; materializes under `evidence/` plus indices. |
| `worker-judgments-v1` | Scoped accepted source rows, original assessments, background bindings and reconciliation. Diagnostic same-revision background matches do not restore historical retrieval-policy authority. |
| `worker-matrices-v1` | Frozen matrices and large result inputs, stored as chunks with exact original-path reassembly records. |
| `worker-replay-state-v1` | Original verdict stores and additional large replay inputs, with a separate chunk reassembly index. |
| `grounded-product-replay-v1` | Retired grounded-product replay observations and explicit dependencies; separate from these twelve recovered method contributions. |

All twenty minimum inputs, including two complete matrices, were restored from verified corpus objects. All eleven shared result modes reproduced their exact saved results with original-lab evidence reads and networking blocked. Imports from the existing scientific environment were permitted; this is evidence relocation, not a sealed standalone runtime. Numerical matrix ranking and queue replay remain distinct from aggregate-only rank/event summaries.

## Minimal shared replay

Use an authorized corpus checkout and a **new** directory for `EVIDENCE_ROOT`. Set `OUTPUT` to a writable result directory. From the public dry-lint checkout:

```bash
git -C "$CORPUS_CHECKOUT" checkout --detach f430b9ade685a4125c8eb66ef785da32f9d1c30c
python3 "$CORPUS_CHECKOUT/verify_recovery.py" --minimum-inputs --out "$EVIDENCE_ROOT"
```

The command validates all payloads/chunks before creating the destination, restores the original relative `jobs/`, `reports/` and coordinator `.lab-results/` paths directly under `EVIDENCE_ROOT`, and refuses an existing destination. Its twenty restored files must match [minimum-replay-inputs.json](minimum-replay-inputs.json). Run the selected method's README command afterward. Shared matrix replay needs NumPy; the other shared result modes use the standard library.

## Original artifacts, judgments and additional inputs

To inspect full original artifacts or source judgments, choose **new**, separate destinations:

```bash
python3 "$CORPUS_CHECKOUT/corpus.py" materialize worker-evidence-v1 --out "$FULL_EVIDENCE_PACKAGE"
python3 "$CORPUS_CHECKOUT/corpus.py" materialize worker-judgments-v1 --out "$JUDGMENTS_PACKAGE"
export FULL_EVIDENCE_ROOT="$FULL_EVIDENCE_PACKAGE/evidence"
```

`FULL_EVIDENCE_ROOT` has the same logical path layout as the minimal root; the package's `indices/` directory holds storage and lineage indices. The judgment package contains the scoped rows and their background bindings. A diagnostic binding supplies exact same-revision source identity, not a claim of production-policy replay; missing bindings remain missing.

For a single larger artifact, take its exact original-relative `ARTIFACT_PATH` from the selected dataset's `reassembly.jsonl`, and choose a new `ARTIFACT_OUTPUT` whose parent exists:

```bash
python3 "$CORPUS_CHECKOUT/verify_recovery.py" --dataset worker-matrices-v1 \
  --reassemble "$ARTIFACT_PATH" --out "$ARTIFACT_OUTPUT"
# For a saved verdict store or other replay-state artifact, select its own dataset:
python3 "$CORPUS_CHECKOUT/verify_recovery.py" --dataset worker-replay-state-v1 \
  --reassemble "$STATE_ARTIFACT_PATH" --out "$STATE_ARTIFACT_OUTPUT"
```

Use the dataset that actually contains the logical path. Reassembly checks every chunk boundary/hash and the complete original byte length/hash before writing a new output. The two commands are independent examples, not two ways to reconstruct an arbitrary file.

## Scope and remaining prerequisites

The minimum closure supports eleven shared recorded-result modes. Recorded metrics are not a reconstructed graph; settled event totals are not a scheduler execution; cached matrix ranking is not encoder inference. The corpus-only result receipt establishes only its stated scope.

All 86 original implementation/test files referenced by the public package were checked against archived bytes. Stronger original scheduler, saved-model allocation, bundle and mapper checks passed locally. Their complete archived-input execution and arbitrary-root relocation are not implied by the minimum closure. The separate closure audit independently verifies all 32 requested original recipe/control/sample files and all 56 restored logical paths. Those enumerated archived-byte gaps are closed; complete execution of every original workflow after relocation remains untested. Original algorithms may require complete source graphs, exact Candidates, prompts, raw recordings, model/feature arrays, pinned product source and the frozen scientific environment. Fresh encoding additionally requires the separately licensed pinned model weights.

Historical absolute paths in immutable manifests need portable resolution before direct legacy execution; setting an environment variable alone is insufficient. Missing inputs must fail explicitly, without substituting a revision, inventing an answer, fitting a new model or invoking a provider. Recorded replay has no provider or inference cost. A new experiment needs its own output history, settings, complete inputs and adopter-supplied credentials/costs.
