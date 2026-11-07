# Small local embeddings add candidates, but have not beaten wider lexical search

A small pretrained encoder can recover candidates labeled as shared operations that dry-lint's first three lexical matches miss. This experiment did **not demonstrate an additional emitted report over the existing wider TF-IDF exploration route**. The apparent Windows report gain is now disputed by independent source review. Keep the implemented encoder optional and cached, retain TF-IDF defaults, and do not promote the experimental reranker on these results.

## What problem we tested

Dry-lint first proposes similar functions; a separate judge decides whether their shared operation deserves a finding. A useful pair that never reaches the judge cannot be reported. TF-IDF—term frequency weighted by inverse document frequency—ranks functions using their extracted behavior tokens. We tested whether a small local encoder could find shared operations despite different surface wording, without displacing existing proposals.

The initial suspected opportunity was a **candidate-generation** failure. The later source review also exposed judge mistakes after useful candidates had already been reached and funded. A result that disappeared when we compared with a larger lexical candidate list would weaken the claim that learned representations supplied unique value.

## What actually changed

The original plugin converts each supplied function into an embedding: a numeric vector produced by the pinned `all-MiniLM-L6-v2` model. It ranks complete-repository competitors by cosine similarity, which measures the angle between normalized vectors. Existing routes run first; the plugin then offers at most **one new, unsettled pair per changed function**, at cosine >= .65. Earlier proposals are excluded before that one-slot limit. Scores are not blended and prior candidates remain unchanged.

We tested two explicit lists of routes:

- **Narrow:** ordinary TF-IDF top3, then CPU top1.
- **Wide:** ordinary top3, the original TF-IDF top20 exploration at .35, then CPU top1.

Ordinary top3 uses a .5 score floor, reduced to .3 for queries under six actual source lines. The wide exploration also permits same-file pairs. Replacing that exploration list with CPU alone is a different configuration, not an unchanged production default.

After the first paid round, we tested one fixed revision: take the first **20 eligible embedding-based (dense) proposals** at .65, rerank them by complete-background behavior-token TF-IDF cosine, discard zero overlap, and offer the best one. Ties use dense cosine then original source order; returned scores remain dense scores. The idea was to discourage topical similarity without a shared operation. That explanation was a hypothesis; the measurements below establish what the recipe did.

## What ran

This was an offline development/regression experiment, not deployed traffic or a fresh holdout. The shared inventory has 617 records across 79 exact background identities. We completed all 16 backgrounds whose pinned native function source was available: **207 distinct records**, producing **223 pair/background measurements** because some records map to multiple scopes. Of those measurements, 198 have accepted labels: 78 positive and 120 negative. The other 25 remain unaccepted, borderline or unknown.

Each representation used the complete original background for its repository, revision and extraction scope, never just the labeled snippets. Original lexical weighting, order and document-frequency cutoffs were retained. The paired run used the same 382 directional query slots, pooled within each background, for every arm. A pair means two source functions; a pair/background context counts that pair in one exact corpus. Related records and repeated scopes are correlated, not independent new examples.

The exact pinned commits were unavailable in the audited local source repositories for 63 backgrounds; those encoders were not run ([coverage receipt](data/background-acquisition.json)). Four model-declaration rows are absent from the original function inventories and retain their separate-model-inventory-required status; this is not proof that embeddings cannot encode declarations. We did not merge revisions or extraction scopes to fill gaps.

We also froze new source-pinned pairs from the actual tested routes, excluding exact known/reviewed pairs. Round 2 reserved LiteLLM, which supplied no round-1 requests: 48 novel hypotheses plus 16 independent control hypotheses, with no reused endpoints. Control was a sampling role, not a negative label. Root ran the providers. An independent source reviewer assessed selected operations blind to method and provider answers; root accepted four source-local assessments. Those assessments remain separate from provider labels and the frozen regression gold.

## What improved, what became worse, and what stayed unknown

The complete paired function-panel results are additional **retrieval exposures**, before judge answers or real deployment budgets. A positive is a shared-operation label in the frozen inventory; a negative is a separate-operation label:

| Added route, after its matched baseline | Additional positive contexts / 78 | Additional negative contexts / 120 | Lost baseline contexts | Total candidates, before → after |
| --- | ---: | ---: | ---: | ---: |
| Original CPU1 after narrow top3 | 15 | 15 | 0 | 483 → 797 |
| Original CPU1 after wide top3 + TF-IDF20 | 0 | 3 | 0 | 1,970 → 2,274 |
| Revised dense20/token-rerank CPU1 after narrow top3 | 25 | 15 | 0 | 483 → 776 |

The revision gains 11 positive contexts and loses one that original CPU1 retrieved; four negative contexts enter and four leave. No earlier baseline candidate is lost. The table preserves the original frozen labels. Excluding the disputed Windows prior positive reduces the positive denominator from 78 to 77 without changing any additions or losses; also excluding the reopened scheduling case reduces the negative denominator to 119. See the [source-conflict sensitivity](data/evidence/conclusion/disputed-source-sensitivity.json). Scoped positive labels mean a shared operation may be extractable; they do not assert that whole functions are interchangeable.

The paid follow-up did not establish a new novel gain in round 1: its latest intake completed all 16 controls, none crossing the Claude .8 reporting threshold, while 48 unstarted novel pairs remain unknown. The earlier Windows result remains a directional retrieval/report observation, with disputed source utility.

The decisive report-policy check is less favorable than the candidate counts. Round 2 obtained answers for 36 of its 64 pairs. Under the frozen standalone Claude reporting rule—non-separate label, score >= .8, `shared-operations` prompt, output cap 1024, exact source/context binding—the revised narrow route projects **one report, 35 non-emissions and 28 unknowns**. Its matched TF-IDF20 control retrieves 46 selected pairs, funds 45 under the same simulated budget, and projects the **same report**, with 22 unknown projections. Baseline3 retrieves none of these selected new pairs. Independent source review finds that sole projected report related rather than usefully extractable. Thus there is one **unsupported report projection** over narrow top3, no source-supported useful report among the observed pairs under this fixed rule, and no demonstrated new report over TF-IDF20. Missing answers are not negative evidence.

## Cases that explain the result

**Disputed apparent recovery: Windows string rewriting.** With the nine-line routine as the sole changed query, top3 misses the pair; original CPU1 retrieves and funds it, and an exactly bound Claude .8 answer projects a report. An earlier source assessment accepted a narrow shared operation. New independent source review finds different contracts: one routine performs case-sensitive substring replacement, including inside larger words; the other performs case-insensitive token-aware rewrites with underscore exclusions. A common Windows guard does not establish a shared transformation policy. Root now marks the earlier positive **disputed**, with a new source-local assessment of related operations. The retrieval, funding and report projection remain observations, not a confirmed useful gain. The reverse four-line query is already found by TF-IDF and still has no exact reversed answer (Windows refinement pair, CPUE04 / PEV2-002; [directional evidence](data/evidence/promotion/CPUE04-directional-emissions.jsonl), [review authority and sensitivity](data/evidence/conclusion/disputed-source-sensitivity.json), decision `9697a6dcdfd4ab45b047`).

**A known false candidate: opposite scheduling transformations.** Creating a schedule from an editor draft and reconstructing an editor draft from an existing task share terminology but perform distinct operations. CPU adds this accepted-negative pair; it is a negative exposure, not a demonstrated false emitted report (scheduling input/output contrast, CF-T3-X02).

**The reranker's tradeoff: budget-reset orchestration.** The revision recovers the scoped shared chunk-processing operation between API-key and team budget-reset jobs, but loses the team/user counterpart that original CPU1 selected. Restricting the additional route to one candidate creates a real selection tradeoff; a larger positive total does not mean there are no losses (LL-S035 and CF-LL-C03; [paired changes](data/anonymous-regression-pairs.json)).

**Useful partial operation reached but not reported: live cache inventory.** LiteLLM's count and item debug routes traverse the same live caches. A small shared inventory reader could remove repeated cache/expiry traversal while preserving distinct count-versus-item outputs, existing router/pin helpers and late-bound runtime globals. Root accepted this scoped utility, not whole-function interchangeability. Both revised CPU and original TF-IDF20 retrieve and fund it; baseline3 excludes this same-file pair. Jev returns drifted .86, but the fixed Claude policy misses it with separate .25. This is a useful source-local candidate and a canonical judge miss, not a unique embedding report gain (cache-inventory operation, CPUR2-002).

**An unsupported report already covered by wider search: deployment model IDs.** The logging helper accepts only existing string IDs and optional input; the affinity helper accepts a mapping and converts any non-None ID to a string. Source review finds no established shared ID policy beyond a primitive lookup. Both judges flag it, and Claude .80 would report it, but root accepted the source assessment as related, not a useful shared getter. TF-IDF20 also retrieves/funds it. Baseline3 loses it at top3, not a size or score floor (ID-validation/coercion contrast, CPUR2-044).

The accepted source join is small and selected, not a representative precision sample. All four pairs below were admitted and funded under the original revised-CPU ledger **and** the matched TF-IDF20 ledger. The existing baseline3 route misses the two same-file pairs and loses the other two at top3. Jev is a second judge observed for diagnosis; it does not replace the frozen Claude report policy.

| Independently reviewed operation | Accepted source-local assessment | Jev observation | Claude observation and fixed .8 report |
| --- | --- | --- | --- |
| Live cache inventory (CPUR2-002) | Useful partial extraction | Drifted .86 | Separate .25: useful operation missed |
| Deployment-ID validation/coercion (CPUR2-044) | Related; differing policies | Duplicate .93 | Drifted .80: unsupported report |
| Service-exclusion wrappers (CPUR2-056) | Related; existing normalizer owns shared work | Drifted .82 | Separate .20: no report |
| Async resource closure (CPUR2-001) | Related; existing wrapper owns closure | Separate .41 | Separate .05: no report |

The [exact source/admission/judge join](data/recordings.json) verifies unchanged source identities, body/file hashes, canonical request identities and original funded ledgers. No paid requests or representations were rerun. These source-local utility decisions do not establish global novelty or relabel the broader frozen gold.

## What we learned and decided

The comparison directly shows that widening lexical search covers much of the apparent gain over three proposals. It also shows that the fixed reranker changes which candidates survive its single slot, improving labeled coverage while preserving negative exposures and losing one prior additional positive. These are measured effects. The useful cache operation was already admitted by wider lexical search, then rejected by Claude; the only Claude report is a related getter pair with incompatible policies. Candidate reach, source utility and judge reportability are distinct failure points. Topical or boilerplate similarity as the broader cause remains a hypothesis, not a quantified causal conclusion.

Keep TF-IDF and its existing exploration behavior unchanged. The disputed Windows example supplies no established useful report gain. The original offline CPU plugin is a bounded opt-in capability, not a recommended default or a demonstrated improvement over the wide route. Do not promote the research-only reranker: its extra representation machinery has not earned a unique emitted gain here. The accepted selected source reviews and Windows dispute are now joined to the original admissions; publish those distinctions with the record. There is no third recipe, judge substitution, reporting-rule change or further paid experiment proposed.

## Runtime and reproduction appendix

Cold CPU work matters. Production encoding/indexing of 100 supplied bodies took **6.623 seconds cold versus .440 warm** (88 unique bodies). Original complete LiteLLM encoding took **2,495.946 seconds**. The revised warm index for all 37,604 LiteLLM functions took 23.476 seconds; selected query median/mean/max were .116/.138/.329 seconds, peak RSS 1,190 MiB, using two CPU threads. It reused 36,674 cached body vectors and performed no new encodes. This supports an optional persistent cache, not default cold CI.

The [pinned artifact contract and adopter instructions](data/original/README.md) identify the exact model revision and file hashes. The Apache-2.0 model runs through ONNX CPU with explicitly supplied offline artifacts, no automatic download and telemetry disabled. It reads the first 256 wordpieces of each supplied full function, averages token vectors with padding masked out, and normalizes the result. There are no chunks. Original LiteLLM encoding truncated 10,657/37,604 functions. Public pretraining contamination is possible.

A simulated normal **$0.04 per changed-function batch** funds each arm independently, even for already observed answers. That is not authentic PR funding. Root's actual diagnostic spend was $0.28323212 in round 1 and $0.22441836 in round 2; cache hits and historical judging are excluded. Provider agreement and confidence do not define source truth. No verdict-reuse rule was changed.

The smallest useful evidence set is [paired results](data/evidence/funded-rounds/round2/regression/comparison-summary.json), [report projections](data/paired-round2.json), [matched sparse controls](data/evidence/funded-rounds/round2/matched-sparse-baseline-summary.json), [exact policy](data/evidence/funded-rounds/round2/projection-policy.json), [independent source/admission joins](data/recordings.json), and [public source packets](REPRODUCTION.md). [Commands and hashes](data/original/lab/funded-rounds/round2/REPRODUCE.json.txt) replay the cached experiment in the materialized lab checkout with its pinned artifacts and cohorts; the scripts deliberately forbid new encoding. A public reader can independently inspect the portable packets and reconstruct their pinned source with Git. The bundle does not distribute model weights, all historical labels or cached vectors, so those commands alone cannot recreate the complete lab elsewhere. Provider observations are preserved receipts; reproducing paid calls would require adopter-owned credentials and is not part of the worker replay.

The source-conflict sensitivity and exact accepted source joins were consumed from frozen records, without fitting or new judging. The old Windows positive remains in frozen data. Private historical rows are published only as anonymous label/admission booleans; they do not expose adopter source, prompts or identifiers.

## Run the selected recorded-source kit

```bash
python3 reproduce.py --output /tmp/cpu-recorded-results-NEW
python3 audit.py
python3 reproduce.py --case CPUR2-002
```

The replay revalidates exact source spans, rendered prompts, recorded answer parsing, fixed report policy and cost accounting on four independently reviewed public cases. It also recomputes 64 selected-queue report states and the anonymous regression changes (11 positive additions, one lost previous CPU success). Missing answers stay unknown. [Original answers and decisions](CASES.md) explain the cache miss and unsupported ID report.

For the original selected vector algorithm, use Python with NumPy 2.5.4 installed, then `python native.py`. It executes the original `CpuEmbeddingComparer.similarity` function on eight recorded source-bound vectors. It performs no encoding or index fitting. The four pair cosines agree within 1e-6 (float32 accumulation tolerance). It does not regenerate top20 eligibility, full-background rank or reranker selection from two-vector subsets.

[Original implementation/configuration](data/original/README.md), [full rerun contract](FULL-RERUN.json), [pinned corpus acquisition](CORPUS.md), [source/model acquisition and dependency instructions](REPRODUCTION.md), and [original/published provenance hashes](data/provenance.json) make the boundary explicit. Public backgrounds with exact matching hashes are available from the separate goldens repository; absent public hashes and private backgrounds remain separate. This is a portable selected-case recorded-source replay plus the original full programs, not a full experiment reconstruction or a checksum-only claim.
