# Balanced discovery: production validation

Use `balanced` for a coding agent's pre-commit feedback. It now runs the production exploration scheduler,
retains a cumulative $0.04 campaign allowance, and accepts reviewed fix/dismiss decisions. This is the profile
selected by the backend and AI hook adoption PRs. Unattended `auto` selection retains its existing calibration.

## Frozen experiment

On 4 November 2026, replayed 11 previously untested backend/AI PRs across 42 commits, then two previously labelled
regression PRs across 16 commits. These are historical source snapshots, not synthetic inserted duplicates.
The fresh cohort includes recent and older unseen PRs. Source extraction never executes repository code.

Merged PRs use the merge commit's first parent as their base; open PRs use their frozen base ref. Every ordered
head and tree is recorded. Development captures with incorrect current-main bases were excluded before judging.
Runtime policy was frozen at `1f215b215e9588290e4769ca30dc6be1095e1ae2`: ordinary baseline candidates followed by
20-neighbour TF-IDF exploration at 0.35, including same-file operations; Haiku shared-operations, 2,048 maximum
output tokens, 0.5 report/fail threshold, no escalation or SDK retry. Budget and pacing match
[the production configuration](production-discovery.md).

Before observing fresh model answers, Codex reviewed 73 final-source pairs: three duplicates, 68 separate and two
borderline. Selection included every final baseline candidate and inspected exploration candidates. This is a
small purposive panel, not a random or exhaustive corpus sample. Codex then reviewed every additional reported
source version, recording supplementary labels separately. Those labels never enlarge the frozen recall denominator.

## Cost and known-positive recall

| Cohort and arm | Commits | Known positive pairs found | Accounted calls | Total cost | Highest PR cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fresh, baseline only | 42 | 0 / 3 | 60 | $0.0227580 | $0.0077642 |
| Fresh, balanced | 42 | 3 / 3 | 270 | $0.1320332 | $0.0174937 |
| Fresh, balanced + reviewed dismissals | 42 | 3 / 3 | 270 | $0.1320332 | $0.0174937 |
| Regression, baseline only | 16 | 2 / 3 | 50 | $0.0208420 | $0.0186607 |
| Regression, balanced | 16 | 3 / 3 | 86 | $0.0388857 | $0.0322314 |

Each PR has its own $0.04 allowance across commits; totals span multiple PRs. Every baseline judgment available
to the baseline-only arm remained covered in balanced at the same commit. The feedback arm explicitly suppressed
one reviewed baseline negative on a later commit; no unreviewed baseline coverage was lost.

The fresh positives were two shared verification pipelines and a repeated ticket eligibility operation. They
first entered the exploration pool at commits 2, 3 and 2 of their histories and were reported then. All are outside
the baseline pool, so this cohort alone cannot prove protection of baseline positives. The regression cohort
supplies that check: the late baseline positive was reported on commit 10 of 14 in both arms, changed evidence was
reported again on commit 12, and balanced ended at $0.0322314. The other regression PR retained its baseline
positive and added its independently labelled exploration partner.

These fractions are **recall of known positives**, not estimated corpus recall. Unjudged candidates remain unknown.
Same-file retrieval explains much of this cohort's gain; it does not isolate the effects of neighbour depth and
pacing. The previous scheduler comparison remains in [the earlier experiment](agent-feedback-experiment.md).

## Review burden and feedback

Balanced reported 36 distinct source/context evidence versions: 16 confirmed duplicates, 13 separate and seven
borderline. Counting every borderline against the tool gives **44.4% confirmed precision**, above the requested
25% minimum. Multiple pairs concern one shared operation, so these are not 16 independent refactoring tasks or
statistical trials. Deduplicating by pair gives 13 confirmed, ten separate and seven borderline: 43.3% confirmed.

Useful supplementary findings included a repeated provider-to-currency rule, filter-default merging, event-email
envelope assembly and redirect-host policy that already differed between validation and explanation. Weak findings
centered on generic view lookup/404/permission sequences, tiny encoding idioms and already-shared helpers.
Different permission classes and failure contracts matter when reviewing these.

The feedback replay dismisses a source version only after its first reported interruption and explicit `separate`
review. It exercises production `Feedback.apply` and scheduling. False-positive report occurrences fell from
**21 to 13**, eliminating all eight repeats of unchanged dismissed evidence, with no additional calls or loss of
positives. Total reported occurrences fell from 93 to 85. Borderline findings remain unresolved. Real findings
continue appearing because we did not invent repairs in historical code.

Noise is uneven: the worst fresh PR consists entirely of generic view-preamble suggestions. The maximum false
positives on one commit was seven, or six with feedback. Aggregate precision does not promise a quiet experience
on every PR. Exact-source dismissals also reopen after a comment edit; this is deliberately conservative.

## Physical spending and latency

The fresh experiment made 270 new provider requests costing **$0.1320332** from returned usage: 572,887 input and
149,489 output tokens, no provider failures. Baseline and feedback reused those observations but charged each
campaign independently. Regression reused 91 eligible historical observations and made 33 additional requests
costing $0.0160197; campaign totals include whichever old observations they actually used.

Fresh calls took 946.8 provider seconds in total. Summed sequential provider time per commit was p50 22.0 seconds,
p90 43.0 seconds and maximum 73.8 seconds, excluding extraction, installation and local overhead. These are recorded
request durations replayed into each arm, not fresh wall-clock timings for cached arms. Dollar budgets do not bound
latency, and other codebases need their own measurements.

A separately installed pre-commit hook used live Haiku on a disposable repository. It rejected a staged duplicate
while preserving an unstaged repair, rejected `feedback fix` for unchanged staged source, accepted the staged
repair, rejected a restored duplicate despite its old fix record, accepted a staged synthetic dismissal, reopened
changed source, and accepted the final repair. Cumulative usage was $0.0006889. This validates mechanics, not
precision or recall calibration.

## Promotion and next evidence

Promote explicit `balanced` for coding-agent hooks now. Keep `agent-haiku` as the baseline-only rollback profile.
The coding agent reviews each shared operation, fixes it or records a reasoned dismissal before committing.
Local SQLite state survives runs and worktrees; hosted CI and other machines have separate allowances unless
state is deliberately persisted and shared. An evictable Actions cache cannot promise a durable cumulative cap.

Do not automatically tune thresholds from these few PRs. Collect distinct reviewed evidence per repository,
track false-positive interruptions and time-to-first-real-finding, and require sufficient new labels before a
bounded policy change. Explicit fixes are reviewer claims, not automatically verified positives. Larger recall
panels and quieter handling of generic framework patterns are the next improvements. Changing unattended `auto`
needs broader calibration; stronger/subscription judging remains a separate profile.

Reproduce with `scripts/replay_production.py`; add `--baseline` for the comparator and `--feedback reviewed.json`
for exact-evidence dismissal replay. Private manifests, source, labels and responses stay outside this repository.
The [aggregate results and per-commit curves](production-discovery-results.json) contain counts, costs, provenance
hashes and anonymous history identifiers.

## Exploration depth

On 10 November 2026 the first-parent history of four repositories (Python and TypeScript, 78 commits with changed
functions) was replayed twice through the production scheduler, one commit as one pull request. Both arms saw the
same candidates in the same order, with the Haiku shared-operations judge at 0.5. Only the pacing differed.

| Per push | Pairs judged | Exploration pairs judged | Reports | Opus 5.5 confirms | Mean cost a commit | Highest |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 exploration calls, $0.006 credit (until 1.10) | 656 | 267 | 90 | 81 | $0.0035 | $0.0133 |
| 30 exploration calls, $0.015 credit (default) | 1,252 | 726 | 135 | 110 | $0.0065 | $0.0207 |

Opus 5.5 read every reported pair with the same question and counts as confirming at 0.5. It is a stronger
model, not a human label. The deeper arm reports 29 more confirmed duplicates and 16 more unconfirmed ones:
91% of the shared reports are confirmed and 66% of the added ones, so the added reports are the less certain
half. The median commit costs the same, because most commits have fewer than ten exploration candidates.

The replay gives every commit a fresh allowance. A real pull request shares $0.04 across its pushes: baseline
keeps $0.015 of it and exploration may spend $0.025, so a push that uses its whole $0.015 credit leaves a later
push $0.010. Verdicts for unchanged pairs come from the store and cost nothing on later pushes.
