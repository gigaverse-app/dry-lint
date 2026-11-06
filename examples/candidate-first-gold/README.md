# Candidate-first operation labels (development data)

This first wave contains 41 accepted operation pairs: 20 duplicate families and 21 separate controls, plus 3 unresolved disputes in `disputed.jsonl`. Labels come from model reviewers, source workers and coordinator adjudication, **not human ground truth**. All independent Jev and Claude observations and dissent remain in `reviews/`. `drifted` evidence may support a scoped duplicate; functions are never labelled equivalent as a whole. Full production-extracted functions provide retrieval context only.

This is a selected, candidate-first development cohort. Counts are not population rates, judge accuracy estimates or an unbiased holdout. Initial acquisition targeted 5 positive families and 5 controls per repository; targets bounded manual curation but did not force acceptance or remove extra confirmed negatives. Sampling was purposive and bounded; nomination stopped at acquisition targets, including deferred lead 1665. All confirmed negative controls and unresolved cases are retained. The 20 positive families were distinct under the workers' prior-package/body/operation novelty audits; this is not proof against all transitive clones.

## Portable closure

Each endpoint includes its repository, immutable revision, source path, line range, function digest, file digest, Git blob digest and public source URL. `sources/*.json.gz` contains complete pinned source files and MIT licenses. Reviews link cited files through `portable_source_file`; historical worker artifact digests are provenance receipts, not claims that private artifacts are included. Original worker snippets and opinions remain evidence. Exact operation spans are checked against bundled source; surrounding whitespace, extraction's removed `export`/`default` prefix and terminal semicolon are explicitly normalized for snippet comparison. Raw replay records the exact unnormalized span hash. A worker `body_sha256` may identify the enclosing function rather than an operation span.

Full scoped sparse corpora in `backgrounds/` are pinned by compressed-byte SHA-256 and decoded repository/revision, extraction contract, scope and document count. Do not replace them with just labelled endpoints: that changes IDF and ranks. These are frozen supported-language extraction scopes, not a full consumer checkout or deployment. The manifest preserves extraction limitations, including T3 partial parses and ambiguous competing IDs. Selected endpoint IDs must be unique. Source is inert text; validation never imports or executes target repositories.

## Offline reproduction

From a dry-lint checkout with its dependencies installed:

```sh
PYTHONPATH=src python examples/candidate-first-gold/validate.py --output /tmp/candidate-first-replay.json
```

The package root defaults to the validator's directory; `--root /path/to/copied/package` supports relocated data. Python must run without `-O`. Native `load_gold` import, full-source extraction, hashes, revisions, licenses, backgrounds, unique endpoints and exact operation spans are checked. `replay.json` is raw machine-readable output; `retrieval-summary.json` omits per-row detail. Reproduction uses the checkout's retrieval implementation and installed extractors; it requires no credentials, API, target execution or network.

Ranks use production TF-IDF over frozen token corpora, excluding exact self, with deterministic ties by descending score, source ID, document position. Both query directions are retained. Raw ranks include zero scores; missing/ambiguous selected endpoints fail. Diagnostic default-style retrieval uses top 3 cross-file and floor .5 (.3 for queries shorter than 6 lines). Diagnostic balanced-style retrieval uses top 20, floor .35 and permits same-file pairs. These calculations do **not** replay production discovery, presets, changed lines, rule filters, budgets, verdict reuse, reporting or deployment behavior. A retrieved separate control measures look-alike exposure, not a false-positive finding. Positive misses are diagnostic only; OCH01 is the sole positive pair below the .35 balanced-style floor in this wave.

Summaries include per-label and per-direction numerators/denominators, repository/family counts, query size, floor-only failures, same-file exclusions and first-loss reasons. Directional observations from one pair are dependent. Unresolved cases are replayed separately and excluded from accepted positive/negative counts.

## Candidate-pool retention

Keep the original candidate pools, acquisition metadata, exact revisions, backgrounds, score/rank receipts and decisions in the private research archive, including rejected, unreviewed and unresolved candidates. Do not silently relabel unreviewed candidates as negative or discard controls to improve retrieval results. Future public pool exports must preserve provenance, scope, hashes and explicit review status; compression is allowed. This release includes reviewed pairs and disputes; it does not claim to publish the complete mining pool. Additional batches are separate evidence and require adjudication before entering accepted counts.
