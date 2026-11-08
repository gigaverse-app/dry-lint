# Combining retrieval signals: more funded candidates, no observed new reports

**Current implementation decision (7 November 2026):** [PR109](https://github.com/gigaverse-app/dry-lint/pull/109) now provides one supported CPU recovery configuration and shares resources across its compatible routes. Exact output/admission parity holds on the 66 selected and five shared campaigns. Warm full-stack time falls 9.7% and 26.3% on two small snapshots; gain-sized T3 is still 75.25 seconds in one warm measurement. This improves usability and execution cost, not predictive ensembling: tail and fused selection remain identical in the judged panel. The [enablement study](https://github.com/gigaverse-app/dry-lint/blob/feat/research-recall-promotion/docs/enablement-results.md) links the new portable reproduction and private evidence release. The earlier studies and their negative conclusions below remain separate.

**New implementable follow-up:** [complete-statement retrieval with raw rank fusion](raw-rank-followup/README.md) adds three useful reports without lost admissions in 66 selected single-function campaigns, while five shared campaigns show no gain. It uses the actual scheduler and differs from the original protected-first experiments below. The evidence supports representation and budget ordering, not an independently demonstrated fusion advantage.

A repeated operation can occupy only a small part of a function and be diluted by whole-function token similarity. This study combined the existing sparse retriever with guarded operation blocks and dense embeddings, then tested learned ranking and a stricter operational gate. The question was whether complementary signals would produce more independently useful reports within the same judging budget.

**Do not promote the learned replacement, universal two-slot combination, or revised gate.** Across the answered paid panels there were no incremental reports. Twenty-eight novel questions remain unanswered; they are unknown, not negative. The simpler one-block add-on after explicit TF-IDF20 remains supported by a small static funding gain, while cached dense retrieval remains opt-in for the small baseline. Neither recommendation establishes new paid report recall.

This publication preserves actual implementation, exact public questions and answers, paired outcomes, source decisions and a runnable original gate example so later work can distinguish retrieval gains from reporting failures.

## What changed

The small baseline proposes three cross-file TF-IDF neighbors per changed function, at cosine ≥0.50, or ≥0.30 below six actual source lines. The wider profile adds the existing same-file-eligible TF-IDF20 exploration at ≥0.35. Those profiles stay separate; both preserve their complete original candidate order and fund it before extras.

```text
BEFORE: complete sparse baseline -> original $0.04 allocation -> unchanged judge
R1:     same baseline -> up to two alternating block/dense extras -> remaining budget -> same judge
R2:     same baseline -> one profile-routed, operation-gated extra -> remaining budget -> same judge
```

R1 alternated guarded blocks and dense candidates, deduplicating exact unordered native parent pairs across directions. Blocks required cosine ≥0.65, parent cosine ≥0.10, three shared operations, two shared calls and an anchor; dense candidates required cosine ≥0.65. Scores from different representations were never added as though calibrated. No source labels, gold IDs or provider answers selected candidates.

Four new R1 novel answers described generic workflow resemblance rather than the same operation. That motivated one preregistered revision: R2 kept dense order for Default3; after TF-IDF20 it used guarded-block order with dense corroboration. Its gate required three shared concrete call/attribute/key tokens, two shared calls, at least one rare shared operation, IDF-weighted containment ≥0.35, parent cosine ≥0.10 and dense cosine ≥0.65. Rare meant document frequency ≤`min(64, max(2, ceil(.002*N)))` in the exact full background. Generic built-ins and logging tokens were excluded. A same-file, same-owner direct-call suspicion caused abstention. It allowed one extra per query, with no tuning after the answers.

The [original gate](data/archived-code/funded-rounds/round2/operation_gate.py.txt), [R2 producer](data/archived-code/funded-rounds/round2/prepare.py.txt), [native-order combination](data/archived-code/promotion-combination/native-order-v2/run.py.txt), and [learned fitting implementation](data/archived-code/learned-ensemble-v1/fit_oof.py.txt) are archived as inert text. [Tested specifications](data/specifications.json) retain the original recipes. The portable [algorithm command](algorithm.py) executes the original gate's methods over a compact projection of its exact 37,604-document background state; it does not refit IDF on two snippets.

## Evaluated units and paired results

The shared inventory contained 617 records in 79 exact repository/revision/background scopes. The final gate replay assessed all 79 and supported 16 compatible frozen-cache backgrounds; the other 63 were missing representations or had no function queries. Four declarations stayed separate, and a reopened disputed record was excluded. The inventory is not the evaluated denominator. Paid discovery searched pinned LiteLLM and OpenHands backgrounds, with source-file/family separation for the revised panel and independent baseline controls.

A canonical pair is an unordered pair of native functions. A family groups related operations and overlapping endpoints. A scope unit is a labeled pair in one exact background; repeated views are correlated. A paid case is one frozen candidate with canonical Claude and diagnostic Jev observations. These are development/regression comparisons, not independent random trials or deployed traffic.

The decisive static comparison is the intersection supported by both frozen R1/R2 arms. Positive means an accepted duplicate or drifted operation, including partial operations. Funding means eligible to ask the judge, not an emitted report.

| Profile / label | Scope units / pairs / families | R1 two extras funded | R2 one gated extra funded | Additions / removals |
|---|---:|---:|---:|---:|
| Default3 positive | 77 / 77 / 67 | 42 | 43 | +1 / 0 |
| Default3 negative | 119 / 103 / 76 | 32 | 28 | +2 / −6 exposures |
| Default + TF-IDF20 positive | 75 / 75 / 65 | 62 | 61 | 0 / −1 |
| Default + TF-IDF20 negative | 118 / 102 / 75 | 52 | 51 | 0 / −1 exposures |

Higher positive funding and lower negative exposure are desirable, but neither measures report accuracy. Against its own baseline, R2 funded 44 versus 37 positives on 78 matched Default3 pairs and 64 versus 64 after TF-IDF20. Complete baseline funding had zero losses in 333 checks; 334 campaign budget checks passed. Another 171 positive and 408 negative scope units per profile lacked a supported matched comparison. [Static summaries](data/supported-regression.json) preserve the original all-scope aggregate result. Published [paired rows](data/matched-regression-rows.jsonl.gz) contain only public/source-free-held scopes: 335 of 439 matched rows. Private per-case tokens are omitted entirely; [the publication boundary](data/static-publication-boundary.json) records aggregate omissions. The portable replay does not regenerate the all-scope static table from that public subset.

| Paid panel | Novel answered / queued | Novel reports | Baseline-control reports / answered | Missing novel answers |
|---|---:|---:|---:|---:|
| Earlier current-phase panel, included once in R1 | 8 / 8 | 0 | 2 / 4 | 0 |
| New R1 intake | 4 / 24 | 0 | 1 / 8 | 20 |
| R2 intake | 16 / 24 | 0 | 2 / 8 | 8 |

Twenty-eight answered novel cases yielded zero incremental reports; 28 more remain unanswered. All five reports were baseline controls. Source review supports four controls, including the R2 video executor bridge and authentication preflight/token-cache policy. The stream-wrapper control remains source-unknown. No incremental false reports were observed because there were no incremental reports; this does not establish precision.

The public package has **75 individual records**: 72 licensed public payload records and three source-free redistribution holds. One earlier private novel case is represented only by sanitized aggregate counts and spend, with no adopter identifiers or prompts. Therefore the individual replay has 27 answered novel cases and 28 unknowns; the isolated private aggregate adds one answered non-report to recover the historical panel total. [Metrics](data/metrics.json), [aggregate exclusion](data/private-aggregates.json), and [replayed output](data/expected-replay.json) make that boundary explicit.

## Follow the original answer to the decision

**Recognized overlap, no report.** [ENS-L2002](cases/ENS-L2002/case.json) compares LiteLLM realtime adapters. The [original Claude answer](cases/ENS-L2002/claude-answer.json) says `duplicate`, 0.62: “Both functions repeat the same realtime provider-transform round trip.” It correctly describes shared state marshaling. Independent source review accepted a narrower seven-field writeback helper, preserving indexed versus optional reads and attribute versus session-dictionary storage. The pair was funded, but 0.62 did not pass 0.80; Jev scored 0.41. This is a reporting failure on an accepted partial operation, not evidence that the model failed to recognize overlap. Do not merge the complete adapters or move session ownership into provider configuration.

**Gate passes shared SDK vocabulary.** [SE-R2-001](cases/SE-R2-001/case.json) passes the original gate with seven shared operations, two shared calls, rare `completions`/`with_raw_response`/`parse` tokens and containment 0.40558. `python3 algorithm.py` recomputes these values from the original methods and frozen full-background statistics. Yet the [answer](cases/SE-R2-001/claude-answer.json) is `separate`, 0.05: “The only overlap is calling `with_raw_response.create(**data, timeout=timeout)` and then `parse()`.” Source review labels it related: chat headers and token-limit handling differ from async text conversion, pre-call logging and error wrapping; the SDK already owns the common call pattern. Rare vocabulary was insufficient to establish an unowned operation.

**Useful, already covered.** [SE-R2-016](cases/SE-R2-016/case.json) emitted at 0.80. The [answer](cases/SE-R2-016/claude-answer.json) identifies repeated context capture, executor dispatch and a second await of coroutine results in video facades. Source review accepts a narrow dispatch bridge while keeping signatures, argument binding, `async_call`, captured locals and exception mapping caller-owned. Baseline already funded it, so it is a success of existing coverage, not ensemble recall.

## Learnings, costs and the smaller alternative

Profile overlap and remaining budget mattered more than adding another similarity signal. R2 reduced negative exposures in Default3 but removed a useful cache-gated alert extra after TF-IDF20. The operational filter does not solve every workflow-similarity error, and retrieval cannot repair a reporting-threshold miss.

On the exact 38-Python-pair block comparison, baseline funded 30/38; both one and two block extras funded 31/38, with no added negative exposures among 80 matched negative scope units (64 pairs). The gain was cache-gated alert emission: baseline estimate $0.02658429 plus $0.00705429 fit the $0.04 cap. Across the broader panel, both caps funded 64 versus 63 of 80 positive pairs; the second slot added nothing. This supports the smaller add-on, not a new paid report. [Cap comparison](data/block-cap-comparison.json) and [recommended configuration](data/recommended-config.json) retain that narrower recommendation. An older 35→37/39 headline used different single-query concept-prompt ledgers and cannot be pooled with these shared-operations family campaigns.

The learned screen froze 26 features, regularized logistic regression and shallow CPU histogram boosting with outer leave-one-repository-out evaluation and family/source-component exclusions. Against matched-cap fixed fusion, default logistic had 0 wins/0 losses on 111 positive pairs and boosting 0/1 on 109. The separate balanced diagnostic had logistic 2/3 and boosting 1/2 on 90 matched pairs. [Learned denominators](data/learned-comparison.json) preserve all units and pilot qualifications; those findings do not support replacement.

| Accounting unit | R1 | R2 |
|---|---:|---:|
| Actual fresh paired judge spend | $0.21864048 | $0.20451824 |
| Earlier current-phase share within R1 | $0.10181884 | — |
| New-intake share | $0.11682164 | $0.20451824 |

Total current-phase spend was $0.42315872; historical older $0.01674792 is separate. Individual public/held records replay R1 $0.20713964; the sanitized private aggregate contributes $0.01150084. Cached answers contribute no fresh spend. Logical campaigns used a $0.04 cap and 150-output-token normal estimates, charging cached candidates; physical diagnostic dollars are different. The unchanged judge was Claude Sonnet 5.5 `shared-operations`, cap 1,024, threshold 0.80; Jev 1.14.0 remained diagnostic. Final cached regression took 38.11s wall/40.20s CPU; R2 source preparation 79.02s/142.28s with two numerical threads. These are preparation/replay costs, not isolated deployment overhead.

Stop the tested learned/combined/gated promotion proposals. Retain one guarded block after explicit TF-IDF20 and opt-in cached dense retrieval for Default3. Keep source-unknown controls and missing novel answers visible; no third variant or lowered report bar is justified by this record.

## Portable reproduction and full-study contract

Python 3.11+, no third-party dependencies, credentials or network:

```sh
python3 algorithm.py
python3 replay.py --output /tmp/signal-ensemble-replay.json
python3 replay.py --case ENS-L2002 --output /tmp/signal-ensemble-writeback.json
python3 verify.py
```

The first command runs the original gate scoring methods on one public pair's exact background-state projection. The second reparses raw public Claude answers and combines original admissions into paired panel counts and cost accounting. Held cases use numeric verdict records only. This is a selected algorithm reproduction plus recorded-result replay; it does not rebuild embeddings, learned fits, full-corpus retrieval, or independent source labels. Checksums complement these computations.

The [recordings archive](data/recordings.json.gz) includes exact rendered public prompts, model/version/options, original provider answers, candidate source/context, admission rows, accepted source scopes and original ledger hashes. [Selected full files](data/selected-source-files.json.gz) support the readable [case directories](cases); license texts are in [licenses](licenses). [Source acquisition](data/source-manifest.json) fixes full source SHA256, pins and paths; each recorded identity fixes exact include/exclude scope.

Four of the five distinct published paid-case background hashes match the [separate pinned goldens catalog](https://github.com/gigaverse-app/dry-lint-goldens/blob/bb29c4b71987008d06c2381a68b6833b6d542e3e/catalog.json). The Kaizen research-only background is not in that catalog; neither it nor source/prompts/answer prose is redistributed. The larger 79-scope study is not asserted fully cataloged. [Exact lookups](data/background-catalog-lookup.json) and [DATA-CONTRACT.json](DATA-CONTRACT.json) retain the difference.

```sh
git clone https://github.com/gigaverse-app/dry-lint-goldens.git /tmp/dry-lint-goldens
git -C /tmp/dry-lint-goldens checkout --detach bb29c4b71987008d06c2381a68b6833b6d542e3e
python3 /tmp/dry-lint-goldens/corpus.py verify
python3 backgrounds.py --goldens /tmp/dry-lint-goldens --out /tmp/ensemble-backgrounds
python3 hydrate.py --repository BerriAI/litellm --git /path/to/litellm --out /tmp/ensemble-source
```

The source hydrator reads exact existing Git objects and verifies hashes; it never fetches or substitutes a nearby revision. For a redistribution-held case, use its original recorded local ledger, whose path/hash are in `case.provenance`:

```sh
python3 hydrate.py --case ENS-L2010 --ledger /home/researcher/dry-lint-round/jobs/experiment-signal-ensemble/.lab-results/funded-rounds/final-supported-evidence/prior-current-phase-completed.jsonl --out /tmp/held-ensemble-case.json
```

This explicit local operation restores the exact original prompt/answer only when the ledger hash matches; the output remains under the redistribution hold. No private adopter case is exported. A full study rebuild needs the original exact inventories, candidate pools, cached dense/block representations, fitting splits and ledgers in the data contract. Archived originals can write at import time, so they remain `.txt` data; `algorithm.py` compiles only allowlisted definitions. [Provenance](data/provenance.json) preserves original hashes and declares privacy-only comment edits. No source corpus is duplicated into the repository and no live provider execution is included.
