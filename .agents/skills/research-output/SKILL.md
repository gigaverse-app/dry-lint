---
name: research-output
description: Turn engineering experiments into readable research reports, experiment READMEs, and evidence PRs that explain the hypothesis, tested mechanism, results, lessons, and resulting decision. Use when synthesizing research, including negative results; not for ordinary implementation summaries.
---

# Research output

Write for an engineer who knows the product but has not followed the investigation. The reader should understand what was worth testing, what actually changed, what happened, and what to do next before opening any artifact. A ledger proves that work happened; it does not explain the work.

Start by reading the experiment specification, implementation, paired results, representative cases, and current code. Reconcile conflicting summaries against these artifacts. Preserve frozen evidence; correct its interpretation in a separate, clearly attributed report.

Build a short claim-to-evidence map before drafting: question, mechanism, comparison, observation, interpretation, decision. Distinguish observations from plausible explanations. Describe the tested recipe precisely enough to implement it; do not let an internal experiment name stand in for an explanation.

Use a connected narrative with this information, adapting its order and length to the result:

- **Motivation and hypothesis.** Name the concrete user problem and the suspected cause. Explain why this intervention could help and what result would refute it. For a multi-stage system, identify the stage being changed.
- **Practical change.** Compare the same input before and after. Give a compact example, pseudocode, or diagram when it explains the mechanism. Name important constants and what stayed fixed. Separate tested behavior from proposed future work.
- **Experiment.** Explain how examples were selected, what was independently labeled, what baseline was used, and what was measured. State whether this was deployed traffic, historical replay, a synthetic budget simulation, or an offline development set. Define a “case,” “pair,” “family,” and other counting units where relevant.
- **Results.** Show the decisive baseline-versus-treatment table with numerators, denominators, units, and direction of improvement. Count useful additions, harmful additions, lost previous successes, and unresolved cases separately. Do not turn a candidate-rank gain into an end-to-end success. Put costs beside the benefit they bought, rather than leading with budget compliance.
- **Representative case.** Explain at least one concrete success or failure that makes the aggregate result intelligible. Use human descriptions before IDs and link exact evidence. Preserve the distinctions that make two superficially similar functions genuinely separate. Explain any proposed partial extraction without claiming the whole functions are interchangeable.
- **Learning and decision.** Say ship, keep opt-in, stop this recipe, or run a specific next test. Explain why. A failed recipe is not a failed research field. A positive result on an already-covered example is not added recall. Give a next experiment only when it follows from an identified remaining uncertainty; do not append speculative work to every negative result.
- **Reproduction and limits.** Link the smallest useful evidence set and exact commands. Say what the reader can reproduce locally, what needs external source or a provider, and what was not measured. Hashes identify missing artifacts but cannot reproduce them.

For a research PR, its opening explains both the research conclusion and the value of merging the record. It is not a lab status update. The README is the coherent entry point; the PR body is a shorter version of the same story. Apply the repository's PR-writing rules when available. Link to one canonical report per direction instead of maintaining several competing conclusions.

When publishing an experiment for others to reproduce, provide the actual implementation, selected inputs, selection/configuration recipe, and recorded outputs, or identify the exact unavailable component. For model studies, include rendered prompts, model/version/output settings, answer parsing and reporting rules. Offer a provider-free command that recomputes the result from recordings and a separately authorized live-rerun command that writes new results. Test the package outside the lab checkout. A checksum auditor is useful but is not an experiment reproducer; do not present it as one. Source licenses and access boundaries determine which inputs can be redistributed.

Explain a negative result by tracing a representative case through input, actual answer, score, and final decision. If a model correctly describes an overlap but scores it below the reporting threshold, call that a reporting failure rather than a failure to recognize the overlap. A missing source fragment proves an omission, not that the omission caused the verdict. Separate causal tests from post-hoc diagnostics and identify the next discriminating experiment only when it is warranted.

For recall and model experiments, keep these distinctions explicit wherever they affect the decision:

- Repositories, revisions, background scope, and data splits must match the comparison. A large inventory does not mean every row was evaluated. State supported and missing coverage without pooling incompatible cohorts.
- A provider's answer is an observation, not independent truth. Confidence thresholds are reporting rules, not label definitions. Preserve related, already-shared, disputed, and unknown outcomes rather than forcing them into binary accuracy.
- Counts of rows, pairs, directional queries, and independent families answer different questions. Avoid adding correlated measurements into a larger apparent sample.
- Physical provider spend, cache reuse, and a simulated per-change budget are different quantities. An offline budget may model deployment; it is not proof of deployment behavior.
- A failed parse or missing answer remains unknown. If it could change the decision, quantify that uncertainty; otherwise state the narrower supported conclusion and proceed.

Before publishing, read only the title, opening, mechanism example, result table, and decision as a newcomer would. Can you explain the general idea, actual implementation, outcome, and learning without decoding filenames? Then follow the links, run the supplied verification, and check the numbers against the machine evidence. Remove unexplained abbreviations, dense status codes, administrative chronology, and caveats that repeat without changing the conclusion.

When improving an existing report, repair its explanation as well as its formatting. Preserve useful negative evidence and scoped positive evidence. Do not improve the story by improving the numbers.
