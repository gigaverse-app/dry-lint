# Historical recovery: preserve candidates, then measure funded reports

Halving function-name weights can expose a useful shared operation below the retrieval floor, but preserving old candidates does not guarantee preserving old reports. The completed source-reconstructed comparison gained **two reported positive pairs in one previously studied family**, from 3/5 to 5/5, with no prior report loss. A different guard that retained only one exploration candidate per query lost **19 report versions** against current balanced retrieval, including five independently useful versions. Neither result establishes a generally better production default.

This record closes the earlier frozen-recovery direction: half-name generation, guarded selection, and native protected/refill scheduling. It preserves the actual implementations and final outcomes so future work can distinguish a score-floor improvement from a scheduling, budget, cache, or reporting effect. Keep the half-name channel experimental and reject the one-candidate guard as a default replacement.

## What changed

Names can dominate a whole-function vector even when two functions repeat a useful operation. The tested half-name recipe keeps the original corpus IDF, multiplies every `fn:` component of **both** normalized vectors by 0.5, then renormalizes. It changes vector weights, not token counts, stop words, corpus scope or labels:

```text
original v = normalize((1 + log(term_count)) * original_IDF)
half_name(v) = normalize(v[token] * (0.5 if token starts with fn: else 1))
current = first 20 allowed unweighted neighbors with cosine >= 0.35
extra = first allowed half-name neighbor >= 0.35 absent from current
protected pool = complete original pool + at most one extra per query
```

“Absent” means outside the **floor-qualified** pool, not necessarily outside raw rank 20. Sparse replay preserves production posting-order ties, same-language admission, resolved-position self exclusion and same-file exploration. Source reconstruction additionally applies actual changed-line selection, pair filters and duplicate-key exclusion. Its exhaustive half-vector sort uses stable corpus-position ties. The original and additional candidates are separately ordered by the production campaign; every original candidate precedes additions. Original sources, scores, lanes and filters stay intact. [Original sparse code](archive/sparse/run.py.txt) and [source reconstruction](archive/source-recovery/run.py.txt) retain these differences.

The other arms test related constraints, not the same generator:

| Study | Baseline and intervention | What it can establish |
| --- | --- | --- |
| Sparse half-name (E03) | Current unweighted exploration20 versus that pool plus one half-name alternative | Frozen target membership and score changes; budget/judge/cache remain unknown |
| Guarded capture replay (H02) | Baseline-only; current balanced exploration20; baseline plus the first original unfiltered exploration candidate per changed query/revision | Chronological reports and costs from captured candidate pools; **no name reweighting** |
| Archived native replay (H04) | Fixed asks baseline only; refill can consume the wider archived pool; protected reserves baseline capacity and paces exploration | Native research-scheduler effects under original and fixed $0.04 PR limits |
| Source-reconstructed half-name (H05) | Current20 versus unchanged current20 plus one weighted alternative, replayed from ordinal zero | A source-authenticated eight-revision counterfactual with separate arm ledgers |

H02's guard preserves baseline candidates and scores but removes most current exploration. H04's protected policy reserves 20 of 40 calls and half the PR dollars, admitting at most one exploration call per revision. These are different meanings of protection. See the [exact rerun contracts](REPRODUCTION.md).

## Score examples readers can execute

The bundled inputs contain **actual complete normalized pair vectors with anonymous feature names**, not invented source functions. All original numeric weights and feature intersections are preserved; the `fn:` versus other-feature distinction remains. These three selected diagnostic examples illustrate a gain, a separate control exposed by the same change, and a remaining miss:

| Projection / original source label | Unweighted cosine | Half-name cosine | Passes .35 before → after | Recorded raw → half rank |
| --- | ---: | ---: | --- | --- |
| 1 / provisional duplicate | 0.346130810826832 | 0.444330455836811 | no → yes | 2 → 2 |
| 2 / separate | 0.320188557566692 | 0.393241321007080 | no → yes | 2 → 1 |
| 3 / duplicate | 0.295593307916614 | 0.303037769475022 | no → no | 5 → 5 |

The [runnable transformation](reproduce.py) recomputes the cosines and floor crossings. Ranks and selected-addition flags are recordings: competitors are not shipped, so this package cannot recompute ranks, prove which alternative was first, or infer funding/reporting from these vectors. Token text, source, private identities and prompts cannot be reconstructed from this publication. Projections 1/2 are from an already evaluated reserved split; projection 3 is development. They are illustrations, not a new evaluation set.

## Sparse retrieval result

Pair membership means the labeled target appears in **either direction**. Separate membership is exposure, not an unwanted judge report. Diagnostic/configured profiles repeat the same labels and must not be pooled.

| Cohort / profile / split | Positive pairs: current → protected | Separate controls: current → protected |
| --- | --- | --- |
| Legacy development | 47 → 47 / 48 | 107 → 107 / 110 |
| Mined configured development | 23 → 25 / 48 | 23 → 25 / 128 |
| Mined configured previously evaluated reserved split | 7 → 10 / 12 | 13 → 14 / 54 |
| Mined diagnostic development | 36 → 37 / 48 | 41 → 42 / 128 |
| Mined diagnostic previously evaluated reserved split | 7 → 10 / 12 | 14 → 15 / 54 |

The five configured positive additions are three provisional families, with **zero additional strict-tier positives**. All added positive directions were originally below .35, with raw ranks 2–12. None demonstrates a need for deeper raw retrieval. The challenge has 242 rows, 70 families and 35 positive families; the 14-positive/74-control strict subset is contained within it. The legacy 158 rows have no complete family denominator. Sixty-six background hashes and 2,348 independently reconstructed scores were checked in the original study; unresolved duplicate source IDs and sparse metadata limits remain. [Aggregate recording](recordings/sparse.json).

The separate frozen public audit covered only 37 Due/pytest pairs (21 positive, 13 separate, 3 borderline) across nine snapshots, not all goldens. All 21 positives reached raw top three in both directions. Conditional current-default pair gates reduced that to 19/21 and 18/21; missing adopter settings and competitor metadata prevented a production-recall claim. No full background or public source snippet is copied here.

## Completed chronological reports

The earlier cohorts contain six original histories / 27 revisions; four protected histories / 18 revisions; eleven production captures / 42 revisions; and two regression captures / 16 revisions. These are **23 history records and 103 revision records**, not 103 independent examples or a fresh holdout. H05 reuses one original history and adds no independent PR. The original reference has 9 duplicate / 62 separate / 1 borderline evidence versions; the selected protected captures have 11 / 103 / 7. Eight protected screen-only labels and an old duplicate ZIP extraction are excluded from these replay denominators. Original labels were authored by Codex before live answers, not human gold; later independent model source reviews remain a separate layer.

All H02 arms use explicit laboratory balanced settings: Haiku 5.5, shared-operations v2, output cap 2048, report threshold .5, $0.04 cumulative per PR, $0.025 baseline reserve, $0.015 exploration cap and $0.006 exploration credit per revision. Current balanced uses depth 20, floor .35, same-file exploration. These are recorded comparison settings, not inferred deployed adopter settings.

| H02 cohort / arm | Known duplicate report versions | Separate | Borderline | Unknown | Replayed calls | Charged USD across PRs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Production / baseline-only | 0 | 2 | 0 | 0 | 60 | .0227580 |
| Production / balanced | 16 | 13 | 7 | 0 | 270 | .1320332 |
| Production / guarded | 7 | 4 | 6 | 0 | 156 | .0763877 |
| Regression / baseline-only | 0 | 0 | 0 | 3 | 50 | .0208420 |
| Regression / balanced | 0 | 0 | 0 | 13 | 86 | .0388857 |
| Regression / guarded | 0 | 0 | 0 | 11 | 78 | .0361805 |

All **39 arms completed** after 12 exact fresh observations; 26 baseline/balanced arms reproduced archived reports/costs. Physical continuation usage was $0.0080576, separately from counterfactual arm charges. The frozen 73-row reference alone has 3 duplicate / 68 separate / 2 borderline versions: balanced and guarded each report 3/3, 2/68, 1/2; baseline reports 0/3, 1/68, 0/2. Thirty supplementary reviewed versions remain separately classified in the [recording](recordings/guarded.json).

Against balanced, guarded adds no production report and loses 19 versions: nine supplementary duplicates, nine supplementary separate and one supplementary borderline. Independent review supports five of those lost duplicates (one overlapping default-merge family); four original duplicate labels are disputed (two separate, two borderline). In regression it adds four reports and loses six: independent review finds one useful gain, two separate gains and one borderline gain, and one provisionally useful loss plus five separate losses. The lost useful case has captured source but lacks the required Git head. The complete regression label denominator is absent. Those reports remain “unknown” in the original-reference table, alongside the separate [independent review](recordings/independent-review.json). Neither “zero useful gain everywhere” nor improved population precision is supported.

Against baseline-only the production guard adds seven known duplicate, two separate and six borderline versions with no prior report lost. Recovering the three frozen positives relative to baseline-only is not added recall over current balanced.

The source-reconstructed H05 comparison has eight authenticated recorded merge-base/head diffs. The first two change no extracted functions; each later revision changes 11. Current candidate occurrences are 29/29/29/30/30/30; additions are 2/2/2/3/3/3. Both arms start at ordinal zero with independent ledgers and the same laboratory settings.

| H05 arm | Ever-reported positive pairs | Separate controls reported | Borderline reported | Normal recorded arm usage |
| --- | ---: | ---: | ---: | ---: |
| Current20 | 3/5 | 0/13 | 0/1 | $0.0088656 |
| Protected half-name | 5/5 | 0/13 | 0/1 | $0.0109911 |

**Two pairs gained, zero prior reports lost; incremental arm charge $0.0021255.** These pairs belong to one overlapping task-cleanup family already in the reference, not two new independent gold families. Twenty-five fresh observations cost $0.0109911 physically, with zero rejected responses and no pending funded key. Physical cost and summed arm charges are different quantities. [Final aggregate](recordings/source-recovery.json).

A representative operation cancels each owned task, then awaits the tasks while suppressing cancellation exceptions. Callers still own list clearing, logging, snapshots and lifecycle context; the evidence supports a bounded shared helper, not whole-function equivalence. One motivating target was already exploration rank 3 at .3642923 and merely moved to rank 2 at .4658859. The two actual additions cross the .35 floor: approximately .336881 → .411 at ordinal 2, and .343054 → .436 at ordinal 5. At ordinal 5 the first target instead has .334376 → .408892 and is not the selected extra. The recorded duplicate scores for the two additions are .80 and .72, both above the unchanged .5 reporting threshold. Mixing revisions would fabricate a recovery. Two other added evidence records lack source labels; their membership alone is neither a useful nor a false report.

Early H05 summaries left finding report flags false because the continuation omitted production `Report.build`. The [final coordinator replay](archive/final-report-correction/replay_h05_final.py.txt) applies it and reruns all eight revisions without provider calls. The table uses that **final post-provider result**, not the early zero-report flags. No dedicated adopter TOML existed at these pins; workflow execution and old action defaults remain unproved. Recorded diffs authenticate successfully, while independent ancestry recomputation is limited by missing ancestors. That is not evidence of a bad base.

## Native $0.04 limits are not a normal-estimate simulation

H04 retains the archived Sonnet 5.5 request-reservation policy, report threshold .6, and output cap 8000 (original historical) or 2048 (protected histories). It completes 72 arms / 324 revision rows without a missing selected answer. The primary comparison fixes **$0.04 per revision and per PR**; original $0.15/revision and $0.50/PR runs are sensitivity/reproduction only.

| Cohort / prompt / cap per PR | Fixed positives | Protected positives | Refill positives | Fixed / protected / refill charged USD across PRs |
| --- | ---: | ---: | ---: | --- |
| Original / concept / .04 | 0/7 | — | 0/7 | .000000 / — / .000000 |
| Original / concept / .50 | 0/7 | — | 3/7 | .021360 / — / .245690 |
| Protected / concept / .04 | 2/11 | 2/11 | 2/11 | .036352 / .036352 / .054422 |
| Protected / concept / .50 | 2/11 | 3/11 | 4/11 | .045176 / .093522 / .147458 |
| Protected / shared-operations / .04 | 2/11 | 2/11 | 2/11 | .038112 / .038112 / .038112 |
| Protected / shared-operations / .50 | 2/11 | 3/11 | 4/11 | .091472 / .158968 / .260222 |

Separate reports are zero in all these arms; each protected-cohort .50 refill arm also reports one borderline. These counts are final positive **pairs**. Original historical refill at .50 has 3/7 final pairs, 4/7 ever-reported pairs and 4/9 positive evidence versions. Those numerators cannot be interchanged. [All arm/call totals](recordings/native.json).

The old output reservation alone is $0.08 for 8000 tokens, so no original historical question fits $0.04. The protected output reserve alone is $0.02048, exceeding its $0.02 exploration slice before input. This is a version/budget incompatibility, not proof of absent useful candidates. Five cleanup positives and two other positives are excluded from fixed retrieval; refill exposes them but reservation blocks them at .04. At original limits the two latter pairs still fail judge/reporting thresholds. Additional protected histories lose candidates to pacing/call limits. The [native first-loss partitions](recordings/native-first-loss.json) and [capture first-available stages](recordings/guarded-first-loss.json) preserve these distinctions without private identifiers. First loss must be traced in order: captured-pool exclusion → admission → answer → reporting.

Native admission reserves a conservative request bound and then settles recorded token usage. `costs.estimate` instead uses prompt characters / 2.8 plus 150 expected answer tokens; it cannot replace a native max-output reservation and be called the same policy. External answer-cache hits are charged on first use in **each arm**; subsequent exact chronological arm-local reuse is free. Normal list-price usage charges are not the same as admitting by normal average estimates. The later fixed-candidate native-versus-normal-estimate ordering study belongs to [PR #113](https://github.com/gigaverse-app/dry-lint/pull/113); its histories, malformed-answer censoring and ordering deltas are not added here.

## Cache boundaries, uncertainty and prior coverage

H02/H05 keys bind the exact oriented rendered prompt and judge version. Every lookup also checks source evidence/context, full effective settings, model/output/policy, recorded usage and request provenance; arm-local sidecars enforce those checks on reuse. An unordered pair ID is insufficient. Original archives lack some full provider-settings hashes: compatible capture config plus exact prompt/output identity reconstruct the request-affecting contract, rather than inventing a missing historical hash. A funded missing or malformed answer stops the arm, retaining a reservation upper bound while usage stays a lower bound. An unknown suffix is never scored as negative. Final H02/H05 selected frontiers are complete; sparse downstream outcomes remain unknown. H04's physical cache still contains two paid failures, neither selected in these completed arms.

Discovery reports led to the public background audit and the earlier protected-containment screen already merged in [PR #100](https://github.com/gigaverse-app/dry-lint/pull/100), commit `fb15ecc` (see [the existing research record](../../tfidf-enrichment-research.md#development-screen)). That screen compared 15/48 funded positives and 7/128 separate controls in both baseline and containment, while funded candidate counts rose 88 → 141. It is covered, not a new uncovered method. Its protected name-channel cold-gold batches use a different admission/judge contract; they are not H05 historical results. The later public baseline audit also is not fresh gold. This publication adds the chronological recovery evidence without duplicating those claims or the later ordering direction.

## Reproduce and decide

From this directory, with Python 3.11+ and no installed project dependencies:

```bash
python3 -I reproduce.py --check
python3 -I reproduce.py > result.json
```

This executes the selected public numerical transformation and aggregates the recorded cohort cells, preserving label layers and units. It checks frozen expected outputs and archived implementation integrity. It is **not a private-history replayer** and does not claim to regenerate private provider answers or independently validate private labels. [Reproduction and missing-input contract](REPRODUCTION.md) describes the full original rerun, source pins, licenses, archive redactions and clean-copy validation.

The evidence supports retaining the narrow two-pair gain as a regression/example and keeping the recipe experimental. It rejects the guarded replacement, which sacrifices useful existing reports. Preserving candidate membership is necessary for additive recovery, but sufficient budget, exact reusable answers and actual report assessment must also hold. No production, configuration, CI or threshold change follows from this publication.
