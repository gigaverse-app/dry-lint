# Joining data models to functions: additional candidates, no incremental reports

Functions can repeat an operation while looking different to token search. Declared fields, types and validation rules might reveal that relationship: if two functions consume related data contracts, perhaps the detector can retrieve a useful operation it otherwise misses. This study tested that hypothesis with a static model-to-function join, then one stricter revision that compared operations on the same resolved model.

**Stop these joined recipes as promotion candidates.** The original schema join added no known-positive function coverage. The fully answered revised supplement funded 18 treatment-only pairs but emitted zero incremental reports. Useful model-contract, developer/test and bounded-operation findings remain worth retaining; baseline already funded every reported supplemental pair. This publication makes those distinctions reproducible with original code, native public source, resolved links, exact prompts/answers and original admissions.

## The actual intervention

The baseline ranks function bodies by behavior tokens. The original join extracted Pydantic, dataclass, TypeScript-interface and Zod declarations and linked them to consumers through exact imports, annotations, constructors and field uses at the same commit. It required field Dice overlap ≥0.65 and two declared common fields. It excluded name-only links and invented inherited/reference-derived fields, kept complete baseline budget priority and allowed one additional function pair per query. Standalone model-contract findings used a separate model question.

The revision required **the same resolved model plus matching operation contexts for two fields**, including at least one call or operator. Only resolved model-field references were normalized; other call targets, literals and defaults stayed intact. Preparing and sending a request can touch the same fields without doing the same job. The revised recipe therefore sought repeated operations rather than field overlap. Both joins required real source spans ≥6 lines and original cosine ≥0.10.

```text
BEFORE: function tokens -> ranked candidates -> original budget -> function judge
R1:     same baseline + related model shapes / shared fields -> one protected extra -> same judge
R2:     same baseline + same resolved model / matching field operations -> one protected extra -> same judge
MODEL:  model declarations -> separate contract question (never credited as function-join recall)
```

The [original implementation](data/archived-code/run_experiment.py.txt), [full-corpus core](data/archived-code/full-corpus-followup/replication_core.py.txt), [native ownership resolver](data/archived-code/full-corpus-followup/ts_ownership.py.txt), [operation matcher](data/archived-code/funded-rounds/contract_operations.py.txt), [coverage expansion](data/archived-code/funded-rounds/expand_round2.py.txt), and [tested specifications](data/specifications.json) preserve the recipe. All are inert `.txt` archives. The runnable [algorithm example](algorithm.py) executes the original Python signature/match definitions on two native public functions, their exact resolved field-use links, and the original model declaration; it reproduces all 15 context hashes and line bindings.

## Coverage and comparison

This was an offline development/regression inventory of 617 records across 79 exact repository/revision/file-scope backgrounds. Full source supported 16 backgrounds; 63 lacked exact source for model analysis. The function comparison covered **182 unique unordered pairs: 78 positive and 104 separate**, across 141 family/repository clusters. Positive can mean a useful partial operation, not whole-function equivalence. The shared 400/617 inventory is not the evaluated denominator; repeated directional queries and scope views are not independent successes. Every route used original full-background term weights and competitors.

Default diagnostic meant cross-file top3 at 0.50, or 0.30 for valid queries shorter than six lines. Balanced diagnostic allowed same-file top20 at 0.35. These are experimental diagnostics, not deployed configurations. Both passes shared the original synthetic $0.04 change-batch cap and charged cached answers at the normal estimate.

| Known function pairs funded | Function-only | Original schema join | Revised operation join |
|---|---:|---:|---:|
| Default positive /78 (higher better) | 32 | 32 | 32 |
| Default separate /104 (lower better) | 16 | 17 | 16 |
| Balanced positive /78 | 58 | 58 | 58 |
| Balanced separate /104 | 39 | 39 | 39 |

The original recipe added no known positive retrieval or funding and lost none. It exposed one additional known-separate preparation-versus-sending pair; the revision avoided it. Of 78 positives, 59 lacked a resolved model link on one/both sides, 12 used the same canonical model that the original distinct-shape rule excluded, six had no distinct-shape edge, and the sole eligible positive was already funded. These gates constrain this recipe's opportunity; they do not disprove model-guided retrieval generally. [Frozen measurements](data/frozen-metrics.json) retain original aggregate denominators and estimates, including source-private inventory only as aggregates.

R1's paid observations covered 22 pairs (44 answered requests), including all 12 top-up controls. Another 32 novel queued pairs remained unanswered, including nine added functions. Initial R2 precision checking covered 13 pairs and 26 answered requests, all already baseline-funded. The coverage revision then queried **2,545 previously unqueried functions** in five pinned source backgrounds and froze a 48-pair supplement.

| Revised supplement (48 distinct pairs) | Function-only | Joined route |
|---|---:|---:|
| Funded in at least one original recorded campaign | 30 | 48 |
| Strict treatment-only pairs | — | 18 |
| Known Claude reports | 7 | 7 |
| Incremental function reports | — | 0 |
| Missing provider answers | 0 | 0 |

These “any campaign” unions reproduce the frozen study convention, not a single deployment or independent 48-PR trial. All 96 supplemental requests returned. Among the 18 treatment-only pairs, Claude labeled 14 separate and four duplicate at 0.50–0.60; none passed 0.80. Provider labels are observations, not independent truth. Seven supplemental pairs would report, and function-only already funded all seven.

## Source D: useful partial operations are baseline-cofunded

The current Source-D update supersedes the older source-pending interpretation while preserving the older metrics bytes. Twelve supplemental source assessments are now joined to the original admissions and provider ledgers: **five bounded extractions, one tiny convenience, four related, one already-shared and one negative**. All five bounded findings and the tiny convenience were already function-only-funded. Five of seven projected reports have bounded support, one is related, and one remains source-unknown. The tiny convenience is below the canonical reporting threshold.

The bounded findings concern provider-dispatch forwarding, end-user page cache finalization, spinner-option normalization, ordered state-path scanning and CLI signal/cleanup lifecycle. Keep provider resolution, transaction/retry ordering, frame generation and caller policies outside the helpers. State-path scanning's any-branch endpoint has only test-demonstrated reachability at this pin; export alone is not production evidence. Patch-status/path formatting is a tiny convenience, not a production algorithm gain. One bounded state-search case is under a redistribution hold, so only its numeric/scoped category record is public.

Source D reviewed two of the 18 treatment-only pairs: one related and one negative. The other 16 are source-unknown. All 18 have known original-policy emissions of zero. Future source curation could establish useful partial operations among them; it cannot change zero emissions under this frozen policy. Global family-newness remains unresolved rather than inferred from pair IDs or provider agreement. [Current metrics](data/metrics.json) and each case's `source_review` retain the final source tier; [pre-update metrics](data/frozen-metrics.json) remain explicitly historical.

## Representative successes and failures

**A useful operation already found by the baseline.** [MF-FC-41a0b0cb6b53](cases/MF-FC-41a0b0cb6b53/case.json) compares EdenAI and FAL dispatch functions using `CompletionDispatchContext`. The original matcher finds 15 shared operation contexts over 13 fields; `python3 algorithm.py` recomputes their original hashes from source and frozen links. The [Claude answer](cases/MF-FC-41a0b0cb6b53/claude-answer.json) says `duplicate`, 0.80, proposing a helper that includes provider configuration resolution. Source review narrows the helper to forwarding already-resolved inputs to the base handler, post-logging and returning the unchanged result. Keep provider credential/base resolution and FAL's streaming rejection outside; do not alter async return handling or logging timing. Before: baseline-funded report. After: the same report, no added recall.

**Same model and branching shape, different work.** [MF-FC-857c073a93d2](cases/MF-FC-857c073a93d2/case.json) is a strict treatment-only OpenCode pair. Both functions branch on stream-commit kind/phase, but one constructs scrollback content and the other chooses color and attributes. The [answer](cases/MF-FC-857c073a93d2/claude-answer.json) says `separate`, 0.04: “There is no shared executable operation, only a similar dispatch shape over the same input type.” Source D agrees with a negative scoped finding. The added candidate did not establish a shared operation or emit a report.

**Model-positive, source-related, below threshold.** [MF-FC-540f9bcdc2b2](cases/MF-FC-540f9bcdc2b2/case.json) describes a local update phase versus an overall update-capsule state. Claude said duplicate at 0.60; Jev scored 0.84. Accepted source review says related: row text and aggregate label/tone/action policy have different priorities and responsibilities. It remains a non-emitting treatment-only pair, with disagreement preserved rather than voted into a binary label.

**Test maintenance is useful, not production recall.** [MF-FC-7e77ae1ff789](cases/MF-FC-7e77ae1ff789/case.json) compares two timer-flush tests. The [answer](cases/MF-FC-7e77ae1ff789/claude-answer.json) says duplicate at 0.93 and recommends removing the redundant copy. Source review accepts retaining one complete canonical timer test while preserving complementary close/reset/full-buffer coverage. Both routes already funded it. This is a scoped test-maintenance success, not new production duplication.

Two earlier held-source findings remain separate: a shared runtime-schema/TypeScript contract was also found by model-only and emitted at 0.80; a modest JSON/stdin/process/environment harness was join-funded but scored 0.20 and never emitted. Their bodies, rendered prompts and answer prose are withheld. Caller-specific runtime, timeout, parsing and exit behavior remain distinct. Neither establishes incremental reported function recall.

## Costs and decision

| Measurement | Before: function-only | After: original join |
|---|---:|---:|
| Aggregate default normal estimates | $5.63708786 | $6.67979714 |
| Known-positive default funded pairs /78 | 32 | 32 |
| Aggregate balanced normal estimates | $10.19110500 | $10.33111000 |
| Known-positive balanced funded pairs /78 | 58 | 58 |

Those totals sum synthetic campaigns and include normal charges for cached candidates. They are not physical spend or one change's budget. Actual fresh central judging was **$0.20703060 in R1 and $0.51609920 in R2** ($0.09918588 initial precision plus $0.41691332 supplement), totaling $0.72312980. Historical pilot $0.044103 and older sealed intake $0.01911308 remain separate. Primary function judging used Claude Sonnet 5.5 `shared-operations`, output cap 1,024, threshold 0.80; model questions use their distinct recorded contract policy. Jev was diagnostic, not a veto. Exact rendered identities and model-specific options are in the recordings.

The original harness took 345.9s/~2.48GiB peak. Successful full-source extension processing totaled 105.05s/~0.60GiB, including 4.98s to materialize five exact sparse graphs that are now cached. These are aggregate processing times, not isolated overhead or deployment latency measurements.

Stop both tested joined reporting recipes. Preserve the standalone model-contract findings and scoped source leads without claiming global new families. Model fields alone were too weak; operation matching generated candidates but did not buy added reports. The downstream reporting misses and architectural distinctions must remain visible. No further variant, provider call or threshold adjustment is proposed.

## Reproduce, hydrate and understand the limits

Python 3.11+, standard library only:

```sh
python3 algorithm.py
python3 replay.py --output /tmp/model-function-replay.json
python3 replay.py --case MF-FC-41a0b0cb6b53 --output /tmp/model-function-provider-dispatch.json
python3 verify.py
```

The first command executes original Python signature normalization/matching over selected native source and existing resolved links. The second reparses original public Claude answer text, preserves held numeric verdicts/unknowns, and recomputes report counts from original per-campaign admissions. It covers **115 case records: 87 public payloads and 28 source-free holds**, including the 32 unanswered R1 novels. This is selected algorithm reproduction and recorded-result replay, not rebuilding ownership resolution, full-corpus retrieval or new model answers. [Expected replay](data/expected-replay.json) and [data contract](DATA-CONTRACT.json) define its scope.

[Recordings](data/recordings.json.gz) contain actual public candidate/context payloads, rendered prompts, model/version/options, original answers, parsed verdicts, admissions and source assessments. [Readable cases](cases) and [selected full sources](data/selected-source-files.json.gz) make representative results inspectable. Source permissions are retained in [licenses](licenses): public MIT source only, excluding LiteLLM enterprise; dry-lint's archived implementation retains Apache-2.0. No private adopter source, prompts or identifiers are included.

| Source | Exact revision | Publication boundary |
|---|---|---|
| `BerriAI/litellm` | `fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f` | Public; enterprise excluded |
| `pingdotgg/t3code` | `6577c6b6185167c0e502fa01f9e8e8f2dee6ff25` | Public |
| `anomalyco/opencode` | `cc996eece172fc69e35662657ea6cea9c2c7db88` | Public |
| `OpenHands/software-agent-sdk` | `344ec8a9c30dff0a4ca200fc412510aad44e1bdc` | Public, including scoped test cases |
| `Garsson-io/kaizen` | `4941b4a8928054910b5053255a99c84ac32bf3c2` | Redistribution held; source-free records only |

Exact include/exclude scopes and source hashes remain per identity in [the source manifest](data/source-manifest.json) and recordings. Four paid-case background hashes exactly match the [separate pinned goldens catalog](https://github.com/gigaverse-app/dry-lint-goldens/blob/bb29c4b71987008d06c2381a68b6833b6d542e3e/catalog.json); the held fifth does not. [The lookup](data/background-catalog-lookup.json) makes no claim that all 79 historical scopes are in that catalog.

```sh
git clone https://github.com/gigaverse-app/dry-lint-goldens.git /tmp/dry-lint-goldens
git -C /tmp/dry-lint-goldens checkout --detach bb29c4b71987008d06c2381a68b6833b6d542e3e
python3 /tmp/dry-lint-goldens/corpus.py verify
python3 backgrounds.py --goldens /tmp/dry-lint-goldens --out /tmp/model-backgrounds
python3 hydrate.py --repository BerriAI/litellm --git /path/to/litellm --out /tmp/model-source
```

These commands use exact matching objects, never a nearby revision or a two-snippet IDF replacement. For a held source case, local users with the original lawful evidence can hydrate the exact recorded payload:

```sh
python3 hydrate.py --case MF-FC-5643422cc704 --ledger /home/researcher/dry-lint-round/jobs/experiment-model-function/.lab-results/funded-rounds/round1/results-v1/v3-completed.jsonl --out /tmp/held-model-case.json
```

The ledger hash and each rendered prompt hash must match; output remains under the redistribution hold. The original scripts, dependency lock and core snapshot are [archived as data](data/archived-code); replay never imports their side-effecting module bodies. [Provenance](data/provenance.json) fixes original bytes and declares privacy-only comment substitutions. Full reconstruction needs the inventories, original resolved links/model declarations, candidate pools, frozen sparse graphs and ledgers identified in the data contract. A separately authorized live judge run would need adopter-owned credentials and new output paths; none is included here.
