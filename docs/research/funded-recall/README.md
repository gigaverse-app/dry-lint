# Improving dry-lint's recall without buying more noise

Dry-lint should find more code that developers would benefit from sharing, while preserving the useful reports it already makes. The constraint is practical: a change has a small judging budget, so retrieving more vaguely similar functions can spend that budget before a real duplicate is examined.

This research investigates **where useful duplicates are lost and which specific interventions recover them**. The unit of success is an additional, independently reviewed useful report. A higher similarity score, more candidates, or agreement between two models can help explain a result, but does not by itself demonstrate that success.

The first completed study in this evidence PR asks whether inexpensive, mechanically selected source context can make the judge more reliable. **Neither tested context recipe recovered a report.** The result tells us to stop those two recipes and explains why fixed windows are a poor substitute for selecting complete operations. Read [the context study](context/README.md) for the hypothesis, implementations, two concrete misses, results, and decision.

## Where the research fits

```text
Changed code
    |
    v
Retrieve similar code --> apply scope and score rules --> spend judging budget --> report
    |                         |                               |                    |
    |                         |                               |                    + useful to a developer?
    |                         |                               + enough context for a correct verdict?
    |                         + did a useful pair survive the filters and ordering?
    + did we find the pair at all?
```

A missed report can originate at any of these stages. For example, a better vector may raise a duplicate's rank while lowering its score below the eligibility floor. A smarter judge cannot recover a pair that was never funded. We therefore measure the stage changed by each experiment and separately check whether its gains survive through reporting.

The research program explores four groups of ideas:

| Question | Practical approaches being evaluated | Evidence needed to justify a change |
| --- | --- | --- |
| Can retrieval recognize equivalent operations despite different surrounding code? | Operation-sized blocks, small CPU embeddings, sparse vector expansion | Additional useful candidates that survive filters and budget |
| Can existing source signals make ranking more precise? | Token cleanup, linked documentation, operation/contract tokens, model-and-function signals, combinations of these signals | Gains on supported known examples and independently reviewed new candidates, with losses reported |
| Can the same budget buy better coverage? | Candidate ordering on historical PRs and separate public-source simulations | More useful reports at the same per-change cap, including displaced old reports |
| Can cheaper judging use better evidence? | Mechanical source excerpts and a bounded source-browsing judge | Paired decisions on the same cases, checked against independent source review |

These are research questions, not interchangeable presets or promises of improvement. A result for one implementation does not close the entire direction.

## What the context study established

The motivation was straightforward: Jev costs less than Claude, and may miss useful sharing opportunities because relevant ownership or implementation evidence is absent from its input. We tried adding nearby source, then replacing long-body prefixes with windows distributed across the body.

| Experiment | Actual comparison | Result | Decision |
| --- | --- | --- | --- |
| Add imports, nearby source, and bounded name references | Six source families; same model with and without added context | No recovered report for either model; all four accepted partial-operation positives still missed | Stop this source-bundle recipe |
| Show start/middle/end windows of long functions | 12 new pairs plus four controls; same questions and reporting rule | Neither model reported either of the two independently confirmed novel operations; one prior Claude positive control report was lost | Stop fixed-position body windows |

The second result is informative because source inspection exposed the mechanism's weakness: a useful operation can fall between windows, and a windowed input can omit evidence the baseline contained. It does not prove that every missed verdict was caused by truncation. The two rounds used 80 fresh provider calls costing $0.70619572. Full details and comparison limits are in the [study](context/README.md).

## How to read the evidence

**Known-example evaluation** asks whether a method retains or recovers already labeled pairs on the exact corresponding source/background. **New-candidate discovery** asks whether it finds additional useful opportunities. **Historical PR replay** applies captured changes and their own policy/version; a public-source budget simulation is a separate experiment. These populations are not pooled into one accuracy number.

Source reviewers inspect complete pinned functions, signatures, documentation, callers and existing helpers. They may accept a small shared operation while rejecting a whole-function merge. Related code, already-shared implementations, disputed utility and missing answers remain visible. “Reported” means the configured model rule fired; “useful” means the source assessment supports the proposed action.

Each completed direction should provide a readable report, paired outcome data, cost receipts, and a verification command. The [research-output skill](../../../.agents/skills/research-output/SKILL.md) describes this writing standard. For the published context evidence:

```bash
python3 docs/research/funded-recall/context/audit.py
```

The audit recomputes costs and report changes and checks the published file hashes. Full rendered requests and source-review archives remain in the lab; this repository's hash receipts cannot reproduce omitted artifacts. These are observed development results, not pristine population holdout measurements. Publication of an experiment records a decision; it does not itself change production defaults.
