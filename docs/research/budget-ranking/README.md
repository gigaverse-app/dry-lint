# Budget-aware ordering: one useful addition did not justify changing the default

dry-lint often retrieves more function pairs than its judge allowance can cover. This study held those candidates fixed and changed their order: could simple operation features, or those features divided by estimated judge cost, buy more useful reports? The first public round added one useful test-support report and one related, already-shared lead. Cost sorting funded more pairs than feature sorting but found the same useful addition. A single revision that restored scheduling fairness added no reports on a separate public cohort.

**Keep the current default. Stop the flat global sorts as a promotion proposal.** Merge this record so future ranking work can reproduce the useful addition, the architectural false lead, and the scheduling lesson without paying to rediscover them. The fairness-preserving revision remains research evidence; these results do not support shipping it.

## Mechanism and comparison

The intervention sits after retrieval and before judge admission. All arms used identical pinned source, token weights, candidates, similarity scores, filters, judge prompts and reporting rules. The original utility was:

```text
utility = 0.60 × lexical cosine similarity
        + 0.30 × Jaccard overlap of non-generic call names
        + 0.10 × different containing file/class
```

“Different owner” here means syntactic placement, not an independently established architectural owner. The cost variant divided utility by the unchanged rendered question's normal estimated cost. Current ordering preserves strong-match priority and rotates across changed functions. Flat global sorts discard those safeguards. The revised recipe preserves the original baseline subsequence and priorities, then chooses the least-served changed function before utility orders peers. Its weights stayed fixed.

```text
BEFORE: fixed candidate pool -> priority + query fairness -> $0.04 admission -> unchanged judge
AFTER R1: same pool -> flat utility or utility/cost -> $0.04 admission -> same judge
AFTER R2: same pool -> baseline + priority + query fairness + utility -> same admission/judge
```

A protected-cost arm allocated the current-funded set before extras. The runnable [algorithm example](algorithm.py) executes the original `feature_order` and `Ledger.select` definitions on the complete 25-candidate public campaign containing the useful addition. [The frozen input](data/algorithm-input.json) preserves original scores, features, costs and orders. It reproduces every candidate's order and funding in all four original arms, without fitting an index. The [original experiment](data/archived-code/run_experiment.py.txt), [fairness revision](data/archived-code/run_fair_fixed_revision.py.txt), [R1 producer](data/archived-code/build_funded_round1.py.txt), and [R2 producer](data/archived-code/build_funded_round2_public.py.txt) remain readable inert data.

## What ran, and what changed

These are synthetic $0.04 budget campaigns over real public source, not deployed PR traffic. R1 selected 74 previously unreviewed pairs from 17 development lineages: 19 treatment-funded hypotheses and 55 current-funded controls. R2 selected 50 pairs from 16 other lineages: four revised-treatment additions and 46 controls. R2 source endpoints, exact pairs, rendered requests and frozen lineage IDs do not overlap R1; this is not a fresh semantic holdout claim. The shared 400/617-row inventory is not either evaluated denominator.

A pair is two native functions at one exact repository revision. A report requires original admission plus a matching answer that passes the frozen rule. A family groups one underlying operation; the same pair found by two sorts is one addition. Claude Sonnet 5.5, `shared-operations`, output cap 1,024 and report threshold 0.80 were primary. Jev 1.14.0 with source context was a diagnostic, never a veto. Every rendered request, model/version, options, original public response and parsed verdict is retained in [recordings](data/recordings.json.gz). Normal cost estimates assumed 150 output tokens; actual provider spend is separate.

| R1 metric (74 judged pairs) | Current | Fixed features | Cost sort | Protected cost |
|---|---:|---:|---:|---:|
| Funded pairs (exposure, not success) | 55 | 57 | 63 | 55 |
| Claude reports | 2 | 4 | 4 | 2 |
| Source-useful reports (higher better) | 2 | 3 | 3 | 2 |
| Related emissions (lower better) | 0 | 1 | 1 | 0 |
| Useful emitted gains / losses | — | +1 / 0 | +1 / 0 | 0 / 0 |
| Dropped current-funded pairs | — | 7 | 10 | 0 |

Eight R1 pairs received accepted source review; all four Claude emissions are covered. Source usefulness of other dropped candidates is unknown. No lost emitted report is not proof that every dropped candidate was expendable. The useful addition is the same pair/family in both sorts; global new-family credit remains unresolved.

| R2 metric (50 pairs) | Current | Revised fair fixed features |
|---|---:|---:|
| Funded pairs | 46 | 43 |
| Newly funded / dropped current pairs | — | +4 / −7 |
| Known Claude reports | 5 | 5 |
| Common paid unknowns | 1 | 1 |
| Novel emitted reports | 0 | 0 |
| Independent Jev flags | 4 | 3 |

The common-funded malformed Claude answer remains unknown, with no retry. Each arm's absolute report count is 5–6; their paired difference is zero. None of the four new pairs emitted under either reporting rule. Unreviewed usefulness stays unknown. A dropped URL-parameter helper was Jev-flagged, but its utility was not reviewed for this direction. Supplemental original flat-arm rows in the recording are diagnostic controls; they are not additional revised trials.

## Trace the useful addition and two failures

**Claude replay test recording.** In [BR-R1-0018](cases/BR-R1-0018/case.json), current ranked the pair ninth and did not fund it. Fixed features ranked it third; cost sorting ranked it first. Both funded the original $0.0089992857 estimate. The [original answer](cases/BR-R1-0018/claude-answer.json) said `duplicate`, 0.82: “Both functions repeat the same operation of recording one resumed Claude query turn.” It suggested a broad turn helper. Accepted source review narrowed the action: extract an options builder with explicit `resume`, and reuse the existing iterator-drain helper. Keep interruption protocol, two-prompt validation, labels, queue lifecycle, runtime closing and error handling with their callers. Before: no emitted pair. After: one useful bounded report, not interchangeable scenario runners.

**Filesystem access wiring.** [BR-R1-0010](cases/BR-R1-0010/case.json) also became funded and emitted. The [answer](cases/BR-R1-0010/claude-answer.json) called it `duplicate`, 0.86, proposing a shared hook. Source review found that `resolveFilesystemReadAccess` already owns the grant, pending and error policy; platform session binding and UI responsibilities differ. The final decision is related/non-actionable for a new shared operation. Call overlap and different files failed to establish missing ownership.

**Redis telemetry composition.** Every arm funded [BR-R1-0059](cases/BR-R1-0059/case.json), but the [answer](cases/BR-R1-0059/claude-answer.json) said `separate`, 0.20, treating hook calls as logging boilerplate. Source review accepted a modest shared scheduling/composition block, preserving single-versus-bulk commands, decoding, timing, metadata and return shapes. This is a downstream reporting miss; reranking cannot recover a pair already funded everywhere.

## Costs, historical evidence and decision

| Accounting unit | R1 | R2 |
|---|---:|---:|
| Attempted physical questions | 148 | 100 |
| Known verdicts | 148 | 99 + 1 unknown |
| Actual fresh judge spend | $0.69653208 | $0.59135360 |
| Producer preparation wall time | 12.26 s | 11.65 s |
| Central batch wall time | 122.58 s | 102.75 s |

These costs buy both judges and independent controls; they are not deployed per-PR costs. Sorting latency was not isolated. Cached and older costs contributed zero to these rounds' paid minimums. The simulation's $0.04 allowance uses normal estimates, not physical research charges.

The final historical interpretation comes from `FINAL-HANDOFF-v2` and `FINAL-SOURCE-UPDATE-v2`, with provenance hashes retained. Only sanitized aggregates are published in [metrics](data/metrics.json). On 11 complete matched normal-estimate histories out of 12 per arm, reports were 53→54: zero substantive useful additions, one tiny optional addition, no report losses; one paid malformed history censored four arms. The revised native history comparison added three reports and lost five: +1/−0 substantive useful, +1/−1 tiny optional, +1/−2 related, plus removal of two separate prior reports. The final three source decisions were outcome-aware coordinator reviews, not independent blind labels or whole-function gold; they cover two source-local families. Older physical spend was $0.12569760. Private source, prompts, timelines and adopter identifiers are excluded and cannot be reconstructed from this package.

More funding did not produce proportionate useful reports; syntactic owner proxies mistook already-centralized policy for an opportunity; and discarding scheduling safeguards caused avoidable losses in historical replay. Restoring fairness addressed that mechanism but did not add a public report. Keep the default and retain the bounded source leads. No further recipe, threshold adjustment or provider call is part of this publication.

## Reproduce and inspect

From this directory, Python 3.11+ with no third-party packages or credentials:

```sh
python3 algorithm.py
python3 replay.py --output /tmp/budget-ranking-replay.json
python3 replay.py --case BR-R1-0018 --output /tmp/budget-ranking-case.json
python3 verify.py
```

The first command reruns actual original ordering/admission on one complete frozen public pool. The second reparses recorded public Claude answers and recomputes the 124-case paired report/cost summaries from original admissions. This is recorded-result reproduction, not a whole-corpus retrieval rebuild or a new model experiment. [Expected output](data/expected-replay.json) is compared by the verifier; a checksum check alone is not the reproducer.

[Selected full source files](data/selected-source-files.json.gz) support the four readable [case directories](cases); full rendered prompts already contain the exact candidate bodies and context used by the judges. Public pins are `pingdotgg/t3code@6577c6b6185167c0e502fa01f9e8e8f2dee6ff25` and `BerriAI/litellm@fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f` (enterprise excluded). License texts are in [licenses](licenses); file hashes, exact pins and source scopes are in [the source manifest](data/source-manifest.json) and recordings.

To hydrate every referenced file from an already available local clone, without fetching:

```sh
python3 hydrate.py --repository BerriAI/litellm --git /path/to/litellm --out /tmp/budget-source
```

[DATA-CONTRACT.json](DATA-CONTRACT.json) specifies the original producer revision, dependency lock, external candidate pools, backgrounds, split inputs and original ledgers needed for a full rebuild. Original implementations are `.txt` data to avoid import-time writes; only explicitly selected pure definitions execute in `algorithm.py`. [Specifications](data/specifications.json) retain tested configuration, while [provenance](data/provenance.json) records original hashes and any privacy-only comment substitutions. No full corpus is duplicated. A live rerun would require separate authorization, exact pinned inputs and adopter-owned credentials; this package has no provider execution path.

The two paid-study background hashes both match the separate [goldens catalog at the migration pin](https://github.com/gigaverse-app/dry-lint-goldens/blob/bb29c4b71987008d06c2381a68b6833b6d542e3e/catalog.json). [Exact hash-to-package lookups](data/background-catalog-lookup.json) distinguish these matches from untested or unavailable historical inputs. Acquire them outside this source repository:

```sh
git clone https://github.com/gigaverse-app/dry-lint-goldens.git /tmp/dry-lint-goldens
git -C /tmp/dry-lint-goldens checkout --detach bb29c4b71987008d06c2381a68b6833b6d542e3e
python3 /tmp/dry-lint-goldens/corpus.py verify
python3 backgrounds.py --goldens /tmp/dry-lint-goldens --out /tmp/budget-backgrounds
```

`backgrounds.py` reads exact Git objects and verifies their study SHA256. The command supplies frozen token weights and competitors, not missing original pools, private histories, or new judge answers.
