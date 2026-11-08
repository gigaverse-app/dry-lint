# Residual-budget native replay

This example reproduces the experimental residual-budget implementation through actual
`Judging`, `CampaignStore`, verdict storage and reporting. It starts with frozen detected
`Candidate` artifacts and supplies exact recorded answers through a judge plugin. It
makes no provider calls, constructs no provider client and requires no credentials.
This is a native-campaign replay, not a normal estimated-admission implementation.

The implementation is tested, but **promotion is held on report quality**. It preserves
the complete configured balanced pass, including operation blocks, then admits residual
TF-IDF exploration under the same $0.04 campaign allowance. The residual pass borrows
capacity reserved for future baseline evidence; current-pass preservation does not
promise future-push preservation. No default profile changes.

## Evidence and conclusion

The paired experiment used 12 frozen single-query source campaigns, not 12 historical
PR diffs: unchanged current main versus the
reviewed opt-in patch, with the same $0.04 cap per campaign and original judge policy.
All 12 candidate prefixes and protected attempt/charge sequences were preserved.

| Scope | Baseline reports preserved | Lost | Added | Useful / nonuseful / disputed additions | Control logical USD | Treatment logical USD |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| 11 complete paired campaigns | 24 | 0 | 10 | 3 / 5 / 2 | 0.0382533 | 0.0969322 |
| Remaining campaign, known prefix only | 2 | 0 | 2 | 0 / 1 / 1 | 0.0035410 | 0.0140067 |
| All known prefixes, not all complete | 26 | 0 | 12 | 3 / 6 / 3 | 0.0417943 | 0.1109389 |

An occurrence is one reported pair in one campaign. The 12 additions represent 11 unique
pairs: 3 useful, 6 nonuseful and 2 disputed claims. Costs sum separate campaign ledgers;
each campaign stays below $0.04. Replay physical calls and physical dollars are zero.
The incomplete treatment reaches a prior failed question without a reusable successful
answer. Its $0.0060248 hold remains charged, with no retry. Its report is explicitly a
reconstructed known-prefix lower bound, not a completed scheduler result.

The independent audit assessed what each report actually claimed against frozen source
judgments. Seven source-useful pair exposures are not seven useful reports: some
rationales name tiny guards, already-shared operations, or disputed behavior instead of
the useful operation elsewhere in the pair. Disputed claims receive no confirmed credit.
All three confirmed useful claims occur in the AI repository; the required two-repository
adoption bar is not met. This is a post-freeze outcome audit, not new blind gold labeling.

A narrower ownership review compared four actual baseline findings with those three
confirmed additions in two campaigns. Its increments are:

| Confirmed added claim | Increment over that campaign's baseline reports |
| --- | --- |
| Batch-feed synchronization | One new useful campaign family claim; one additional owner, with the already-exposed owner retained |
| Analysis finalization | One new independent owner in an existing family |
| Collector lifecycle | One redundant alternate pair; no additional owner or family |

Thus there is one new campaign family claim, two additional independent owner memberships
across the first two rows, and one redundant pair—not three new families. All are in AI;
none of the three families is globally new to the frozen source-review history. The
ownership review did not inspect other campaigns or broaden source opportunities.

Budget and candidate correctness passed, while report quality and limited ownership
increment keep the implementation in draft. A separate grounded-operation prompt
experiment does not change these observations or this example's judge policy.

## Fixture access and pins

Only scripts and this README are public. No corpus, source excerpts, rendered questions,
recorded answers or private audit rows are included here. The private corpus dataset is **`residual-native-replay-v1`**, published in
[corpus PR #8](https://github.com/gigaverse-app/dry-lint-goldens/pull/8) at merge
`f14564f05f1541bc1ee8557b099253d82e7fa70f` (reviewed head
`405fba8f870f14b401c9390d39f3608309ebf235`). Authorized reviewers need access to
[the private corpus repository](https://github.com/gigaverse-app/dry-lint-goldens).
It materializes 297 files including the claim audit and owner closure, with zero new
labels. Without private access, the synthetic corruption tests can run but the full
replay cannot. The coordinator independently materialized this published dataset and
reran all 24 actual arms; four corpus storage tests also passed.

The dataset uses a content-addressed object store. It contains the same 12 cases / 24
arms, 24 detected candidate arrays, expected ledgers, and only the 117 funded recordings
plus their 117 immutable originals. There are 284 objects totaling 22,705,584 bytes.
No complete function inventories, TF-IDF matrices, dense embeddings, unrelated answers
or additional gold cases are required. Historical absolute paths inside receipts are
provenance strings resolved by hash beneath `--corpus`; they are never opened.

| Pin | Value |
| --- | --- |
| Private dataset merge | `f14564f05f1541bc1ee8557b099253d82e7fa70f` |
| Unchanged product base | `2aab042c256141383c7c731b7ba6097dd2db53b3` |
| Original research runtime, distinct from the tested product base | `a10a288530c4aa25711c7ec3b86ac164d182899a` |
| Verified private portable archive SHA-256 | `a1864e6aa01cf2f38a7964a95d16dca3961a795b88c392d41d7ed6588eb71b40` |
| Verified archive size | 3,302,143 bytes |
| Corpus `manifest.json` SHA-256 | `0aef1600f0db97c2b6c6737d0942650373261af1dfbf7e9f7cbef5ff7842c416` |

The archive pin identifies the tested private package, not the public scripts directory
or the corpus repository's storage wrapper; the latter also includes the claim audit and owner closure. The corpus
manifest pins all 56 source files in each runtime and every required evidence object.
The treatment runtime is the base plus the reviewed residual patch; a source mismatch
fails before replay. The complete capture-equivalence audit accepted 918 derived receipts
from 907 physical originals; this smaller fixture retains only the funded subset and
its provenance closure. That receipt acceptance does not imply product promotion.

## Run the actual native replay

Use Python 3.11+ with the checkout's locked dependencies. The validated interpreter was
Python 3.14.4. An existing repository venv suffices; with a populated dependency cache,
`uv sync --locked --offline` sets up another. No optional provider or Dryer extra is
needed by frozen-candidate replay. The scripts perform no installations or downloads.

First materialize the dataset from a dedicated authorized corpus checkout. No clone or
access token is supplied by dry-lint:

```bash
GOLDENS=/path/to/authorized/dry-lint-goldens
EVIDENCE=/path/to/new/residual-native-replay-v1
git -C "$GOLDENS" checkout --detach f14564f05f1541bc1ee8557b099253d82e7fa70f
python3 "$GOLDENS/corpus.py" materialize residual-native-replay-v1 --out "$EVIDENCE"
```

Set paths to your authorized local files; there is no lab-directory dependency. Select
an unchanged source checkout at the base pin and a reviewed patched checkout. Keep
`replay_frozen.py` and `recorded_judge.py` together:

```bash
export PYTHONDONTWRITEBYTECODE=1
PY=/path/to/locked-venv/bin/python
BASE=/path/to/unchanged-base-checkout
PATCH=/path/to/reviewed-patched-checkout
SCRIPTS="$PATCH/examples/research/residual-budget"
CORPUS="$EVIDENCE/corpus"
OUT=/path/to/new-replay-output

# Check this against the manifest pin above before replay.
sha256sum "$CORPUS/manifest.json"
mkdir "$OUT"
PYTHONPATH="$BASE/src" "$PY" "$SCRIPTS/replay_frozen.py" --runtime "$BASE" --corpus "$CORPUS" --arm balanced --out "$OUT/control"
PYTHONPATH="$PATCH/src" "$PY" "$SCRIPTS/replay_frozen.py" --runtime "$PATCH" --corpus "$CORPUS" --arm residual --out "$OUT/treatment"
```

Expected results are 12 complete controls and 11 complete treatments, with all 24 arms
matching expected ledgers, charges, unknowns and reported pair sets. The runner writes
`SUMMARY.json` and per-case actual reports, ledgers and events. Any semantic mismatch
fails; timestamps may differ, so report byte hashes identify individual runs rather
than define equivalence. Use new output directories to preserve prior evidence.
Outputs contain private fixture excerpts and must remain with the authorized evidence.

Returned tokens settle through real native admission; the verdict cache is not preloaded
for free. Exact rendered question, model, source/context, reporting settings and physical
receipt bytes are checked before answer reuse. Only `Candidate.residual` is normalized
as routing metadata. Missing recordings remain unknown and retain a conservative hold.

Both arms were independently rerun after relocation with networking and original evidence
reads blocked: all 24 matched. The runner does not import the research scheduler. Product
recovery is more conservative after deferred baseline or failed/in-flight attempts and
keeps protected pacing credit separate; agreement on these single-revision traces does
not establish equivalence for concurrency or future revisions.

Synthetic relocation/corruption tests need no private fixture:

```bash
PYTHONPATH="$PATCH/src" "$PY" -m pytest -q "$SCRIPTS/test_portable.py"
"$PY" -m ruff check "$SCRIPTS"
"$PY" -m ruff format --check "$SCRIPTS"
```

Six tests cover moved originals, corrupt objects, missing objects without fallback and
invalid object references. The product's separately completed full suite had 1441 passes
and 19 skips. Provider-free replay of a private fixture is not a new source-quality audit.

## Detection regeneration is a separate task

Frozen-candidate replay needs no source Git stores. Regenerating detection requires
access to the exact six repository/revision/scope cohorts and twelve query identities
listed in the private package's `DETECTION-INPUTS.json`, plus the original producer's
frozen configurations and current-native extraction procedure. Obtain private repository
access from the owners; public scripts ship no keys or source archives. Verify each
required commit in an authorized existing store before extraction:

```bash
git -C "$SOURCE_STORE" cat-file -e "$SOURCE_REVISION^{commit}"
```

The evidence package identifies the native function/background objects by digest.
Obtain the original producer procedure and those objects through the authorized corpus
maintainer when regenerating detection; do not substitute old extractor metadata or inferred
source equivalence. This minimum example deliberately starts from detected candidates
and does not reproduce detection from source excerpts alone.
