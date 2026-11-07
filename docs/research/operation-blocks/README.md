# Recovering shared operations without mistaking coverage for reuse

Keep the bounded operation-block comparer **opt-in**, and **do not promote the residual-coverage veto** tested here. Comparing small syntax regions recovered a useful helper-reuse opportunity that whole-function retrieval missed. The proposed veto then removed that opportunity and a second useful, actually reported opportunity. This record preserves both the working retrieval recipe and the counterexample to an apparently sensible optimization. It does not establish a gain for dry-lint’s default configuration or its balanced preset.

The problem is a mismatch in granularity. A short helper and a long configuration function can contain the same operation while doing very different amounts of other work. Whole-function TF-IDF—similarity over behavior-token frequencies—can give that pair a low score. The hypothesis was that comparing complete syntax regions would recover actionable reuse inside different workflows, without replacing the existing retrieval baseline or sending fragments to judges. A result consisting only of already-retrieved pairs, nonactionable scaffolding, or unaffordable proposals would not establish added value.

Before this change, the tested discovery recipe used the protected three-neighbour whole-function baseline, then an explicit TF-IDF exploration route with a .35 floor and a raw limit of 20. The new route appends at most one previously unseen, unfiltered pair per query. A **query** is one changed function; a **pair** is the query and an indexed function. A **family** is the shared operation or contract connecting related pairs, not another name for a directional query.

The new comparer extracts whole compound statements, such as a `try` block, and maximal consecutive straight runs. It never slides windows through oversized code or includes a nested function’s/class’s body in its parent region. It fits weights to the same complete function-token background as the baseline. Rare concrete calls, attributes and keys act as **anchors**: they restrict which parent functions need comparison. The returned Candidate still contains the complete native functions, including signatures, documentation and context.

```text
existing = protected_baseline3(query) + explicit_tfidf20(query)
regions  = bounded_syntax_regions(query)
parents  = bounded_anchor_lookup(regions)
extra    = first_guarded_parent_not_already_in(existing)
return existing + full_native_pair(extra)
```

The fixed limits are 12 regions per function, 8 anchors per region, 64 postings per anchor and 64 candidate parents. A region spans 4–80 lines and 20–400 executable syntax nodes. It needs eight distinct behavior tokens and two nongeneric calls. A match needs three shared concrete operations, two shared calls and a retained shared anchor; its region cosine must reach .65 and whole-function cosine .1. Common postings are discarded rather than truncated. Parent deduplication and ties are deterministic. Scores have the separate identity `operation-blocks:1`; they are not substituted for unrelated TF-IDF scores. The [production implementation](data/original/product/src/dry_lint/operation_blocks.py.txt) and [opt-in configuration](data/original/README.md) contain the complete recipe.

The concrete success is token-error handling in LiteLLM. An existing helper fetches an access token and translates `GetAccessTokenError`. A longer Responses configuration function repeats that translation in its login branch. The whole-function score was .347608, just below the .35 exploration floor; the region score was .976964. In the exact same query/background and synthetic .04 budget, TF-IDF-20 did not retrieve or fund this pair, while the appended block pair was funded. Sonnet’s shared-operations answer qualified for a report at .80. Independent source review accepted **reuse of the existing token-or-error helper**, preserving the exception type, provider/model/message, chaining, bypass behavior and caller headers. It did not accept merging the configuration functions, headers or credential-selection branches. This is a useful newly retrieved pair, not evidence that the whole functions are equivalent (authentication helper/Responses login, RF14).

Here, a “report” means an observed answer satisfies the specified reporting rule and its pair is admitted in the stated replay. It is not a claim that a deployed pull request emitted it. RF14’s exact original **concept-policy** answer was prepared but not run; it remains unknown after the call stop. The shared-operations answer is not a substitute.

The experiment used exact repository/revision/extraction-scope backgrounds, never concatenated revisions. The archived inventory contains 617 records and 79 backgrounds. Of 580 accepted function records, 483 were supported Python records and 103 had source sufficient for evaluation; 380 supported records remained missing. Four accepted model declarations are outside this Python-function method. The conditional archived comparison deduplicates directions and lineage into pair-with-background units, not independent families:

| Archived synthetic .04 funding outcome | Baseline3 + TF-IDF-20 | Plus original block route |
|---|---:|---:|
| Accepted duplicate pairs funded | 35/39 | 37/39 |
| Accepted separate pairs funded | 35/80 | 38/80 |

These are **funded exposures**, not emitted reports: the method bought both positive coverage and more separate-pair judging. Family intervals and missing denominators remain in the [archived paired evidence](data/evidence/full-corpus-followup/span-v2-migration/paired-summary.json). All of this is development/regression data, not a pristine holdout.

The subsequent paid discovery used the pinned public LiteLLM and OpenHands SDK corpora. Production parity checks matched the frozen region extraction and 250 eligible scores across 148 saved queries. Round 1 then answered four novel pairs and twelve separately sampled baseline controls, with both Jev/context and Sonnet/shared-operations/1024 at a .80 report threshold. The other 32 novel pairs—64 requested answers—were unstarted and remain unknown. Independent review supported RF14 and three baseline controls: timeout normalization, UTC normalization and asynchronous dispatch. The controls were already baseline proposals; they are not added retrieval recall. Two of those controls qualified for Sonnet reports; the asynchronous control’s .72 answer did not.

Two previously reviewed workspace-tool method pairs also received exact Sonnet concept-policy answers at the production default 8,000-token limit. Both scored .90, and two known separate controls stayed below the report threshold. But both positive pairs were already TF-IDF-20 funded. They demonstrate no incremental gain against that baseline, and represent one family, not two independent discoveries. The limited baseline3 diagnostic gains must not be called production-default gains.

The one revision tested a **residual-coverage veto**. Before anchor lookup, it removes a query region when one scoped region in an already-retrieved baseline neighbour contains all its concrete-operation tokens and passes the unchanged .65 guarded comparison. Retrieval then uses only the remaining regions. This changed eligibility, not tokenization, weights, thresholds, budgets or source boundaries. Its rationale was to avoid paying for operations already represented in whole-function neighbours; its declared risk was losing useful additional copies. It was not tuned to keep RF14.

A full cached-source sweep covered every native function in the two announced public backgrounds, not only the initial sampled queries:

| Stage | Count and unit |
|---|---:|
| Complete background documents | 39,952 functions |
| Native source with valid spans | 39,806 functions |
| Missing/ambiguous native source, retained as token-only competitors | 146 functions |
| Queries with eligible syntax regions | 13,694 queries |
| Queries with retained rare anchors | 13,256 queries |
| Original / residual route selects an extra | 1,132 / 692 queries |
| Residual extras pass normal concept / operations funding | 240 / 187 queries |
| Affordable replacements satisfying both funding checks | 1 query |

Of the rare-anchor queries, 654 kept the same winner, 442 lost the original extra, 36 changed winners and 2 gained a winner where the original had none. The initial held-out slice’s zero funded replacements was therefore **not** proof of source exhaustion. The single affordable replacement is an unjudged selection/funding result, not added useful recall. The sweep reused exact fitted indexes and cached regions. It took about 297 seconds including missing-baseline derivation and funding checks; the smaller fixed-split run took about four seconds. These are offline audit timings, not an isolated production latency benchmark or a speedup claim.

Round 2 consequently judged a declared **rejection audit**: original, actually funded questions excluded by the fixed gate, plus separately sampled baseline controls. Thirteen audit pairs and twelve controls used the primary baseline3 + TF-IDF-20 profile. Four fresh supplemental audits used the other original frozen **default3 diagnostic** profile, with its matched baseline3 input and cross-file policy. That supplementary profile is neither discovery defaults nor balanced. All 29 pairs received both answers. None of these audit answers is credited as a new residual proposal or emission.

| Source-reviewed report-bearing case | Original diagnostic report | Residual counterfactual | What the evidence supports |
|---|---|---|---|
| Token-error helper reuse in Responses login | Sonnet .80 | Removed | Useful scoped opportunity lost; native concept outcome unknown |
| Reuse existing atomic commit helper in CLI file replacement | Sonnet .80; Jev .85 | Removed | Useful report lost under the actual matched diagnostic policy |
| Timeout coercion in batch/file API wrappers | Sonnet .80 | Preserved | Existing useful baseline report retained; no added recall |
| Guardrail deadline versus relay-resource cleanup | Below reporting thresholds | Rejected | Related scaffolding, not actionable nominated-body consolidation; no false report demonstrated as prevented |

The atomic-file opportunity is modest but concrete: reuse the existing staged-file commit operation, roughly five lines of atomic replacement and failure cleanup. Keep UTF-8 text staging, same-directory placement, file mode and flush/fsync behavior local. Preserve `OSError`-only cleanup/rethrow; do not substitute a higher-level JSON writer. These source distinctions matter more than the two functions merely sharing file APIs (atomic-commit audit, RRC10). The timeout control similarly supports only timeout coercion, not merging batch and file request handling (RRC11). The deadline/relay assessment remains **related**, not relabeled as a binary duplicate or separate pair (RRC12).

The useful atomic-commit report and the useful timeout-control report are **actual answered questions**. Their preservation/suppression above is a counterfactual of the frozen selector and reporting rule, not a second paid judgment or a deployed PR measurement. Two provider positives on the same atomic-commit pair are one lost pair, not two independent losses. These are losses of the nominated pair opportunities; recovery of every affected family through other reports was not measured. Other source outcomes remain unknown. In the reviewed report-bearing cases, the veto has no demonstrated false-report prevention to offset the useful losses.

The causal lesson is narrower than “blocks work” or “residual retrieval fails everywhere.” Whole-function similarity can miss an actionable operation. Conversely, an operation appearing in a baseline neighbour does **not** establish that the nominated caller already delegates to the right existing helper. Token coverage is representation evidence, not a consolidation decision. Turning it into a hard veto removed useful opportunities in two distinct reviewed operation families. For the authentication helper, a baseline region scored only .6715 but still triggered the veto against the .977 match; no threshold was adjusted to rescue that case. The related asynchronous case shows why shared APIs alone also cannot establish usefulness; the judge was already withholding that report.

Keep the original bounded plugin available for explicit exploration, with its existing guards and unchanged budget defaults. Preserve the original useful audit report and the already-baseline timeout report; neither an audit finding nor a preserved baseline report is a new residual emission. Do not enable it by default or promote this residual veto. The next integration step is the opt-in implementation and this record, not another parameter search. Any later default-rollout decision would need matched configured-judge answers and actual campaign histories.

In particular, discovery is off by default. The **balanced** preset enables implicit TF-IDF-20, uses Haiku/shared-operations/2048 at .50, and paces exploration through a persistent ledger; it does not automatically enable blocks. Explicit balanced-plus-blocks cold-admission bounds admitted the four observed novel proposals, but no matched Haiku answers or real revision ledger were supplied. Regional scores can also reorder exploration: the held-reservation diagnostic displaced 20 exploration admissions while preserving the protected baseline. Those are accounting displacements, not measured lost reports. Sonnet/shared-operations/1024/.80 and Sonnet/concept/8000 observations establish neither balanced emissions nor a default-policy recall gain.

## Reproduce the selected source and recorded decisions

The [machine metrics](data/metrics.json), [29-pair round-two table](data/paired-round2.json), and [four selected public-source recordings](data/recordings.json) preserve the original observations, scoped source decisions, funding and counterfactual veto. [Representative original answers](CASES.md) make the useful helper reuse and related cleanup contrast inspectable. [Original implementation/configuration](data/original/README.md) includes region extraction, guarded comparison, residual veto, all original evaluation programs and dependency locks, archived as data to prevent import side effects.

Run from this directory with Python 3.11+:

```bash
python3 reproduce.py --output /tmp/blocks-recorded-results-NEW
python3 native.py
python3 audit.py
python3 reproduce.py --case OBR1-cd803a8002adba3e
```

`reproduce.py` revalidates source spans and exact rendered inputs, parses recorded answers, recalculates report eligibility and the original/residual projection, and recomputes the two reviewed useful losses. `native.py` executes the original `_blocks`, `_regions` and behavior tokenizer function ASTs against eight selected source functions; all 25 region token/count/operation records match the frozen capture. It does not refit TF-IDF on the selected functions or pretend to reproduce full-background anchor competition. There are no model calls, new encoding, source mutations or new experiments.

The [full rerun manifest](FULL-RERUN.json), [exact corpus lookup/acquisition](CORPUS.md), [source and dependency instructions](REPRODUCTION.md) and [provenance](data/provenance.json) distinguish this small portable reproduction from a complete rerun. Both exact public sweep backgrounds are available from the separate goldens repository; native source still needs the pinned repositories. Private historical aggregates are anonymous, with no source-bearing prompts or identifiers. The selected full files are licensed public OSS and retain [license notices](licenses/). Exact RF14 concept and balanced Haiku answers remain absent.

The physical spend bought the above observations: round 1 used **$0.22461896** in fresh owned calls, including the exact four-question concept supplement; round 2 used **$0.22776080**. Cache hits and older pre-promotion spend are excluded. These amounts are separate from simulated .04-per-query admission. The remaining unexecuted reserve and missing RF14 concept/Haiku answers stay unknown. Both funded rounds are closed; **no further provider calls are authorized or needed for this decision**.
