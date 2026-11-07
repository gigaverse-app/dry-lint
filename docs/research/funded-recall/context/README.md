# Can mechanically extracted source context make a cheap duplicate judge more reliable?

**The two recipes we tested did not recover a useful report. We should stop these recipes and keep the existing input format.** This is a result about how we selected source text, not a reason to abandon better context or cheaper judging.

Dry-lint first retrieves potentially duplicated code, then asks a model whether sharing an implementation would actually help. Jev is cheaper and faster than Claude, but the two often disagree. One possible explanation is missing evidence: a function may delegate to an existing helper, its caller may impose a different contract, or its duplicated operation may sit beyond the part of the body the model sees. If a script could supply the relevant evidence, we might obtain more reliable decisions without paying for a model to browse the repository.

This experiment tested that explanation at the **judging stage**. It reused existing candidate pairs; it did not change TF-IDF retrieval or claim to find more candidates.

## What we tried

We compared each model with itself, keeping its question and reporting rule fixed. A report required a duplicate/drifted answer with a score of at least 0.8. That is the configured reporting rule, not our definition of source truth. The models were `jev-1.14.0` and `claude-sonnet-5-5`.

**First attempt: add mechanically selected surrounding source.** An earlier small source-browsing pilot suggested imports, nearby code and references as potentially useful evidence. We therefore extracted, in order: referenced imports, the preceding 12 source lines, the function's first 24 lines, and up to three exact-name reference sightings in nearby files. Each side received at most 4,000 characters of this material. We supplied source text and coordinates, without a model-written explanation of what the code meant.

Jev still received its original 8,000-character function prefix; Claude retained its full function input. Thus this first attempt could add ownership clues but could not fix Jev's missing function tail. Six source families were checked with baseline and treatment calls to both models: 24 fresh calls in total. Four families contained independently accepted partial operations worth sharing. Neither model newly reported any of them.

**Second attempt: show more of a long function within a bounded input.** Because the first attempt left the truncation problem intact, we changed the body selection. For a body longer than 8,000 characters, the script selected 1,600-character windows at its start, one-third, two-thirds and end, aligned to source lines and capped at 7,200 rendered characters. Short bodies stayed intact. The windows were chosen from source position, without using the gold operation's location. This attempt did not also add the first attempt's context bundle.

```text
BEFORE: candidate pair -> Jev's body prefix / Claude's full body -> verdict
AFTER:  same pair      -> fixed windows across each long body   -> verdict
                         start | one-third | two-thirds | end
```

The second attempt used 12 previously unjudged pairs selected from retained TF-IDF candidates, plus four existing controls. The new pairs came from families separate from the first attempt and its design examples. Each new pair received all four calls: baseline and treatment for each model. The controls reused their exact recorded baseline answers and received fresh treatment calls. This produced 56 fresh calls; the control comparisons are consequently noncontemporaneous.

## What happened

Independent source review found two useful **partial operations** among the 12 new pairs. Six pairs already shared the relevant implementation, three were related without an accepted extraction, and one was separate. The controls added two known positives and two separate examples. Related and already-shared cases were retained as such, rather than converted into binary negatives.

| Second-attempt outcome | Jev: baseline → windows | Claude: baseline → windows | Meaning |
| --- | ---: | ---: | --- |
| Useful novel operations reported; higher is better | 0/2 → 0/2 | 0/2 → 0/2 | No recovered report |
| Known positive controls reported; higher is better | 0/2 → 0/2 | 1/2 → 0/2 | One earlier Claude success was lost |
| Separate cases incorrectly reported; lower is better | 0/3 → 0/3 | 0/3 → 0/3 | No new false report on these three cases |

All requested answers and source assessments were obtained. This is a small development experiment, not an estimate of production-wide accuracy. In particular, the historical control comparison cannot distinguish input effects from model variation over time. The zero recovery result on the newly paired cases does not have that historical-baseline limitation.

## Two misses explain the limitation

**T3's per-thread action reservation.** Two hooks independently reserve a thread ID, suppress a concurrent action, await a job and release the reservation after normal completion. Source review found a small common operation worth sharing. A correct extraction must preserve the existing behavior on rejection: it must not introduce `finally` cleanup that changes the reservation policy. Both models still missed the report. The useful region that was hidden in a long body remained between the fixed windows. [Pinned source](https://github.com/pingdotgg/t3code/blob/6577c6b6185167c0e502fa01f9e8e8f2dee6ff25/apps/mobile/src/features/home/useThreadListActions.ts#L86) · evidence ID `JCTX-R2-08b01303638b8b9d`.

**LiteLLM's repeated error construction.** The router's failure handler and pre-call checks construct matching unsupported-parameter and context-window errors. Those error builders can be shared while preserving each caller's selection and raising/returning behavior. Whole-function consolidation would be wrong. The second recipe omitted a previously visible relevant region, and neither model emitted a useful report. [Failure handler](https://github.com/BerriAI/litellm/blob/fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f/litellm/router_rust/core.py#L3682), [pre-call checks](https://github.com/BerriAI/litellm/blob/fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f/litellm/router_rust/steps/precall.py#L317) · evidence ID `JCTX-R2-2f2794c9ff5b2164`.

These cases demonstrate a concrete weakness: distributing a fixed character budget across a function does not ensure that a complete useful operation is visible. The experiment does **not** establish that visibility was the only cause of each model's miss. It also does not establish that mechanical context cannot help; the first recipe's bounded lexical references were not a full caller or helper-ownership analysis.

## Decision and useful next boundary

Do not deploy either the surrounding-source bundle or fixed-position windows. They recovered no report in this sample, and windows can remove evidence the baseline already contained. Preserve full function signatures and documentation in the source records; distinguish any provider-side excerpt from the complete function.

A worthwhile successor would have to select complete semantic operations or resolve specific helper/caller questions, then demonstrate benefit against the same full-body baseline. The separate source-browsing judge experiment addresses part of that question. We should not tune a third window recipe on these reviewed cases.

## Cost and verification

The first attempt cost **$0.24912180** and the second **$0.45707392**, totaling **$0.70619572 for 80 fresh calls**. Cached control baselines and older pilot spending do not count toward this total. The second attempt's 12 novel pairs cost Jev $0.00276296 before versus $0.00261040 after, and Claude $0.219142 before versus $0.167578 after. Smaller inputs saved some provider cost but bought no recovered report.

The repository contains [paired results](paired-results.csv), [aggregate evidence](evidence.json), [exact source pins](source-pins.json), and [request/output hash and cost receipts](request-hash-receipts.jsonl). From the repository root:

```bash
python3 docs/research/funded-recall/context/audit.py
```

This verifies file hashes and recomputes published costs and report changes without a provider call. Raw rendered requests and full source-review records remain in the lab archive; the hashes identify them but do not make the full experiment reproducible from this PR alone. The experiment used a separate diagnostic judging allowance. It does not establish what an adopter's $0.04 historical PR budget would have admitted.
