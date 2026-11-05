# What a zero-duplication backlog actually improved

Use duplicate cleanup to reduce the number of places that own a rule, and show
that reduction with concrete callers. A clean counter alone does not establish
a bug fix, a faster program or a smaller implementation.

[pytest-obligation #206](https://github.com/gigaverse-app/pytest-obligation/pull/206)
merged on 5 November 2026. This case compares parent
[`d39f77e`](https://github.com/gigaverse-app/pytest-obligation/tree/d39f77ea343a25bf0a065376ea7a50ed38c7b2f6)
with merge
[`389c5bb`](https://github.com/gigaverse-app/pytest-obligation/tree/389c5bb84f7ab186fa9c7815c2e15cb9332b67a4).
It follows the [full adoption playbook](../adoption-playbook.md).

## The demonstrated benefit

| Behavior | Before | After | Why this helps the next change |
| --- | --- | --- | --- |
| Module import bindings | Coverage, handoff scanning and report inventory implement alias handling | One `import_bindings` owner, reused by module and scoped scans | Relative-import or alias fixes have one implementation to update |
| Selection-gap grammar | Contract validation and Django proofs independently parse the same key | One framework-free `gap_combination` parser | A valid gap cannot diverge merely because its grammar was edited in one caller |
| Lost-reply lifetime | Redis, MongoDB and Kafka each create a counter, install an observer, yield and restore | One `counted_reply_breaker`, with backend observers and error factories supplied | Lifetime changes reach all three adapters; driver semantics remain explicit |
| Lost-reply counting | Ledger and generic counter independently increment, retain and raise the chosen failure | Ledger inherits `LostCommitReplies` | The count and exception-identity rule has one owner |
| Poison isolation | First-tick and subsequent-poll checks separately enforce healthy progress and owed work | One oracle; later polling explicitly permits per-identity backoff | Reporting and dropped-work checks cannot drift independently between polls |
| Wagtail test setup | Several bindings directly enqueue the same kind of purge | One enqueue/identity helper, with URL choice and recorder reset at callers | Arrangement stays consistent without coupling distinct test observations |

These are change-locality improvements, not measured incident reductions. One
fix now reaches several consumers through their shared owner. Existing tests
continue to exercise each consumer's contract, including real database and wire
boundaries.

The refactor also made previously implicit differences visible: resolved Django
transactions versus broad publication scopes; a first poison tick that must fire
versus a later tick allowed to back off; driver-specific reply failures; and
binding guards versus a full contract that mutates test state. The shared owners
and those boundaries are documented in the consumer's
[architecture](https://github.com/gigaverse-app/pytest-obligation/blob/389c5bb84f7ab186fa9c7815c2e15cb9332b67a4/package/docs/architecture.md#shared-analysis-and-fault-policy).

## What the evidence does and does not show

| Measure | Parent | Merge | Interpretation |
| --- | ---: | ---: | --- |
| Accepted baseline pairs remaining | 32 | 0 | The accepted backlog was exhausted |
| Cumulative pairs marked cleaned | 8 | 39 | 31 additional pair outcomes; not 31 independent refactorings or fixes |
| Dismissed baseline pairs | 0 | 1 | Strict Django transaction detection and broader publication analysis retain independent meaning |
| Library Python files | 152 | 156 | Four shared modules added |
| Library source lines | 33,144 | 33,182 | 38 more lines, including documentation and imports |
| Library function definitions | 1,619 | 1,615 | Four fewer definitions, including nested functions and methods |
| Non-docstring AST statement nodes | 13,547 | 13,523 | 24 fewer statement nodes; a structural measure, not a complexity or speed score |

The source measurements cover tracked `package/src/**/*.py` at those two exact
commits. Line counts use `splitlines()`; function counts include sync and async
AST definitions; statement counts include imports and definitions but omit
standalone string-expression docstrings. Other files, such as demo setup and
baseline metadata, are outside these source counts.

**No demonstrated functional bug fix.** This was a behavior-preserving
consolidation. There is no before-failing/after-passing behavioral reproduction
establishing a bug fixed by #206. Passing existing tests supports preservation;
it does not prove a previous bug existed. Reduced future drift is a plausible
maintenance benefit, not an observed reduction in production errors.

**No demonstrated runtime speedup.** The cleanup introduced no performance
benchmark or algorithmic speedup. It adds helper calls, and the set-valued
selection adapter now builds the shared ordered list before converting it to a
set. That allocation is a tradeoff, not an optimization. Do not infer lower
latency, CPU use or memory from fewer duplicate pairs.

**Simpler ownership, roughly unchanged size.** The diff replaces repeated
policy with focused shared helpers and explicit parameters. It also adds module
boundaries, imports and documentation. The benefit is fewer independent places
to edit, not a dramatic reduction in lines or abstractions.

## Validation and operational value

The [final CI run](https://github.com/gigaverse-app/pytest-obligation/actions/runs/42027016021)
passed Python 3.11-3.14, both PostgreSQL driver lanes, MongoDB, Kafka, Redis/Celery,
adopter demos, upstream Celery regression sensitivity and fixture validation.
Local checks included 1,621 core tests and 486 PostgreSQL tests, followed by
focused reruns after extraction. These results bound the preservation claim to
the exercised behavior.

The independent [full GitHub audit](https://github.com/gigaverse-app/pytest-obligation/actions/runs/42027009025)
covered 1,656 functions and 611 candidate pairs: 100 settled by rules, 506 reused
verdicts, five new judgments and zero reported duplicates. Its subsequent
ratchet reused all 511 judged answers, made zero new model calls, and changed
neither baseline, progress nor README. This is measured savings in repeated
judging work; it says nothing about the consumer's runtime performance.

A prior [independent audit](https://github.com/gigaverse-app/pytest-obligation/actions/runs/42025677173)
found the Wagtail arrangement pair after a local sweep had reported clean.
Identical-model judgments can vary. Review concrete findings and preserve useful
verdicts; do not repeatedly rejudge until a run happens to pass. The Wagtail
helper was consolidated and the other findings were inspected before the final
cached audit. A zero-result sweep is a result for that candidate set and policy,
not proof that no duplication exists anywhere in the repository.

## What to carry into dry-lint

1. Report an ownership change with a real example alongside the pair counter.
   Several pair edges can represent one duplicated rule; deleting or moving an
   endpoint can retire several edges at once.
2. Keep before/after evaluation pairs. A detector that finds the original
   duplication but keeps blocking the shared-owner adapter punishes the desired
   repair.
3. Keep meaningful variants explicit. Backoff, driver errors and scoped import
   resolution belong in the shared contract; independent test oracles and
   acceptance policies need source-based justification to remain separate.
4. Capture uncertainty instead of training from every dismissal. Whether two
   persistence controls must remain independent requires their callers and test
   purpose. A different backend alone is insufficient evidence.
5. Separate audit economics from application performance. Cache reuse is a real
   measured result, but it is a different metric from faster application code.

## Replayable regression examples

[`examples/pytest-obligation-gold.toml`](../../examples/pytest-obligation-gold.toml)
contains 15 public, pinned function pairs: six duplicates, six separate pairs and
three borderline cases needing omitted caller/policy context. Four families
include both the repeated implementation and its repaired delegation. Every
snippet has a source link and content checksum. No answer or suppression comment
was injected into judge input.

Labels come from this agent's source review informed by the merged change. They
are not independent human review, a multi-model majority or a random sample.
Borderline rows are deliberately excluded by the existing benchmark. The
pair-only benchmark cannot see the missing data flow in those rows. Do not use
this small panel to recalibrate production thresholds or claim population recall.

Run the ordinary benchmark with the adopter's own credentials:

```bash
dry-lint bench --gold examples/pytest-obligation-gold.toml --preset sonnet
```

Two fresh `sonnet` / `dry-v2` runs on the 12 non-borderline pairs produced the
same aggregate result: four of six expected duplicates reported and blocked;
four of six expected separate pairs left unreported. One additional separate
pair was warning-only, and one was falsely blocking. All four repaired
delegations were correctly left separate. Each run cost approximately $0.038
for this small panel. These are diagnostic counts, not population accuracy.

The second run retained per-pair explanations. It missed the original
reply-breaker lifetime and Wagtail arrangement as backend/test templates. It
called the strict-versus-broad transaction policies drifted and blocking, and
SQL membership-versus-rewriting drifted at warning level. It also called the
pre-repair gap parsers drifted because they return errors differently, even
though the shared grammar and the caller-specific diagnostics need separate
judgments. No label, prompt or threshold was changed to make those results pass.
This panel therefore exposes both useful detections and unresolved judge
limitations. Future judge work should improve these cases without regressing
the four post-repair controls, then validate on a fresh independent sample.

The offline `tests/test_cleanup_gold.py` checks provenance and exact function-body
transport, guards all six positive retrievals in the small frozen panel, and
requires both pre- and post-repair cases. It does not mock a judge into agreeing
with the labels or claim full-repository retrieval recall. `bench --comparer`
against dry-lint's checkout cannot find these consumer functions; use the
isolated panel test, or the corresponding pinned consumer checkout.
