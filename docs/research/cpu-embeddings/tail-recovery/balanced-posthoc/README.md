# Post-hoc balanced check of two CPU retrieval reports

Both selected CPU candidates remain admitted and reported under the exact balanced configuration. This is a **post-hoc two-query diagnostic**, selected because the original Sonnet diagnostic reported these pairs. It does not estimate effectiveness across all 63 cases or justify a global claim. Both target reports now have coordinator-accepted, source-scoped bounded extraction judgments: **2 gained bounded-useful reports and 0 lost reports**. These are two selected pairs, not independent concepts or a population precision estimate.

The replay preserves each original prefix+TFIDF pool exactly and appends one operation candidate. Four separate cold `CampaignStore` ledgers use the archived PR109 `73709fd` runtime, Haiku `claude-haiku-5-5`, canonical shared-operations, output2048, budget $0.04, report/drop/drift .50/.50/.80, default prices and no escalation. Reservations remain held without settlement. Native holds charge prompt UTF-8 bytes plus 1024 input tokens and the full 2048-token output ceiling; normal estimates remain separate.

| Case | Original → treatment admissions | Target hold | Haiku verdict | Reports |
| --- | ---: | ---: | --- | --- |
| CPUI2-004, private numeric row | 0 → 1 | $0.00196650 | duplicate .80 | yes |
| CPUI2-012, public | 1 → 2 | $0.00200230 | drifted .80 | yes |
| Retained original pair for query012 | retained in both arms | $0.00212300 | separate .05 | no |

There are **2 gained admissions/reports, 0 losses**, and one retained original pair. The public query's treatment holds total $0.00412530; its original holds total $0.00212300. The private query's treatment holds total $0.00196650. The two targets' normal estimated charges are $0.00037482 and $0.00038761, respectively. These counterfactual charges are not physical provider spend.

The retained control compares `completion` with `test_llm_completion_with_tools`. The coordinator reviewed it before calls as a separate test oracle, with body/file hashes checked. Its control role was known: this was **not fully method-blind review**, and it shares query012 rather than providing an independent query sample. All three source judgments are accepted with exact repository/revision, endpoint spans, file hashes and body hashes matched. Original reviewer labels and review packet IDs are retained; no automatic gold label is created.

For public CPUI2-012, the bounded opportunity is the `MetricsSnapshot` field projection in `completion`, also owned by `Metrics.get_snapshot`. The inline path passes mutable token usage directly; the helper copies truthy token usage and maps falsy values to `None`. A behavior-preserving extraction must explicitly preserve each caller's copying/aliasing and absence policy. Directly substituting the existing helper can change observable aliasing and is **not equivalent**. The accepted review retains that counterexample and boundary in `accepted-source-public.json`. Private004 contributes only its numeric accepted outcome here.

The extension cost **$0.00223456** in four new calls (three Haiku, one Jev), with two exact Jev reuses. Canonical Jev scored the targets .90 and .20, respectively; it does not gate the balanced Haiku report. Sonnet answers were never substituted for Haiku. The existing cumulative account/direction/CPU R2 caps remain unchanged.

The public archive contains only query012 and its control: full Candidates, exact rendered requests and raw answers, three pinned source files, complete original/treatment pools and their two SQLite backups. Private004 has a numeric row only—no source prose, function paths, prompts, raw answer prose or private native SQLite state. Local verification covered all four campaigns; portable public replay covers two and explicitly reports the private-source hold.

Reuse the already-frozen balanced package's canonical runtime and verification functions:

```sh
python3 replay.py --balanced-package ../balanced
```

The command reruns the two public native campaigns, verifies the three source files and body spans, rerenders/rekeys all four public questions, reparses the answers, and applies the canonical CLI report policy. It makes no provider calls. `balanced-dependency.json` pins the reused implementation and runtime. `summary.json` supplies all three numeric rows and the completed source join. `accepted-source-public.json` preserves the public reasons, original labels and boundaries; the private review prose remains local. Retrieval generation belongs to the main CPU experiment; this addendum reproduces admission and reporting from its frozen pools.
