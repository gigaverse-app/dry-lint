# Complete operation views recover two bounded useful reports

The append-only CPU variant produced **2 independently source-supported useful Claude reports among 47 novel candidates**, with **0 reports among 16 controls**. Independent review also found **two bounded useful candidates that Claude did not report**. This is a scoped improvement over the fixed prefix baseline, with concentrated evidence: 45 novel candidates came from one held repository, two from OpenHands, and all eight confirmation pairs belonged to one previously unreviewed family. Keep the original CPU method opt-in. Stop pursuing the abstention-only restriction; retain append-only operation retrieval as promising research, without promoting another CPU implementation or changing defaults.

The model remains the pinned `all-MiniLM-L6-v2` CPU encoder. Its original input is the full function text truncated at 256 wordpieces. Long functions gain at most two source-exact complete-statement views: Python AST or TypeScript syntax statements, 48–180 wordpieces, extending beyond the prefix cutoff. Maximal enclosing statements suppress their children; largest statements win, source order breaks ties, and overlapping views are excluded. The function name prefixes each view, and inputs exceeding 256 wordpieces are excluded rather than silently truncated. Fragment caching keys exact input content and the encoder contract. Every judge receives the unchanged native whole functions, names, signatures, documentation and normal context.

Retrieval takes the maximum cosine across query/target prefix and operation views, requiring at least one operation view. It uses a 0.80 floor and stable source order, returning at most one new eligible pair. The original sequence remains baseline3 → explicit TFIDF20 → original CPU1. Round 1 only used the new route when CPU1 abstained; Round 2 appends it after original winners. There is no score reranking, added call-resolution guard, Jev veto, or test-label-adaptive statement placement. Existing native forwarding and policy eligibility still applies. Actual code/configuration and the pre-answer method-identity correction are included in `implementation/` and the experiment records.

For the public OpenHands example, [LLM.completion](sources/OpenHands__software-agent-sdk/cfae94d00e7addaa592ee7c9a92ebb4939b13034/openhands/sdk/llm/llm.py) constructs a `MetricsSnapshot` inline; [Metrics.get_snapshot](sources/OpenHands__software-agent-sdk/cfae94d00e7addaa592ee7c9a92ebb4939b13034/openhands/sdk/llm/utils/metrics.py) owns a similar field projection. The whole-prefix cosine is 0.343447, rank 1,029; the operation score is 0.816806, rank 1. TF-IDF score is zero in the fixed fitted background. Original CPU1 returned another candidate, so V1 suppressed this pair; V2 admitted it. Claude reported duplicate at 0.82 while Jev scored 0.20. Independent review accepted a bounded shared projection **only with explicit copying/aliasing and absence policy**: the inline construction retains token usage directly, while the helper deep-copies truthy usage and converts falsy values to `None`. Direct helper substitution changes observable behavior.

The other report, CPUI2-004, is a held confirmation case. It scored 0.80 with Claude and 0.90 with Jev and has an accepted bounded source decision. Its source, paths, prompts and explanatory prose remain private. **V1 would also admit this pair**: it demonstrates operation-representation recall beyond the original prefix route, not an effect of removing the abstention guard. CPUI2-012 specifically demonstrates the append rule.

| Paid cohort | Novel candidates | Controls | Research-only suppressed audits | New canonical Claude reports | Fresh spend |
| --- | ---: | ---: | ---: | ---: | ---: |
| R1, including corrected supplement | 5 | 32 | 18 | 0 | $0.36591404 |
| R2 append-only | 47 | 16 | 0 | 2 | $0.44305252 |

Both judges answered every selected case independently: 236 fresh valid calls for these 118 cases. R2 candidate source utility was 4 bounded, 5 tiny, 19 already shared, 12 separate and 7 generic; controls contained 2 tiny, 6 already shared, 5 separate and 3 generic cases. Both emitted Claude reports were bounded-useful. The two remaining bounded candidates were misses: CPUI2-002 received Claude `duplicate` at 0.50, below the unchanged 0.80 threshold; CPUI2-038 received `separate` at 0.12. They remain source-supported misses, not negatives. Jev scored them 0.21 and 0.09. Review acceptance is scoped evidence, not automatic gold relabelling. R1 also contained useful unreported audit/control operations; those reviewed families informed development and were excluded from fresh confirmation.

The primary comparison preserves the original standalone Claude-only **$0.04 normal estimated per-change budget**, using Sonnet 5.5/shared-operations, a 1024-token output ceiling and the normal 150-answer-token estimate. A separately named paired Jev+Claude $0.04 diagnostic ledger is also recorded. Both targets are funded under each of those ledgers, with original admissions preserved. For CPUI2-012 the original Claude-only estimate rises from $0.00861429 to $0.01636643. Physical research spend is neither ledger's estimate.

The separate [balanced posthoc check](balanced-posthoc/README.md) selected the two reports after seeing Sonnet outcomes. Native cold `CampaignStore` admission with Haiku 5.5, output ceiling 2048, report/drop/drift thresholds .50/.50/.80, no escalation and $0.04 budget admitted and reported both targets, retaining the original control as separate: 2 gains, 0 losses. The public query goes from one to two reservations, $0.00212300 → $0.00412530; the held query goes from zero to one, $0.00196650. Its control shares a query and was not fully method-blind. This supports those two selected queries, not all 63 R2 cases. Four additional fresh calls cost $0.00223456, with two exact Jev reuses. **Total CPU spend is $0.81120112 across 240 fresh valid calls**, with no missing/error answers. No further paid supplement was requested.

The historical corpus was fully swept at its frozen scope: **16 backgrounds, 171,449 indexed documents, 170,750 native-resolved functions and 699 unresolved ambiguous identities**. The 699 are not empty functions, model declarations, forwarding verdicts or source negatives. Their original snapshot code, TF-IDF tokens and prefix vectors remain in the unchanged competitor backgrounds. They contribute to sparse document frequencies; no documents were silently dropped and no refit was performed. Unknown native spans and ambiguous identities exclude them from CPU neighbours before the neighbour cap, from tail encoding, from query sweeps, and from paid eligibility. Sparse candidates with unknown spans cannot pass the logical funding ledger. Native-resolved means function/body/span resolution; strict whole-file parsing was additionally required for every paid endpoint, not established for every historical competitor.

| Repository | Unresolved documents across its frozen backgrounds | Reason |
| --- | ---: | --- |
| t3code | 169 | ambiguous native identity |
| LiteLLM | 144 | ambiguous native identity |
| gigaverse-ai | 10 | ambiguous native identity |
| OpenHands SDK | 4 | ambiguous native identity |
| opencode | 372 | ambiguous native identity |

The complete per-background/revision table is [native-source-coverage-by-background.csv](native-source-coverage-by-background.csv). CPUI2-004's background contains 4 unresolved documents among 31,104; CPUI2-012's contains 2 among 2,349. For both exact queries, unresolved documents occupy zero raw TF-IDF top-20 slots and produce zero selected or funded candidates. Their maximum prefix scores are .3224/.4540 and operation scores .3367/.3870, below the respective floors. Both reported targets rank first even in the raw operation array. The documents' causal effect on fitted IDF was not measured; baseline and treatment share it. See [the numeric influence audit](unresolved-report-query-influence.jsonl).

The full discovery population was **119,034 queries**; exclusions were 699 unresolved queries and 51,716 test/example/fixture paths, whose documents remained competitors. V1 produced 58 addition occurrences, 41 paired-funded. The pre-answer diagnostic population comprised every operation-bearing eligible query plus a fixed one-eighth hash sample of short functions: **36,866 queries**, with 82,168 short queries outside that diagnostic sample. It yielded 3,510 best-operation occurrences, 3,465 suppressed by original nonabstention, and 963 counterfactual paired-funded occurrences. These repeated query/background observations are not independent useful reports.

R2 selected from the 15 completed cohorts while LiteLLM finished. Selection used the existing family split, prior-review exclusions, source-key ordering, repository round-robin and no endpoint reuse. Of 64 selected rows, one failed strict whole-file TypeScript parsing and remained unknown, leaving 47 candidates and 16 controls. The same unsupported file had been removed from R1's corrected supplement. The final LiteLLM cohort finished under the unchanged algorithm: its remaining fixed selection had 123 eligible development occurrences and one confirmation occurrence before endpoint deduplication. It received no paid supplement because R2 exceeded the $0.20 minimum and the registered question had informative source-reviewed outcomes; those unjudged candidates remain unknown.

Both variants replayed all **223 historical matched contexts, 207 unique gold records**, against their complete fixed competitor indexes. The original and V2 each fund 71/78 accepted positive contexts and 62/120 accepted negative contexts under the original Claude-only estimate; there are zero known positive/negative gains or losses. One additional unresolved/unaccepted context is funded. The paired diagnostic gives the same counts here. This regression is distinct from fresh candidate assessment.

A separately acquired extension adds **14 public backgrounds at nine pins, 115 mapped rows and 230 directions**. It was explicitly replayed with frozen V2 code, taking 13.1361 seconds with zero funded gains/losses and no providers. [Rows and summary](public-extension-v2/summary.json) are included; equality with V1 was measured, not presumed. These older reviewed public examples are regression, not new holdout. The original inventory contained 79 backgrounds: 16 initially available and 63 unavailable via the inherited registry. Of those 63, 36 had no recorded acquisition attempt, including these 14 public contexts; 22 other registry gaps and 27 previously attempted unavailable contexts remain outside this study. The original and extension units are reported separately rather than pooled as independent samples.

The representation census found 46,283 truncated documents and 48,466 possible statement-view instances. **48,439 native view instances across 32,203 functions were encoded; 27 views belonging to unresolved identities were excluded.** This difference is an eligibility distinction, not a quarantine/re-execution change. Fifty-seven statement parses were unavailable. Across all 16 encodes there were **48,199 distinct per-cohort inputs, 31,582 fresh encodes and 16,617 cache hits**. The extra encodes took 1,395.27 seconds (1,398.61 summed phase-wall seconds). Prefix matrices total 263,345,664 bytes; extra operation matrices total 74,402,304 bytes; the SQLite fragment cache is 69,898,240 bytes. Peak encoding RSS was 469,064 KiB; the sequential full V2 regression process peaked at 1,774,096 KiB. Full V1 discovery phase durations sum to 3,477.72 seconds across workers, not wall-clock elapsed time.

A fixed 100-function operation-bearing timing sample took 7.2821 seconds for fresh original prefixes and 7.3814 seconds for 157 additional operation inputs. Warm fragment reads took 0.00727 seconds with zero encodes and bit-identical vectors. This intentionally truncation-heavy sample and concurrent research host do not establish general deployment latency. The extra cost and concentrated novel yield support a research-only decision; original CPU opt-in and production defaults remain unchanged.

Reproduce the selected retrieval/answer evidence using Python 3.11+ and its standard library:

```sh
python3 replay.py > replay-result.json
```

This recomputes endpoint vector similarities, ranks across every recorded competitor score, bounded routing, complete ordered normal-budget admissions, and canonical answer labels/report decisions. It verifies the six selected licensed examples' full source files, native functions and exact statement transformations. It uses recorded vectors/scores; it does not rerun ONNX encoding, regenerate the corpus, adjudicate source truth, or contact a provider. Actual experiment implementation, model/artifact contracts, exact source pins, rendered questions, raw answers and output settings are bundled. Source licenses are alongside redistributed files. The six examples explain the mechanism; all 118 paid cases remain the numeric denominator.

The balanced replay is self-contained with the pinned canonical runtime and verification functions copied unchanged from the earlier balanced study:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r balanced/requirements.txt
.venv/bin/python balanced-posthoc/replay.py --balanced-package balanced
```

It recomputes both public native campaigns, rerenders/rekeys four exact questions, reparses recorded answers, applies the canonical report policy and verifies three source files and two accepted source decisions. The dependency hashes and upstream manifests are retained. Neither replay executes target code or needs provider credentials. Live reruns require separate authorization and adopter-owned inputs/credentials; no live-call command is shipped.

`all-cases-numeric.jsonl` preserves all 118 cases' role, split, source status, scores, admissions and costs. Private and Kaizen bodies, source paths, prompts and explanatory prose are withheld. Public numeric summaries are reproducible; private source semantics are not publicly re-evaluated. An authorized owner can hydrate exact local evidence outside this package:

```sh
python3 hydrate.py --case CPUI2-004 \
  --lab-root /authorized/improve-cpu-retrieval/.lab-results \
  --judge-root /authorized/judge-improvement-wave/.lab-results \
  --output-dir /authorized/private-replay
```

The hydration contract checks revision, Candidate/body/file/background hashes and request keys, then copies native candidates/context, recorded questions/answers, ranks and complete budget ledgers from authorized local files. It does not fetch repositories or call a provider. Its private output must remain private.
