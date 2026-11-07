# Contextual operation tokens: stop these two recipes

dry-lint can miss repeated operations when their code uses different vocabulary. We tested whether small, mechanically derived operation descriptions could improve candidate retrieval while keeping the original code evidence. The tested recipes produced no substantial useful added report. Close them and preserve the minor reuse example and counterexamples below.

The baseline uses **term frequency–inverse document frequency (TF-IDF)**: rare code tokens contribute more to similarity. The first recipe recognized eager transform-and-collect and owned file cleanup, then added at most 12 operation/contract tokens per function. We compared unweighted addition with separate normalized fields, `score = code + α(1 − code)concept`, at α=.10/.20. Original symbols and qualified APIs stayed visible.

Generic overlap still matched reading with writing, JSON with YAML loading, and incidental file handling inside unrelated policies. The sole revision bound the complete contract, resolved payload calls, literals and control shape into one **conjunctive signature**: for example, `cleanup + read-mode + json.load + return-shape` must match as one key. Unknown policy or calls caused abstention. It then appended one exact-signature candidate **after funding baseline candidates**, qualifying through key equality even below the original code floor. This changed both representation and admission; their individual effects were not isolated.

The inventory contains 617 development/regression records across 79 exact revision/scope backgrounds. Of 584 accepted records, 580 concern functions and four are unsupported declarations. Twenty-five backgrounds have complete source: ten nonempty representations were updated and 15 zero-rule contexts reused baseline. Fifty-four source-missing backgrounds remain explicit. A comparison case is a source pair in one background; related operations form families, and repeated directions/scopes are correlated. These were offline comparisons and synthetic single-function budget simulations, not deployed pull requests.

| Matched wider, same-file policy | Baseline → recipe | Gains / losses |
| --- | ---: | ---: |
| Generic-tag recipes: positive pairs admitted to judging | 61 → 61 / 72 cases | 0 / 0 |
| Conjunctive channel: positive pairs admitted to judging | 61 → 61 / 72 cases | 0 / 0 |

The revised retrieval comparison is also unchanged, 80→80/91 cases; funding covers 57 known family blocks. Missing-source and unknown-admission cases are excluded from these matched denominators. The wider policy considers 20 candidates, allows same-file matches and uses a .35 original-code floor; the default considers three cross-file candidates with size-dependent floors.

Paid discovery returned 24 novel pairs/eight controls for the original recipe and 16 novel pairs/12 controls for the revision. The revision emitted one added pair: a default-permissions wrapper repeats an enum-to-string comprehension already implemented by a helper in the same class ([pinned helper](https://github.com/BerriAI/litellm/blob/fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f/litellm/proxy/management_helpers/team_member_permission_checks.py#L48), [wrapper](https://github.com/BerriAI/litellm/blob/fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f/litellm/proxy/management_helpers/team_member_permission_checks.py#L245); CTR2-012). Independent source review retained this as **minor existing-helper reuse**, not a substantial useful report. Its .17225 code score missed the original floor; same-file exclusion prevents default-policy emission. No original arm funded it in either direction.

The [image and binary validation tests](https://github.com/OpenHands/software-agent-sdk/blob/344ec8a9c30dff0a4ca200fc412510aad44e1bdc/tests/tools/str_replace_editor/test_file_validation.py) exercise different byte fixtures and remain separate (CTR2-035). Jev's .83 verdict falsely emits in both baseline and revision. Three useful baseline controls concern stored-tag serialization and two edges of one Model Context Protocol error-envelope family; they add no retrieval gain. Their original Jev policy does not emit them.

**Decision: STOP_THIS_VARIANT.** Complete signatures removed inspected partial-tag matches, but local operation similarity still did not establish substantial independent ownership. Funding preservation is verified; complete pull-request report recall and production precision were not measured. Keep production unchanged, publish this record, and run no third variant or extra paid calls. Learned associations and broader operation vocabularies remain untested.

**Evidence appendix.** [Final source/policy join](data/evidence/final-source-decision.json) distinguishes the minor emission, unchanged false control and unknowns. [Original](data/evidence/original-metrics.json) and [revised](data/evidence/revised-metrics.json) frozen metric snapshots preserve the comparisons. From this directory, run `python3 data/evidence/verify_evidence.py`. Root-attributed paid usage is $0.21678424 and $0.22040344; the first supplied feed proves $0.17597860, with $0.04080564 awaiting its additional ledger binding. These costs are separate from the simulated .04 Jev budget. Twenty-three unstarted novel pairs/four controls remain unknown. The revised gold update took 113 seconds and 1.24 GiB peak process memory from cached sources; incremental production overhead was not isolated. Exact full-corpus replay requires coordinator source/background archives and scripts; hashes cannot reconstruct them. Verification here makes no provider calls.


## Run the portable study package

This publication adds exact selected-input transformation replay and recorded-answer scoring to the frozen report above. It keeps original artifacts in `data/evidence/` unchanged, including historically pending fields. [Final source interpretations](data/final-source-decisions.json) are a separate update; provider answers never substitute for them.

From this directory, using CPython 3.14.4 (the original AST-dump contract) and only the standard library:

```sh
python3 transform.py
python3 reproduce.py replay
python3 reproduce.py audit
python3 reproduce.py inspect CTR2-012 --part prompt
python3 reproduce.py inspect CTR2-012 --part answer
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


The selected transform executes the original `features`, `Resolver`, and conjunctive `derive` definitions directly from the inert archive against complete pinned Python files. It reproduces the enum-projection signature on both sides of CTR2-012. The binary/image tests in CTR2-035 share the generic owned-file-cleanup tags but produce different full signatures. This is an actual AST algorithm replay, not a comparison of copied key strings. `python3 aggregate.py` additionally reconstructs all eight qualified paired retrieval/funding comparisons from 865 anonymized directional records.

The answer-to-decision trace matters. For CTR2-035, Jev returns `.83`, `duplicate`, and “One portable domain concept can share an implementation”; the unchanged rule emits in both arms. Claude returns `.20`, `separate`, explaining that different byte fixtures cover different scenarios. Root source review accepts the functions as separate, so this is an unchanged false baseline control, not a new conjunction-induced error. For CTR2-012, both source bodies reproduce the same enum projection key, but source review limits the win to **minor existing-helper reuse**. Use `python3 reproduce.py inspect CTR2-012 --part answer` for the complete original answers, and the same command with CTR2-035 for the failure.
