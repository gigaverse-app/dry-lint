# Reproduction scope and original-run contract

## The self-contained public command

Run `python3 -I reproduce.py --check` from this directory. Python 3.11+ standard library is sufficient; it imports no dry-lint module, archived script, SDK or target repository. It reads only bundled inputs and writes only stdout. `python3 -I reproduce.py` emits the computed JSON. No credentials or network access are needed.

The computation has two deliberately different parts:

- **Execute a measured transformation:** each pair in `inputs/weight-projections.json` carries all of its original normalized TF-IDF components. Multiply `fn:` weights by .5 on both sides, L2-normalize, compute the dot product and test the .35 floor. Validate against the original exact recorded scores to absolute tolerance 1e-12.
- **Aggregate recorded results:** combine frozen-reference and supplementary label counts while keeping the two layers available; compute guarded gains/losses, native arm tables and the source-recovery incremental cost. Check denominator/first-loss partitions, cap/completion assertions, and cross-table delta arithmetic. `expected.json` is the frozen output, not an input to the computation. Private histories are represented only by cohort-level cells.

`archive/manifest.json` additionally checks source integrity; hashes are not the reproducer. The vector transformation and recorded-result calculations run before that audit. `validation.json` records a complete clean-copy run, archive syntax checks and deliberate corruption checks. The package can be copied into an empty directory and run without this checkout or the lab.

## Exactly what the numerical projection loses

The first qualifying recorded E03 configured additional duplicate direction, the first qualifying additional separate direction, and the first configured development private positive floor miss without an addition were selected in original row order. This is an explicit illustrative selection, not random sampling or a performance panel. All tokens in each query/target union receive anonymous ordinals; equal original tokens still share an ordinal. Only membership in the function-name feature family is retained. Original insertion order and floating-point weights remain intact.

No token strings, paths, private Git revisions, source bodies, pair IDs, prompts, provider IDs or mapping back to identities are included. Full original IDF is already reflected in the normalized numbers, but raw counts and document frequencies are absent. The public command cannot recompute extraction, IDF, competitors, ranking, first-alternative selection, rules, changed queries, funding, cache reuse or labels. Original full backgrounds remain in the goldens repository. This is a source-free arithmetic projection of actual measurements, never a fabricated public reconstruction of private histories.

The source-recovery report counts are authoritative final recorded outcomes. We do not invent anonymized source programs, substitute public functions for private history, or treat vector projections as H05 replay inputs.

## Implementation versions and inert originals

All four workers used dry-lint commit **`b74a6223b4b41b8bb881c445c86c2dba82d62dd2`**. The public baseline used Python **3.14.4**; its sparse captures recorded **3.14.7**. Exact environment/extraction contracts for other backgrounds belong to each original manifest, not an assumed common Python version. For full source replay use the pinned checkout's `pyproject.toml` and `uv.lock`; they are available at that immutable public commit. The standalone calculation needs neither.

The actual lab scripts, selection algorithms, answer loaders, report correction and relevant production source are under `archive/`, always `.txt`. Original sources are inert: the public command never imports or executes them. Some originals contain live provider or filesystem-mutation code; their presence records the tested implementation, not an instruction to invoke it. Archive names retain `.py.txt` to make that boundary explicit.

The native recorded contracts also retain the earlier shared-operations v1 configuration for provenance; the H04 shared-operations result rows use v2, selected from `fresh-v2` by the original replay.

The original historical concept template is recovered from public dry-lint commit `2056161f4616bf07e0baf04c6d447329989dd1e4`, template SHA256 `6f25e05044efe101f069b1783b191e27ec348956a3cb7da156c035c5b7c2416b`. It is bundled in `archive/historical-template.txt`. Protected reference templates are in `archive/protected-reference-templates.json.txt`. The current generic shared-operations template has SHA256 `d16aa74739f455d380262e448db3d28a68241c4af47c4f87549b2dc83df6474f` and is bundled in `archive/shared-operations-template.txt`. A generic template is **not** a rendered private request.

Private lab roots and embedded adopter identifiers in archived scripts are replaced with explicit placeholders. Numeric history aliases 7001/7002 are placeholders, not public PRs. Every changed Python copy has a notice; `archive/manifest.json` records original and publication hashes plus replacement categories. Algorithms/constants are preserved. These sanitized scripts cannot authenticate the original private history without restoring the original identity bindings. The root coordinator retains the original files and a private pin/selection inventory outside the publication payload.

| Code / configuration | Purpose |
| --- | --- |
| `archive/sparse/run.py.txt` and `validate.py.txt` | Frozen IDF, weighted index, scope/source matching, directional selection, independent score reconstruction |
| `archive/guarded/replay.py.txt` | Exact oriented cache, strict sidecar reuse, first-unfiltered guard, production reservation and report construction |
| `archive/guarded/provider_support.py.txt` | Validated supplemental observations; paid failures remain unknown |
| `archive/native/replay.py.txt`, `judge_history.py.txt`, `replay_coverage.py.txt` | Historical-template recovery, original fixed/protected/refill scheduler and cost/call constraints |
| `archive/source-recovery/run.py.txt`, `handoff.py.txt` | Pinned Git/diff extraction, full candidate reconstruction and protected ordering |
| `archive/source-recovery/provider.py.txt`, `settled_provider_support.py.txt` | Source/funding/settings validation and separate observation overlay |
| `archive/final-report-correction/replay_h05_final.py.txt` | Actual final H05 replay with production `Report.build`; supersedes earlier false report flags |
| `archive/production/` | Original TF-IDF, candidate construction, scheduling, estimate/reserve/settle, prompts/parsing, settings and reporting implementation |
| `config/balanced.json` | Complete imposed H02/H05 balanced settings, including default fields; not a deployment assertion |
| `config/native-recorded-contracts.json`, `native-replay.json` | Archived Sonnet judge/template thresholds and exact two-budget replay limits |
| `config/half-name.json`, `prompt-contract.json` | E03 frozen selection and current prompt contract; its downstream unknowns remain unknown |

The source archive includes historical reporting scripts that generated provisional text. Those texts do not override `recordings/source-recovery.json`, which projects the final coordinator `h05-completed-evidence.json`. Likewise independent source review does not overwrite original reference labels. `recordings/provenance.json` identifies the exact final source artifacts by filename and hash for an authorized custodian; it cannot supply withheld data.

## What the full original rerun requires

The following inputs are **not bundled**. Access to the original private corpus and its exact identity bindings is necessary; a current checkout, a pair hash, gold snippets or the public nine-background panel cannot replace them.

| Study | Exact missing input contract | Original entry points, after restoring the authorized lab layout |
| --- | --- | --- |
| E03 | `pr-mining/{challenge.jsonl,legacy-gold-with-backgrounds.jsonl,background-manifest.json,configured-background-manifest.json,legacy-background-manifest.json}` and all 66 matching compressed backgrounds. Each must match repository, revision, scope, source mapping, document order, raw counts, extraction contract, max_df and compressed hash. Duplicate source IDs remain unresolved. | `protected-name-comparison/run.py`, then `validate.py`; code retained in `archive/sparse/` |
| H04 | For `historical-trial`: ordered `captures/*/{manifest.json,replay.json}`, `reference/labels.json`, `live/*-fixed.json`, `live/answers/*.json`. For `protected-trial`: equivalent captures, `fresh-labels.json`, `prompt-v1-snapshot.json`, archived `fresh/` and `fresh-v2/` fixed configs, `answers/*.json`, original `.04`/`.50` comparison outputs. Source authentication additionally needs all 45 recorded heads/merge-bases, pinned blobs and configuration files. | `native-history-replay/replay.py`, then `summarize.py`; original `scripts/judge_history.py` and `replay_coverage.py` from the implementation pin |
| H02 | `production-discovery/{frozen,regression}/captures/*/manifest.json` and every ordered numbered candidate packet, both cohorts' `answers/*.json`, frozen `reference.json` (73 rows), `supplementary.json`, original baseline/balanced curves, complete effective settings, exact prompt/source/context bindings. Supplemental loader needs immutable `provider/request-history.jsonl`, response contract, 12 accepted observations, funding snapshots and recorded usage. No complete regression reference panel is supplied even privately. | `historical-pr-replay/replay.py`, `report.py`, `final_counts.py`; strict supplemental import stays separate from original answers |
| H05 | The original eight-revision historical manifest, exact recorded base/head/merge-base objects and full source trees, configuration/workflow blobs, actual diffs, `candidates-0.json` through `candidates-7.json`, `candidate-deltas.json`, `config-source-audit.json`, `implementation-provenance.json`, `frozen-replay-inputs.json`, source-bound reference/labels and exact production/protected answer caches. Continuation additionally needs all 25 validated request/response records, `provider-staging/request-history.jsonl`, immutable `frozen-funding/` ledgers/contracts and the original identity map. | Original `run.py` reconstructs candidates; final coordinator `replay_h05_final.py` loads the validated overlay, starts both arms at ordinal zero and applies `Report.build` |

For those full runs, use the pinned checkout plus its locked environment, put each original script back in its recorded `.lab-results/<study>/` position so relative imports resolve, restore authorized input paths/identity bindings, and run with `PYTHONHASHSEED=1`. The archived implementations define exact input schemas, admission, parsing and output behavior. Source IDs and private Git SHAs are intentionally withheld publicly; the local coordinator's `PRIVATE-source-pins.json` maps the 23 manifests to exact commits/revisions/configs, and `PRIVATE-selection-provenance.json` identifies the three projections. Those files must not be copied into a public PR.

H04 source audit matched 782 distinct captured function spans across 45 revisions, but did not prove fresh extraction parity. H05 reconstructed all eight diffs; some other ancestors are missing, preventing independent ancestry recomputation. H02 capture absence cannot distinguish extraction, scope, changed-line selection, floor or ranking loss. These limits cannot be repaired with invented inputs.

A fresh provider run is not part of the public reproducer. It would require the same private rendered requests and source/config/funding bindings, compatible named model/version/output policy, the adopter's own authorized credentials and budget, and a new append-only response/usage recording. No provider call was made to create this publication, and no credential, endpoint operated by dry-lint, or live-rerun helper is supplied. Historical provider answers are observations, not independent labels.

## Reservation, normal estimates and cache charging

At the archived Sonnet rates of $2/M input and $10/M output, H04 reserves:

```text
((UTF8_prompt_bytes + 1000) * 2 * 1.25 + output_cap * 10) / 1_000_000
```

It settles recorded input/output/cache-write/cache-read usage. H02/H05 use production `reservation_cost` and `CampaignStore` with recorded Haiku rates $0.10/M input and $0.50/M output; see archived `discovery.py` and `costs.py`. Their complete balanced config fixes 200 campaign calls, 20 calls/revision and 10 exploration calls/revision as well as the dollar/credit limits. Cache-create tokens cost 1.25× input; cache reads cost .1× input. Rates are frozen experimental assumptions, not a statement of current provider prices.

An average normal estimate is a different calculation (`prompt_characters / 2.8`, expected output 150 tokens for these models). Do not admit by that cheaper estimate while claiming a native reservation comparison. Nor may old gold-query batch estimates or PR #113's later ordering simulations be substituted for these chronological results. Each arm pays its own first selected exact observation; only valid same-arm chronological reuse avoids a new charge. All reported dollars are list-price usage estimates, not verified invoices.

## Licensing and publication boundary

The archived dry-lint implementation and derived reproducer retain the repository's **Apache-2.0** license in [LICENSE-APACHE-2.0.txt](LICENSE-APACHE-2.0.txt). Modified archive copies carry notices. Generic templates are dry-lint source. No private adopter source, source-name tokens, rendered private prompts, private provider logs, full corpus backgrounds or third-party source snippets are redistributed. Numeric projections and aggregate measurements are research evidence; this publication grants no rights to the omitted private sources. Exact upstream public Due/pytest source examples were not added to this package, so their sources/licenses are not substituted or silently relicensed.

Keep this whole directory together when copying the public payload. Handoff metadata (`HANDOFF.json`, `PR-title.txt`, `PR-body.md`) is for the root coordinator and is excluded from the public payload. Private audit inventories live outside this directory. The intended public destination is `docs/research/historical-recovery/`; the relative link to the already-merged research record resolves there.
