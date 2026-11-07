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

## Why the changes failed to produce a report

The recorded answers distinguish **recognizing an overlap** from **emitting a report**. Claude described a useful partial extraction in both representative cases, both before and after windowing. It assigned 0.60 each time, so neither answer crossed the unchanged 0.80 reporting rule. The direct observed loss is at that reporting threshold. We did not test a lower threshold here, and a lower threshold cannot be assumed safe without checking negatives.

| Independently useful partial operation | Jev score: original → windows | Claude score: original → windows | First observed loss in this judging comparison |
| --- | ---: | ---: | --- |
| T3: suppress concurrent work on the same thread, then release its reservation after normal completion | 0.68 → 0.73, duplicate in both | 0.60 → 0.60, duplicate in both | Both recognize duplication but neither reaches 0.80 |
| LiteLLM: construct the same unsupported-parameter and context-window errors | 0.29 → 0.27, separate in both | 0.60 → 0.60, duplicate in both | Jev rejects the concept; Claude identifies the overlap but stays below 0.80 |

**T3's action reservation.** The executor and the larger action hook independently check and reserve an in-flight thread key, await a job, and remove the key after normal completion. The useful extraction must preserve the current behavior on rejection: adding unconditional `finally` cleanup would change the policy. Claude's answers identify a shared mutation runner, but describe the overlap as partial and assign moderate confidence. That is narrower than “the model could not see the operation.” Its proposed broader cleanup also needs checking against the actual failure behavior. [Pinned source](https://github.com/pingdotgg/t3code/blob/6577c6b6185167c0e502fa01f9e8e8f2dee6ff25/apps/mobile/src/features/home/useThreadListActions.ts#L86) · `JCTX-R2-08b01303638b8b9d`.

**LiteLLM's error builders.** The failure handler and pre-call checks independently construct matching exception messages and fields. They should retain their separate decisions about which error applies, parameter sorting, and whether to raise or return it. Claude describes essentially these error-builder helpers in both answers, yet scores both 0.60. Jev continues to classify the larger functions as separate concepts. [Failure handler](https://github.com/BerriAI/litellm/blob/fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f/litellm/router_rust/core.py#L3682), [pre-call checks](https://github.com/BerriAI/litellm/blob/fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f/litellm/router_rust/steps/precall.py#L317) · `JCTX-R2-2f2794c9ff5b2164`.

**What the evidence explains.** Adding context did not raise the relevant scores enough to produce a report. Claude's explicit answers suggest that confidence in a useful partial extraction is a separate bottleneck even when it can describe one. This is a hypothesis about its scoring behavior, not a calibrated causal finding. Its prompt already asks it to score confidence in the repeated operation rather than code size. Jev's question instead asks whether the two functions implement one concept. Consequently this is a within-model input comparison, not a controlled Jev-versus-Claude capability test.

**What windowing demonstrably risks.** The saved source-to-window mappings show accepted operation fragments that remain hidden and others that were visible before but are omitted afterward. Fixed positions do not guarantee complete operation coverage. Those omissions are observable; claiming that they caused the two misses would go beyond the evidence, because Claude still identified the overlaps. A useful successor must address both evidence selection and the meaning/calibration of the reporting score, with negative controls.

## Decision and useful next boundary

Do not deploy either the surrounding-source bundle or fixed-position windows. They recovered no report in this sample, and windows can remove evidence the baseline already contained. Preserve full function signatures and documentation in the source records; distinguish any provider-side excerpt from the complete function.

A worthwhile successor would have to select complete semantic operations or resolve specific helper/caller questions, then demonstrate benefit against the same full-body baseline. The separate source-browsing judge experiment addresses part of that question. We should not tune a third window recipe on these reviewed cases.

## Cost and verification

The first attempt cost **$0.24912180** and the second **$0.45707392**, totaling **$0.70619572 for 80 fresh calls**. Cached control baselines and older pilot spending do not count toward this total. The second attempt's 12 novel pairs cost Jev $0.00276296 before versus $0.00261040 after, and Claude $0.219142 before versus $0.167578 after. Smaller inputs saved some provider cost but bought no recovered report.

The [reproduction kit](reproduction/README.md) now contains the **actual code, inputs and answers**, rather than only their hashes:

| Inspect | Included evidence |
| --- | --- |
| Actual implementation | [Original source-anchor recipe](implementation/trace_followup.py), [body-window recipe](implementation/coverage_round2.py), [scoring](implementation/score_coverage_round2.py), [Claude renderer/parser](implementation/anthropic.py), [Jev renderer/parser](implementation/jev.py); complete dependency archive and lockfile |
| Exact question and settings | [Prompt contracts](reproduction/prompts.json), complete rendered request payloads, model/version/output caps, source and request identities |
| Source used | Complete licensed native Candidates, signatures/context, pinned full Git files, source-to-window maps, licenses; native parsing can be rerun separately |
| What the providers answered | 88 sanitized recorded observations with final answers and token usage: 80 fresh calls plus eight historical control baselines |
| How results were calculated | [Portable replay](reproduction/reproduce.py) recomputes transformations, labels, scores, report changes, costs and synthetic budget admissions; compares against [published paired rows](paired-results.csv) |

From the repository root, reproduce the recorded selected-case result **offline**, using only Python's standard library:

```bash
cd docs/research/funded-recall/context/reproduction
python3 reproduce.py verify
python3 reproduce.py metrics > /tmp/context-metrics.json
python3 -m unittest discover -s . -p test_kit.py -v
```

Inspect the T3 case directly, including the exact answer rather than a prose summary:

```bash
python3 kit.py inspect-case JCTX-R2-08b01303638b8b9d --kind claude --arm baseline --part answer
python3 kit.py inspect-case JCTX-R2-08b01303638b8b9d --kind claude --arm treatment --part answer
```

`--part original`, `git`, `input` and `prompt` expose the native function, pinned file, selected text and actual question respectively. The kit also provides the original selection/scoring code, optional pinned native-extractor replay, immutable Git acquisition and **dry-run-by-default live playback**. Live playback creates new observations in a new directory; it cannot promise the same model answers. The [instructions](reproduction/README.md) distinguish each operation and its dependencies.

One first-round Kaizen case remains under its existing redistribution hold. Its source-free results and hashes are included, so numeric replay covers every case. Its four source-bearing requests require the supplied local hydration command; they are not silently replaced or approximated. The other 21 cases include their full licensed source and payloads. Eight historical control payloads are canonical reconstructions from retained inputs; original fresh-call wire hashes are preserved separately.

This package reproduces the **selected-case extraction, input transformations and recorded judging comparison**. It does not rebuild the earlier whole-corpus nomination campaign, whose full backgrounds and family graph are outside this package. Historical native metadata differences are explicitly reported; stored Candidates and current re-extraction are not asserted identical. Source assessments remain supplied, reviewable judgments rather than facts proved by arithmetic.

The experiment used a separate diagnostic judging allowance. Its synthetic $0.04 calculation is reproducible but does not establish what an adopter's actual historical PR budget would have admitted. The outer `context/audit.py` remains a lightweight consistency check; the reproduction kit is the executable study record.
