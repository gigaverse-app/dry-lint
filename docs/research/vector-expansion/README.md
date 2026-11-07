Keep raw token retrieval; stop the tested latent and sparse-expansion recipes

Raw TF-IDF (token frequency weighted by rarity) needs shared retained features and can leave useful matches outside its first three candidates. We tested learned feature relationships to improve dry-lint’s retrieval stage without losing known duplicates or exceeding the same review budget.

First, latent semantic indexing compressed function-token vectors into 64 dimensions, optionally correcting for frequently retrieved “hub” functions. Ranking worsened; loss of lexical detail is a plausible explanation, not an isolated cause. We then kept raw retrieval first and appended one candidate from a separate sparse-association channel. It adds at most four features from rare tokens whose cooccurrence spans at least three functions/two files, then normalizes. No labels train either representation.

For example, raw treats `equal` as a function name differently from `equal` in a body. Learning that feature-role link connected a provider type assertion with an equality-test helper, moving normalized-vector similarity from 0 to .362. Both providers rejected the pair: correlation is not a repeated operation (VEC-R2-006).

We compared 79 separate frozen backgrounds covering 617 development records, including all 400 historical and 37 original public records. Evaluated: 607 function records, including all 580 accepted functions. Four accepted model declarations were unsupported; five unaccepted source/mapping exceptions and one self-pair remain visible. Below, 227 positive pair/background conditions represent 185 distinct pairs /106 family groups of related cases. Each condition is an unordered pair in one exact snapshot/scope; directions/families are correlated. This is regression evidence, not fresh holdout.

| Representation | Mean inverse rank, higher better | Positive top 3 /227 | Positive top 20 /227 |
|---|---:|---:|---:|
|Raw TF-IDF|.7002|182|218|
|64-dimensional latent|.5916|158|198|
|Latent plus hub correction|.5451|144|196|
|Sparse association|.6931|182|220|

Sparse top 20 gains 2/loses 0 positive conditions in one family, but top 1 gains 4/loses 7. It newly exposes 3 separate-control conditions at top 20, removing 1. These are candidates, not false reports. Protected known-positive funding stays 13/78, with 171 unsupported contexts; separate-control funding stays 6/120, 408 unsupported.

Full-source discovery used disjoint source-file groups between rounds and matched controls with distinct endpoints:

| Mechanism | Answered novel / controls | New policy emissions | Actual judging cost |
|---|---:|---:|---:|
|Latent protected channel|34 /8|0|$0.200325|
|Sparse association|36 /8|1|$0.207322|

Seven first-round source assessments found no useful operation. Seven accepted second-round assessments found one SMALL polling extraction, one tiny exact-fixture control, two related cases and three negatives. None became global gold; 19 unstarted pairs and one parse exclusion stay unknown.

The source-accepted emitted lead is only a small polling/timeout test convenience, requiring explicit synchronous/awaiting check modes and preserved timeout labels ([polling helper](https://github.com/anomalyco/opencode/blob/cc996eece172fc69e35662657ea6cea9c2c7db88/packages/tui/test/cli/tui/use-event.test.tsx#L12), [async-capable helper](https://github.com/anomalyco/opencode/blob/cc996eece172fc69e35662657ea6cea9c2c7db88/packages/tui/test/context/session-tabs.test.tsx#L21), VEC-R2-042). Adding an await to the synchronous check would change scheduling; source acceptance does not permit that substitution. Raw already ranked it fourth at .962: an extra slot may explain the gain, without learned associations. A meaningful missed lead repeats tool-result conversion inside an event reducer, with namespace/guard differences ([reducer](https://github.com/anomalyco/opencode/blob/cc996eece172fc69e35662657ea6cea9c2c7db88/packages/ai/test/lib/tool-runtime.ts#L82), [converter](https://github.com/anomalyco/opencode/blob/cc996eece172fc69e35662657ea6cea9c2c7db88/packages/ai/src/schema/events.ts#L627), VEC-R2-017). Its .55 judge score misses the unchanged .8 report rule; whole-function equivalence is not claimed. Both funded zero-original-posting pairs were provider-rejected, so no useful zero-overlap recovery is established.

**Decision: STOP_THIS_VARIANT.** Keep raw retrieval; do not ship these fixed recipes. Sparse expansion did not improve overall ordering or known funded-positive coverage, and its emitted lead does not establish association-specific value. Retain the accepted tiny polling contract and the unaccepted converter lead; close the experiment with no third variant. Other sparse expansions and soft token matching remain untested.

<details>
<summary>Protocol, runtime, reproduction and audit appendix</summary>

Latent fitting used uncentered randomized singular-value decomposition: rank min(64,min(shape)−1), oversampling 10, two power iterations, seed 0. Hub correction subtracts each endpoint’s mean similarity to ten other-file neighbors from twice their latent cosine; floors match raw first-neighbor coverage without labels. Each representation fits its own complete pinned background. Original corpus feature weights, feature order and maximum-document-frequency filtering remain unchanged; unsupervised fitting uses source competitors transductively, never labels or merged revisions. The sparse recipe learns from each function’s eight rarest retained anchors: document frequency 3 through min(128,5% of functions), association strength log₂(N×cooccurrence/(frequency₁×frequency₂))≥3, where N counts functions, at most two edges per anchor. Add 0.5×anchor weight×min(strength/8,1), then normalize. This is ordinary vector cosine, not an arbitrary soft-token metric.

Mean inverse rank averages both directions; topK succeeds if either direction reaches K. Negative controls cover 522 pair/background conditions/377 distinct pairs/138 family groups. Family/repository resampling preserves shared lineage; no independent-trial significance claim is made. Scoped-operation and drift labels remain scoped. All 1608 original raw directions are unchanged.

The diagnostic default is other-file raw top 3, floor .5 (.3 for a verified native span under 6 lines); sparse expansion adds at most one candidate at the same floor. Standalone balanced top 20 at 0.35 is a separate diagnostic. Neither is inferred deployment configuration. Each synthetic eight-query batch retains a normal-estimated $0.04 cap, charging cached answers to each arm. Physical provider costs above are separate; older $0.01393132 is excluded. Emission replay uses the original standalone Sonnet shared-operations policy at .8; Jev remains a separate observation. Second-round baseline controls emit two reports already available to raw and receive no novelty credit. Source review accepted the identical agent fixture as a tiny control convenience (VEC-R2-040): keep fresh objects and function-scoped fixture lifetime. The other emitted control remains source-unassessed. The small polling candidate was admitted in its original $0.04 batch ($0.026542 normal estimated total) and emitted under the unchanged policy; this is one small scoped benefit, not a substantial improvement or global novelty claim. The conversion lead was raw rank 1 at .476, below the .5 retrieval floor; expansion moved it to .500, then the judge score blocked emission. This is a retrieval-floor gain followed by a reporting loss, not proof of whole-function duplication. The LaTeX-layout full-file parse exclusion remains unknown (VEC-R2-025), not negative; 28 first-round pairs also remain unstarted.

Cold sparse builds across 79 backgrounds total 123.35s; peak regression RSS 819,044 KiB. On the 13,893-function public contrast, raw query time was 74.81s and the added association query work 52.15s. The primary 2,348-function scan used 2.21s raw and 1.61s association queries. All computation used at most two threads and sparse queries rather than a full pair matrix. An initial ledger-adapter error was corrected before queue publication; fitted vectors and selection decisions were preserved, and normal charges were repaired from exact selected candidates. Timing is not a clean cold end-to-end deployment benchmark.

Use [the compact final metrics](data/evidence/FINAL-METRICS.json) for denominators, gains/losses, source status and costs. The supplied `source_pmi.py`, `run_regression.py`, `discover.py`, `summarize.py` and result-join scripts define the implementation. Run with `PYTHONHASHSEED=0`, `PYTHONPATH=src:<vector-helper-directory>` and BLAS/OpenMP thread limits 2. Regression and discovery are local; provider execution belongs only to the coordinator. Exact lab commands, input hashes and private evidence references are kept separately. Full 617-record reproduction requires the frozen backgrounds, mapper and native-source caches; hashes alone do not reproduce unavailable artifacts. Source-only discovery used OpenHands/software-agent-sdk at 344ec8a9c30dff0a4ca200fc412510aad44e1bdc and anomalyco/opencode at cc996eece172fc69e35662657ea6cea9c2c7db88; source examples link their unchanged pins. No production, configuration or CI changes were made by this experiment.

</details>


## Run the portable study package

This publication adds exact selected-input transformation replay and recorded-answer scoring to the frozen report above. It keeps original artifacts in `data/evidence/` unchanged, including historically pending fields. [Final source interpretations](data/final-source-decisions.json) are a separate update; provider answers never substitute for them.

From this directory, using Python 3.11 or newer and only the standard library:

```sh
python3 transform.py
python3 reproduce.py replay
python3 reproduce.py audit
python3 reproduce.py inspect VEC-R2-042 --part prompt
python3 reproduce.py inspect VEC-R2-042 --part answer
python3 reproduce.py archive
```

`transform.py` reruns the selected transformation, checks its recorded output and prints the before/after result. `reproduce.py replay` reparses sanitized original answers for the representative cases and recomputes fixed-policy emissions and primary-feed costs. The full primary feeds retain all unstarted answers as unknown in [observations](data/observations.jsonl). Admission decisions are frozen inputs in [policy admissions](data/policy-admissions.jsonl); replay is not a fresh candidate search or a new source adjudication. The historical full-corpus comparisons remain scoped to their supported denominators.

The exact contextual Jev request uses `jev-1.14.0`; Claude uses `claude-sonnet-5-5`, shared-operations prompt, 1,024 output tokens, no effort override, no malformed-answer retry, and the recorded default server fallback option. Exact per-request options, scope, full rendered prompts and source hashes are in [selected cases](data/selected-cases.json.gz), inspectable with the commands above. No temperature or seed is set in these requests. Jev scores same-concept probability, capped by a concrete separation reason; score below .6 is separate, behavior difference at least .8 is drifted, and non-separate score at least .8 is reportable. Jev and Claude remain independent observations. These are recorded outcomes, not a claim that a future model would answer identically.

[Readable key implementation files](implementation/README.md) and the complete archived study scripts, dry-lint modules and lockfile are available through `reproduce.py archive NAME`. Archived runners preserve their original dependency paths and are data, never imported at module startup. The portable adapters execute only explicitly selected pure algorithm definitions or their documented bounded application; they never import provider runners. Original and public hashes disclose any static private-routing redaction.

## Inputs, acquisition and limits

The selected native function bodies and full files are shipped under their original [licenses](licenses/), with Git pins and hashes in [source files](data/source-files.json.gz) and the [source manifest](data/source-manifest.json). They are parsed or inspected as data, never imported or executed. Full corpus inputs stay in the separate goldens repository. Print the pinned acquisition plan, review it, then run it explicitly:

```sh
python3 acquire.py > local-acquire.sh
cat local-acquire.sh
sh local-acquire.sh
```

[CORPUS.json](CORPUS.json) maps all 79 study-background hashes against `gigaverse-app/dry-lint-goldens` at `bb29c4b71987008d06c2381a68b6833b6d542e3e`: **8 exact matches, 19 public backgrounds absent from that catalog, and 52 private backgrounds excluded from public distribution**. It records exact dataset/materialization paths for matches. A same-repository background with another hash is not a replacement. The manifest is an input inventory, not an evaluated denominator. Public source pins, configured/diagnostic scopes, parser and extraction versions, original row mappings, family lineage, per-query candidate exclusions and budget ledgers are all needed for full-campaign reruns. Their location contract is explicit; a hash cannot reconstruct an absent input. Original scripts and specifications preserve the protocol without copying large backgrounds into this repository.

The included source-free held-request templates, if any, have no source or model explanation prose. `python3 hydrate.py` prints the exact local plan. Hydration requires an explicitly supplied Git checkout, checks full source hashes, applies the frozen extraction character map and validates both rendered-request and request-identity hashes. It is cached-extraction reconstruction, not a fresh parser validation. Keep hydrated output local. The current publication makes no provider calls and provides no executable live judge runner; a new live study would require separate authorization, adopter-owned credentials and budget, the original archived procedure and a new output directory.

[PROVENANCE.json](PROVENANCE.json), [feed hashes](data/feed-provenance.json), per-file archive hashes and `SHA256SUMS` distinguish original evidence from publication adapters. [CHECKS.json](CHECKS.json) records the clean-copy commands, source/license checks and decompressed archive scan. These checks verify the stated selected replay and arithmetic, not full-corpus extraction, production deployment, semantic gold labels, invoices or broad recall.


The selected vector replay executes the original TF-IDF class and the original bounded contribution loop from `source_pmi.py`, using the exact recorded full-background IDF and learned edges. It reproduces all four selected vector pairs to floating-point tolerance without refitting associations. It does not infer full-corpus ranks from the selected examples. `python3 aggregate.py` separately recomputes ten original/revised positive and separate ranking comparisons, including the latent/hub-corrected regressions. Dataset/batch funding uses a different denominator and remains preserved in `FINAL-METRICS.json`.

For the SMALL polling lead (VEC-R2-042), the original Claude answer says “EXISTING is a superset” and returns `duplicate`, `.90`; Jev returns `drifted`, `.96`. Root accepts only a narrow polling convenience with explicit synchronous/awaiting modes. Adding an `await` to the synchronous callback changes scheduling, so the original answer's blanket substitution needs that qualification. The converter lead (VEC-R2-017) gets a Claude `duplicate` answer at `.55`: the overlap was recognized but the reporting rule suppressed it. It remains an unaccepted source lead, never a confirmed missed report. Both raw answers and the seven accepted source-D decisions are included; neither tiny fixture reuse nor the SMALL report is inflated into substantial gain.

Round-one primary feed cost is $0.17328328 for 72 successful responses. Twelve additional current-phase responses in [the supplemental feed](data/supplemental-observations.jsonl) cost $0.02704136. Their disjoint request keys reconcile to **84 responses / 42 pairs / $0.20032464**; 56 unstarted responses remain unknown. Round two costs **$0.20732188**, for **$0.40764652** total fresh attributed spend. The separately excluded older $0.01393132 is not added. `reproduce.py replay` recomputes this reconciliation.

To run the complete original representation algorithm later on one acquired exact background (a new computation, not needed for the recorded-result replay), create an environment with the observed `numpy==2.5.4` and `scipy==1.18.1` and use:

```sh
python3 -m venv local-env
local-env/bin/python -m pip install numpy==2.5.4 scipy==1.18.1
PYTHONHASHSEED=0 local-env/bin/python run_original.py --method sparse --background local-candidate-first-gold-v1/backgrounds/opencode-cc996eece172fc69e35662657ea6cea9c2c7db88.json.gz --out local-new-sparse-fit
```

Use `--method latent` with another new output directory to execute the original randomized rank-64 fitting function. `run_original.py` loads only explicitly selected original algorithm definitions and checks the background hash; it has no judge transport. The original complete hub correction, nomination, source-resolution and funding runners remain in the archive. This optional full-background entrypoint was syntax/help checked during packaging; no refit was performed. Its output is a representation, not a reproduction of the whole historical campaign.
