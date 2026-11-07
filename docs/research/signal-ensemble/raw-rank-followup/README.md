# Complete statements help; preserving the budget order makes them usable

The original ensemble recipes produced more funded candidates without an observed useful-report gain. This follow-up combines two concrete signals—complete Python operation blocks and CPU embeddings of complete tail statements—and evaluates them with the existing budget scheduler. The implementable result is **three additional bounded useful reports and three tiny reports, with no lost admissions**, across 66 selected single-function campaigns. Keep it opt-in. Five four-function shared campaigns produce no gain, so this is not a demonstrated PR-wide improvement.

The new representation addresses a specific miss: the encoder sees only the first 256 wordpieces of a function. It can miss a registration request or permission policy embedded much later in a long handler. Up to two complete statements beyond the prefix provide additional vectors. Both routes apply actual eligibility before returning up to 20 neighbours; equal reciprocal-rank fusion adds `1/(60+rank)` per proposing route, ties by original corpus order, and emits at most one extra full-function pair. A tail-only first-ranked neighbour scores `1/61`, not its origin cosine. The full recipe, installed plugin and configuration are in [PR109](https://github.com/gigaverse-app/dry-lint/pull/109).

## Why the first combination was not good enough

The first tail and fused variants returned the selected candidate's origin cosine. Their extra .8-level scores moved them ahead of older exploration work under the native budget scheduler. Keeping the old retrieval routes first did not protect their funding. In the 37-query continuation panel, five new bounded useful reports displaced six old ones, and one new report was already shared. Two known-positive regression campaigns gained one useful report but lost two. Those variants remain rejected as implementations.

The successor keeps the actual raw fusion score. It does not inspect remaining money, reserve an extra slot, alter the scheduler, or scale scores after seeing a budget outcome. Its low raw scores schedule after higher-scoring older candidates *within the same query's exploration work*. Cross-query fairness still applies and can change that order. This is a transparent scoring-and-admission choice, not a proof that every prior report is protected.

| Paired cold campaigns, same $0.04 cap | Existing stack | Raw-rank successor |
| --- | ---: | ---: |
| Admissions in 66 selected single-function campaigns | 191 | 207 |
| New bounded useful reports | 0 | 3 |
| New tiny-overlap reports | 0 | 3 |
| New unsupported reports | 0 | 0 |
| Previous admissions lost | — | 0 |
| Admissions in five four-function campaigns | 27 | 27 |

The 16 added pairs comprise three bounded useful, four tiny, six already-shared, two related and one separate pair. All have independent source assessments and exact provider answers; six report under the fixed Haiku rule. Three useful reports are three operation families across two repositories: T3 desktop portal host registration, opencode manual-permission visibility after project auto-approval, and opencode extension-panel entry discovery. Tiny reports are not counted as substantial gains. Neither three families nor 66 correlated selected queries establishes generalization to unseen repositories.

There are 338 completed regression row/background contexts over 30 exact backgrounds: 309 accepted positive/negative contexts and 29 borderline/unaccepted/unknown contexts. The successor preserves every baseline admission outcome. Accepted pair-context funding remains 70/78 positive and 59/119 negative in the prior16 panel, and 52/56 positive and 18/56 negative in the recovered14 panel. Negative funding is judge workload, not a false report. These denominators are repeated source contexts, not 338 independent gold families.

The explicit baseline is TF-IDF3 plus TF-IDF20/.35, operation-blocks2/top1 and prefix CPU/.65/top1. Native cold CampaignStore replay uses Haiku 5.5/shared-operations/2048 with .50 report/drop, .80 drift and no escalation, plus the same $0.04 cap. No adopter configuration or default-policy equivalence is inferred. Reservations are held without settlement; historical PR sequences and conditional relatives are outside this experiment.

## What we learned about ensembles and boosting

Tail-only and fused selection chose the same candidates in the tested panel. Therefore, these results support **complete-statement representation plus compatible budget ordering**, not a separate predictive benefit from RRF agreement. The three successful pairs each have a tail match even where the block route abstains. Keeping RRF gives a bounded, deterministic way to combine the available routes, but should not be marketed as a learned ensemble win.

The previous learned attempt also had a data-coverage problem: its balanced labels contain 147 positive source components and 102 named positive families, while only 22 rows had recorded dense features and 32 had recorded block features. Missing measurements are not zero-valued negative evidence. There are enough labels to motivate a later complete feature matrix and family-held-out training; this study does not show that shallow boosting is inherently unhelpful. It does show that adding model complexity before repairing features and auditing admission losses would be premature.

## Evidence and reproduction

The canonical new experiment is [the CPU raw-rank follow-up](https://github.com/gigaverse-app/dry-lint/blob/research/study-cpu-embeddings/docs/research/cpu-embeddings/raw-rank-followup/README.md). It owns the runnable provider-free reconstruction, complete selected source and prompts, recorded responses, original failed arms, exact Candidate variants, budgets and source labels. Large matrices live in the separate private corpus repository and require collaborator access; the public report states what cannot be rerun without them.

The [independent aggregate checks](audit-summary.json) reran 142 native ledgers/1,148 events and two actual production index cases. All 64 successor request identities matched previously purchased exact source/prompt/model/options/policy questions; these are 32 primary Haiku questions and 32 Jev diagnostics, not 64 independent primary observations. Reuse was free physically but not in arm ledgers. Total new provider spend for this investigation was $0.48353090 over 259 calls, including the separate Sonnet diagnostic. No missing answers were invented or judged negative.

**Decision:** implement `cpu-tail-rrf` in #109 as an optional targeted recovery method, alongside the existing routes. Keep the high-score variants, learned replacement and old gates as negative evidence. There is a useful increment worth implementing; there is not evidence for changing defaults or promising wider PR recall.
