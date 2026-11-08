# Balanced admission addendum: more useful reports, with a precision caveat

**Current implementation decision (7 November 2026):** [PR109](https://github.com/gigaverse-app/dry-lint/pull/109) now enables bounded operation blocks automatically only within explicitly agent-reviewed `balanced`, with an explicit TF-IDF-only escape hatch. This is a coordinator decision to accept the earlier development tradeoff (+9 net bounded-useful / +3 net unsupported reports), not a claim of broad validated recall. A new native chronological replay of 10 PRs / 47 revisions adds **zero new bounded-useful pairs and one unsupported pair**, loses no prior reports, and reports one already-found tiny operation earlier. Detection on a 10,319-function snapshot rises from 1.73 to 12.68 seconds. The [enablement study](https://github.com/gigaverse-app/dry-lint/blob/feat/research-recall-promotion/docs/enablement-results.md) explains this cost, the decision and exact reproduction. Legacy automatic presets stay unchanged. Earlier opt-in recommendations below describe their frozen study stage; the residual veto remains rejected.

The helper-operation retrieval treatment adds **9 net bounded-useful reports** and **1 net tiny-useful report** across 53 development queries under the balanced configuration. It also adds **3 net reports that independent source review does not support as useful extractions**. This supports keeping the treatment opt-in; it does not establish production precision or justify enabling it by default.

This addendum tests whether the helper candidates remain useful after actual budget admission and reporting. It complements the original retrieval/diagnostic study. The original and treatment pools are frozen inputs from that study: treatment can introduce a helper-operation candidate into a query's candidates, which can also displace an old admitted pair. The candidate-generation recipe and corpus-wide selection are documented in that study; this package reproduces the subsequent admission and recorded-answer comparison from the complete 735-row pools.

Both arms use `claude-haiku-5-5`, canonical `shared-operations` (`dry-operations-v2`), output ceiling 2048, budget $0.04, report/drop/drift .50/.50/.80, default prices, no escalation, no effort override, and no retries. Haiku's fallback option is disabled. We instantiate **two cold CampaignStores per query**, for 106 stores, and apply their real `order`/`reserve` APIs. All successful reservations stay held; none is settled with the research answers. The native hold charges UTF-8 prompt bytes plus 1024 input tokens and the full 2048 output tokens at the configured Haiku rates. Balanced exploration credit, baseline fraction .625, and call limits remain active. Thus this is a cold held admission replay, not historical PR spending or sequential production settlement.

| Quantity | Original arm | Treatment arm |
| --- | ---: | ---: |
| Complete candidate pool rows | 349 | 386 |
| Admitted by normal estimated charge | 349 | 386 |
| Admitted by native held reservations | 167 | 177 |
| Sum of normal estimated charges over 53 campaigns | $0.10223300 | $0.11730868 |
| Sum of native held reservations over 53 campaigns | $0.28724570 | $0.31399650 |

The admission change consists of **38 gained and 28 lost query/pair occurrences**, each also a distinct source pair within its respective delta set. Another 139 occurrences are retained. For these retained occurrences, the reproducer checks identical endpoint source, rendered Haiku questions and lanes across arms; their common question is held fixed in the delta calculation. Most retained pairs were not judged, so absolute useful-report totals for all 167/177 admissions remain unmeasured. These are correlated development pairs, not 66 independent concepts or a held-out precision sample.

All 38 gains and every displaced old pair were answered by the exact Haiku configuration and paired canonical Jev. Six admitted original controls are included separately; ten other original controls remain explicitly rejected by native admission. All original 53 cases are accounted for. The initially disclosed extra gain outside that cohort was subsequently answered and source-reviewed: Haiku said separate (.20), and the independent source label is related/too-generic. It contributes no report. No gain or loss was dropped based on its answer.

| Native delta outcome | Added among 38 gains | Lost among 28 displacements | Net |
| --- | ---: | ---: | ---: |
| CLI-reported pairs | 17 | 4 | +13 |
| Source-supported bounded extraction reports | 10 | 1 | **+9** |
| Source-supported tiny extraction reports | 2 | 1 | **+1** |
| Reports without a useful extraction | 5 | 2 | **+3** |
| Unknown provider assessments / source labels | 0 / 0 | 0 / 0 | 0 / 0 |

The reporting rule is the canonical `Report.build`, not the raw label: a non-separate verdict must meet `report_at=.50`. All three gained `drifted` verdicts at .55/.60/.60 report; `drift_at=.80` is not an extra report gate. The displaced websocket pair is source-supported as a bounded extraction, but its duplicate score .45 does **not** report and is not a lost report.

Source reviewers received source-only packets before provider execution, and the coordinator accepted scoped judgments after checking pinned bodies/files. Provider answers are observations, not truth. The package preserves normalized labels, original `reviewer_label` where supplied, reasons and extraction boundaries, with `accepted_gold=false`. Of the 17 added reports, only 10 are bounded useful and two are tiny useful; the remaining five are three already-shared pairs, one related pair and one separate pair. The four lost reports comprise one bounded expiry helper, one tiny header filter and two related pairs.

A representative gain shares only datetime/ISO normalization and naive-as-UTC handling between key-expiry paths; failure actions and clock sampling stay local (`OBH1-561b381b1020222f`). A real loss is the independently repeated expiry check in custom authentication and virtual-key validation (`OBHS1-LOSS-2cf3abd6664a5814`): extraction must retain strict comparison, malformed-date behavior, error parameters, redaction and each call position. The positive net does not make this displaced success disappear. Conversely, a gained custom-template report points to rendering already owned by `render_custom_prompt_template`; its remaining wiring is not a useful extraction (`OBH1-830e393c7770f88a`). Exact reasons and boundaries are in [the delta table](native-deltas.json).

Canonical Jev truncates eight selected pairs at 8000 characters: seven from the original cohort and one displacement. The full Candidate in the key is not proof of a full question. [The truncation audit](jev-truncation.json) records rendered/full lengths and hashes, omitted suffix hashes and affected outcomes. Historical 6000-character file-prefix context is used by Jev; canonical Claude shared-operations ignores Function.context and includes both full function bodies. Three added bounded-useful reports and the lost bounded expiry report have partial Jev questions. Their canonical Jev answers remain partial evidence. The balanced conclusion uses full-body Haiku and independent source review, so no full-body Jev successor is necessary for it; no causal explanation of Jev disagreement is claimed.

The balanced extension cost **$0.05358154** in 101 new calls (72 Haiku, 29 Jev), reusing 43 exact Jev answers. The extra handoff also repeated a control whose two answers cost nothing new; it is not a fresh-funded control claim. Physical spend is separate from both tabled logical accounts. The unchanged shared research account totals $0.85974610 against its $8 cap, with direction/round caps preserved. The separate historical agentic allocation retains $0.127882 of unknown maximum usage; it was not reset or credited to the new account. Exact cache reuse saves physical spend, never the normal logical charge.

Run the provider-free reproduction from this directory with Python 3.11+ and the dependencies in `requirements.txt`:

```sh
python3 reproduce.py
python3 reproduce.py --output ./recomputed
python3 -m pytest test_reproduce.py -q
```

The command imports the bundled original runtime, recomputes all 106 actual SQLite admission campaigns, compares their states with the supplied immutable backups, recomputes normal estimates, rerenders 144 exact requests, checks model/output/settings/source keys, reparses recorded raw responses, validates known usage charges, and rebuilds the report/source join. No model, key or network is needed. The archive is about 3.3 MiB compressed; it includes full selected Candidates, exact rendered prompts, answers, all 735 pool rows, and all 82 scoped source reviews, without duplicating the background corpus. `runtime.zip` and `native-snapshots.zip` supply executable policy and native store proof. [summary.json](summary.json) is the compact machine result; [selected-cases.json](selected-cases.json) preserves the independent controls.

Source pins are LiteLLM `fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f` and software-agent-sdk `344ec8a9c30dff0a4ca200fc412510aad44e1bdc`. All 75 selected source files were also checked against immutable local Git, including exact body spans and file-prefix context. That check can be repeated with `--verify-local-git` when the original repository paths in the recordings are available. Ordinary portable replay checks included bodies and recorded hash bindings, not absent whole repository blobs or extraction of the entire corpus. Source and runtime licenses are included. Live provider execution is outside this recorded-evidence reproduction.
