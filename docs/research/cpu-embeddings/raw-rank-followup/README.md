# Complete-tail recall under the production budget scheduler

**Current implementation decision (7 November 2026):** [PR109](https://github.com/gigaverse-app/dry-lint/pull/109) now exposes the complete CPU recovery stack as a supported opt-in configuration. Compatible routes automatically share one encoder and prepared block index, preserving candidates, prompts and native admissions on all 66 selected and five shared campaigns. Warm full-stack time falls 8.47→7.65s and 13.57→10.00s on two small snapshots; peak memory falls 21–23%. One gain-sized T3 pair improves 87.46→75.25s. Cold inference remains expensive and no new recall claim follows from this optimization. Prefix-only CPU remains experimental. The [enablement study](https://github.com/gigaverse-app/dry-lint/blob/feat/research-recall-promotion/docs/enablement-results.md) supplies paired costs, limitations and a portable reproducer; earlier measurements below remain distinct.

Use the raw reciprocal-rank score recipe as a narrow opt-in increment, implemented in [PR109](https://github.com/gigaverse-app/dry-lint/pull/109) with separate parity and performance checks. In the frozen selected single-query panel it added three source-supported, useful bounded-operation reports and three tiny-operation reports, with no unsupported added reports and no lost reports. The useful additions cover three source-described operations in two repositories. All three belong to previously reviewed broad directory families: this is development evidence, not independent-family confirmation. Five shared campaigns had zero gain and zero loss with raw RRF. No default rollout or deployment claim follows from this experiment.

The original tail append and origin-cosine RRF recipes should not ship in their tested form. Both lost two known accepted-positive pairs under the unchanged production scheduler. Their candidate selections were identical in the judged panel, so their gains do not establish a fusion advantage.

The motivation was a specific retrieval omission: a 256-token prefix embedding can miss a complete operation near the end of a long function. Complete-tail-statement views retrieve that overlap. They still send the canonical function body to the judge. Appending a candidate does not preserve funding: `CampaignStore.order` globally orders the combined pool before reserving credit. A high tail cosine can displace an earlier candidate. The raw-RRF successor retains the same bounded union and selection, but scores it by its genuine rank sum instead of an origin cosine.

| Frozen recipe | Candidate selection and score | Native scheduler |
|---|---|---|
| current109 | TFIDF top3, explicit TFIDF top20 at .35, operation-blocks v2 unseen top1, original prefix CPU unseen top1 at .65, in that order | Unmodified full-pool order then reserve |
| tail_append | One unseen complete-tail candidate at .80 after the full baseline; tail cosine | Same |
| fixed_rrf | First candidate from block/tail top20 union, ordered by sum of `1/(60+rank)`; score is selected-origin cosine, blocks win overlaps | Same |
| fixed_rrf_raw | Same rank ordering; score is the actual rank sum, at most `2/61`, rounded to three decimals by Candidate | Same |

All fusion versions are explicitly identified and non-reusable. No fabricated cosine, score rescaling, campaign peek, threshold retuning, or admission-aware selector is used in either stateless RRF arm. The earlier admission-aware selector is diagnostic only. A raw score naturally follows baseline exploration scores in one query; query fairness can still displace candidates in shared campaigns, which is why actual route-major `Detector.candidates` pools were tested.

The immutable runtime is PR109 `5583bb1d3ad8deb22ab45642782988f6deae79e3`. The installed optional profile is not evidence that adopters deploy it. Primary policy is native balanced Haiku 5.5, shared-operations, output 2048, report/drop/drift .50/.50/.80, no escalation, separate .04 ledgers. Native results are cold, held reservations, not sequential settled provider execution or actual PR history. Normal estimated-cost admissions are exported separately.

| Matched panel, each original arm separately | Bounded reports added | Bounded reports lost | Tiny added / lost | Unsupported added / lost |
|---|---:|---:|---:|---:|
| First 27 selected queries | 5 | 1 | 3 / 1 | 0 / 2 |
| Continuation 37 selected queries | 5 | 6 | 2 / 2 | 1 / 0 |
| Two known-gold loss queries | 1 | 2 | 0 / 0 | 0 / 0 |
| Five actual shared campaigns | 2 | 0 | 0 / 0 | 0 / 0 |
| Raw-RRF successor, all 66 selected queries | 3 | 0 | 3 / 0 | 0 / 0 |
| Raw-RRF successor, five shared campaigns | 0 | 0 | 0 / 0 | 0 / 0 |

Panels overlap in pairs and operations; do not sum them as independent evidence. Unsupported combines source judgments `alreadyshared`, `related`, and `separate`; tiny is kept separate from meaningful bounded extraction. Provider reports are outcomes, not source labels. Raw RRF admitted 16 additional canonical pairs: 3 bounded, 4 tiny, 6 alreadyshared, 2 related, 1 separate. All three bounded pairs reported. The sealed source review, exact answer, and per-arm admissions are in the data asset.

Across the accepted-positive historical contexts, the original arms changed prior16 native funding from 70/78 to 68/78. Raw RRF restored 70/78. Recovered14 stayed 52/56 for all arms. These are funding counts, not newly judged successes. Both known original losses were paid and independently source-reviewed; both reported bounded operations. The first failing constraint was the .006 revision exploration credit, not total .04 spend or a call cap. Normal estimated admissions did not reveal these losses. Exact holds and remaining credits are in `gold-loss-first-constraint.jsonl`.

For a concrete mechanism, the T3 portal host registration pair (HYB1-021) had full-background TFIDF rank 1 but score .305149, below the explicit .35 floor. Its prefix cosine was .607836, while a complete-tail comparison reached .833559. The opencode manual-permission visibility pair (HYB1-044) had TFIDF rank 4/.291156 and prefix .649682, just below .65; the tail score was .822352. The shared operation can be extracted while caller-specific error and permission boundaries remain at the callers. HYB1-055 is the counterexample: a useful home-session-opening report was displaced by a higher-scored tail candidate. Exact spans, view texts, cross-view cosines, ranks, source proofs, and budget paths for all three are in `worked-examples/` in the data asset.

The independent Sonnet diagnostic used output 1024 and report threshold .80 on only the first 35 questions. Each original arm added one bounded and one tiny report and lost one bounded report under that diagnostic. This does not replace or retune the primary .50 Haiku policy. Jev is diagnostic, never a gate; its canonical 8000-character input bound persists. Full Candidate preservation does not imply full Jev rendered-body coverage. The per-kind coverage exports retain that distinction.

`COVERAGE.json` defines the denominators. All **338/338** compatible row-background contexts were evaluated, including the two known losses; 336 is not the coverage denominator. They represent 282 row IDs, 310 pair-background identities, 676 correlated directional contexts, and 524 distinct query inputs. There are 309 effectively accepted contexts and 29 unresolved/unaccepted contexts, including the reopened-label overlay. All 193,399 background documents and 699 unresolved native identities were retained across 30 backgrounds. Unknown identity excludes admission, not IDF membership. These full 30-background matrices include private inputs and are unavailable publicly; only numeric summaries are included here. The four public pins contain 72,740 documents, including 493 unresolved identities, and 149 gold contexts. The runnable selected panel has 66 single-query inputs, five groups of four changed queries, 142 recorded original/successor pool versions, and 497 primary arm ledgers. None of these are independent-family sample sizes.

Discovery used frozen label-independent query order and exclusions, prior unjudged pools, and up to 300 new positions per repository. Already completed reused scans were retained; LiteLLM was explicitly capped at its first 300 registered positions plus all matched gold queries. Exhaustive remainder was deferred. The complete primary replay evaluated 2,789 unique query inputs across 30 backgrounds. The selected discovery/control panel contains 48 novel-pair selections and 16 independently selected controls; the two subsequent known-loss query campaigns are non-novel. Two strict TypeScript whole-file failures remain unknown retained controls, without replacement. They are not hidden gains or losses. Native non-strict extraction can retain their functions even though strict source validation rejects the enclosing files.

A pair is an unordered repository-bound pair of canonical function identities and body hashes. A source-described operation family is the reviewer's description of an extraction contract. A prior-directory exclusion family is the broader repository plus directory grouping used before source review. Those family definitions are not interchangeable. Prior reviewed endpoints/pairs/families cannot become fresh confirmation merely because a reviewer was unfamiliar with them. For boosting, the relevant residual candidate union contained only two labeled negative pairs and zero positive families. The larger accepted-label corpus alone did not support training a residual selector with leakage-safe independent positive families. Fixed interpretable fusion remained primary.

The root executor independently verified **all 64 successor requests** against actual previous paid observations, comparing every request identity field except Candidate SHA and allowing only the documented comparer/similarity/reuse/lane/parent Candidate differences. They are derivative mappings, not new observations. Successor fresh calls and new spend are both zero. Each arm still bears its complete logical charge. The full study used 259 fresh physical calls for $0.48353090; Sonnet diagnostic cost is included. There were no provider errors or unknown provider answers. This worker made no provider calls.

This small folder contains the runner and results. The data archive is [published as a versioned release](https://github.com/gigaverse-app/dry-lint-goldens/releases/tag/combined-recall-data-v1-20261107) in **private** `gigaverse-app/dry-lint-goldens`; authorized repository access is required. A public reader cannot download it without that access. [DATA-RECEIPT.json](DATA-RECEIPT.json) records its exact SHA256 and layout. Bulk vectors, source and selected provider recordings stay outside the dry-lint git history. These are research observations, not a new accepted-gold release.

With authorized GitHub CLI access, obtain the exact archive:

```bash
gh release download combined-recall-data-v1-20261107 --repo gigaverse-app/dry-lint-goldens --pattern combined-recall-data-v1.tar.gz
python3 -c "import hashlib; print(hashlib.file_digest(open('combined-recall-data-v1.tar.gz','rb'),'sha256').hexdigest())"
# Expected: 216fb0de00c490cea71c924f3c4db65c6fa46477b9549bf321624190d79633bc
tar -xzf combined-recall-data-v1.tar.gz
```

With Python 3.14 and the listed dependencies installed, run:

```bash
python -m pip install -r requirements.txt
python replay.py --data-dir /path/to/combined-recall-data-v1 --output-dir /path/to/new-replay
python replay.py --data-dir /path/to/combined-recall-data-v1 --output-dir /path/to/new-retrieval-replay --retrieval
```

The first command re-executes actual native ordering/reservations, separate normal ledgers, strict full-file extraction/body proofs, full-source Haiku rendering, successor request equivalence, canonical reparsing of primary and diagnostic reply text against recorded verdicts, and source/report joins. The second also reconstructs every selected single/shared pool from the complete four pinned backgrounds and frozen prefix/tail vectors, including unknown documents and frozen IDF. Neither calls a provider or acquires a model. The output directory must be fresh. Native runtime modules are loaded from the pinned `runtime.zip`, not an installed dry-lint. The compact experimental adapters memoize only exact already-indexed input objects; the actual product plugin and its independent performance/parity audit are separate.

The data asset contains full source files for all judged endpoints and cited helper evidence, complete public function corpora and vector arrays, exact rendered request identities, recorded answer text/parsed verdicts/usage/cost receipts, full Candidate versions, per-arm ledgers, sealed source decisions, derivative reuse mappings, and source license notices. Provider transport headers, credentials, signatures, and diagnostic logs are excluded. LiteLLM's root license has a separate enterprise clause; no `enterprise/` functions occur in the included corpus. Root and nested license notices are retained in `licenses/`. Frozen vectors reproduce retrieval; fresh encoder inference and unavailable private backgrounds are not reproduced by this kit. Provider responses are replayed as historical observations, never regenerated or presented as deterministic future answers.

The measured full replay passed all 497 reconstructed arm pools, 4,117 reservation events, 210 full-source Candidate/prompt checks, and 64 successor reuses in 130.92 seconds on the research host. The final additive check reparsed 112 primary and 35 diagnostic answer texts and verified all 294 final manifest entries. `REPLAY-RESULT.json` and `FINAL-ADDITIVE-CHECK.json` distinguish those checks. Root owns a fresh clean-copy run and release publication.

The published Python is formatted for reading; parsed ASTs are identical to the frozen worker scripts. [Publication provenance](PUBLICATION-PROVENANCE.json) binds both versions. The coordinator also ran the copied package against a fresh archive extraction outside the lab checkout; see [the full clean-copy result](COORDINATOR-REPLAY-RESULT.json). A second run in a fresh environment installed only from `requirements.txt` also passes the source, prompt, answer and native-budget checks: [isolated result](COORDINATOR-ISOLATED-RESULT.json).
