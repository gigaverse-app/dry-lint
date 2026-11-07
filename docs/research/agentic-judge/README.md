# Source-reading judges clarified context, but added no reports in this experiment

**Do not enable this recipe by default.** In the corrected nine-pair comparison, the source-enabled judge resolved two source-supported non-reporting questions that the body-only judge left uncertain. Both reported the same useful test-tool factory at .90. The first-round checkpoint report was also already covered body-only. Source access provided a narrower benefit—clarifying context—without an observed additional duplication report, at higher cost. The corrected comparison is complete; unstarted requests remain unknown. Merging this record makes the original tool protocol, comparator repair and recorded decisions inspectable without another paid experiment.

## Problem, hypothesis and practical change

A dry-lint judge decides whether two similar-looking functions contain an operation worth sharing. Bodies can leave caller gates, helper ownership or delegation unclear. The hypothesis was that a judge could choose useful supporting source, make better decisions, and reveal what a cheaper single-request judge should receive mechanically. A useful report identifies a shared operation while preserving caller-specific behavior; it does not claim that entire functions are interchangeable.

Ordinary Claude judging supplies both full function bodies, names and the adopter's policy. The experiment changed the judging stage:

```text
Body-only:    full function pair → judge → cited final decision
Source tools: same function pair → judge ↔ bounded pinned-source reads
                                      → cited final decision
```

Tools could list bounded paths, read exact lines or symbols, inspect imports and find lexical references in an allowlisted Git snapshot. They could not execute target code, access the working tree or network, read labels, or mutate source. Each case allowed at most six provider rounds, 1,024 output tokens per round, roughly 24,000 returned source characters and $0.15 spend. The final submission required brief evidence citations. A certain `duplicate` assessment (a useful shared operation) or `drifted` assessment (conflicting outcomes of that operation) at score ≥.8 produced a report; this threshold is a reporting rule, not a calibrated probability. Invalid, capped, missing and uncertain answers remained unknown.

Two first-round controls requested UI text containing spaces or hyphens through an identifier-only reference tool. The single second-round mechanism change replaced it with literal-text search outside supplied function regions, examining at most 160 prioritized files and returning at most eight sightings. Lexical sightings do not establish runtime ownership, and bounded empty searches prove no absence. Model, semantic policy, final validation and caps stayed fixed; different cases were selected.

## What ran

A **case** is one nominated function pair. A **family** groups related source operations or overlapping endpoints so closely related cases do not cross the learning/check split. These were offline, observed development datasets, not deployed traffic or a pristine population holdout. Candidates came from dry-lint's native term-frequency/inverse-document-frequency similarity arm, which ranks functions using their source tokens. Independent reviewers assessed scoped partial operations and counterarguments in pinned source; model agreement was not truth.

An initial eight-case diagnostic froze informative disagreements and positive/separate controls before tool responses. Four learning cases supplied observable traces. A deterministic extractor then added imports, nearby lines and bounded lexical references to six other families. Claude and Jev each ran with and without those additions: **24 valid requests, zero recovered reports, zero lost reports and zero new false reports for either model** at .8. That fixed extraction recipe did not improve reporting on this panel.

The funded source-tool rounds used four public pinned corpora. Round one started eight novel pairs and four controls; round two started nine different novel pairs and four controls. “Novel” means absent from prior pair/endpoint registries with known file/family exclusions, not proof of semantic novelty. Eight first-round and seven second-round selected pairs never started and remain unknown. Four additional protocol-check cases were funded in round one but are not pooled into the novel comparisons.

We call the source-enabled Claude judge the **teacher** because its observable reads informed the extractor; its answers are observations, not source labels. Every started novel pair received a separately keyed body-only control. The final comparison preserves the full source bodies, user semantic question, model, 1,024-token cap, final schema and .8 reporting rule. **The corrected second-round procedure is different:** it explicitly limits evidence to supplied source and asks for a final submission or uncertainty. The teacher procedure permits supporting reads. This is a corrected comparator, not a comparison that changes only tool availability or a changed teacher. Each request has one observed model sample.

## Results with the corrected comparator

| Novel-pair result | First round: 8 pairs | Second round: 9 pairs |
|---|---:|---:|
| Certain body-only finals → source-enabled finals | 6/8 → 6/8 | 6/9 → 8/9 |
| Valid finals, including explicit uncertainty | 8/8 in both arms | 9/9 in both arms |
| Reports: body-only → source tools | 1 → 1 | 1 → 1 |
| Pairs with certain finals in both arms | 6/8 | 6/9 |
| Reporting changes within those certain pairs | 0/6 | 0/6 |
| Established useful added reports / lost reports | 0 / 0 | 0 / 0 |
| Confirmed false novel reports | 0 in either arm | 0 in either arm |
| Source-supported non-reporting uncertainty resolutions | 0 | 2 |
| Uncertain in at least one arm | 2/8 | 3/9 |
| Actual novel judging cost: body-only → source tools | $0.088006 → $0.153436 | $0.085286 → $0.233598 |

The remaining second-round uncertainties are not negative labels: one small source-positive predicate is uncertain in both arms; two source-supported non-reporting decisions are uncertain only body-only. No population precision or recall estimate follows from these small, selected panels.

## Concrete findings

**Checkpoint diff target construction** (`AJ-R1-92702b5c40cb27a7`) is a useful shared pure builder. It preserves missing-input checks and distinguishes full-thread from turn-range diffs; web enablement and unconditional query hooks remain caller-specific. The teacher made two reference searches, returned six new lines, cited one, and reported .82. The exact body-only control reported .86. This useful extraction was already covered, so it adds no recall.

**A shell/editor tool factory for integration tests** (`AJ-R2-79b342568fc7ba88`) was independently accepted. Both getters reject exactly `None`, register the same tools in order, and return fresh specifications bound to the workspace. A test-only factory can share that operation while preserving registration timing, fresh mutable objects and unrelated tests' defaults. Both corrected body-only and teacher reported .90. Supporting references were real evidence, but the report did not require them in this sample; this is test scaffolding reuse, not a production library improvement.

Two context gaps explain the narrower source benefit:

* **Plugin-context accessors** (`AJ-R2-54b6abcd0f86aeb6`): body-only could not establish whether identical-looking context names denoted the same provider. The teacher read supporting definitions and cited 15 new lines, identifying different private contexts, value types and provider contracts. It gave a certain non-reporting decision, consistent with independent source review.
* **Proxy base-URL wrappers** (`AJ-R2-9d94b5ed1e94eaf2`): body-only asked for the delegated helpers' bodies. The teacher retrieved supporting definitions and cited 31 new lines. One contract validates configured URLs and may return `None`; the other falls back to the request URL and appends its root path. Source review supported keeping those contracts distinct. The teacher resolved uncertainty without adding a report.

Those are observed, source-supported differences consistent with the retrieved evidence. Because the procedural instructions also differ and each arm has one sample, we cannot attribute the difference solely to tool availability or claim a stable effect size.

Source access also left useful operations unreported. The accepted **lazy sequential Map/Headers callback loop** (`AJ-R2-b2baa757d0e06e7c`, a control) must preserve callback order, failures, `thisArg`, Map's live traversal and Headers' snapshot behavior. The teacher rejected it as boilerplate and did not retrieve supporting source. The novel **three-kind file-mutation predicate** (`AJ-R2-294585ab744e5e23`) is only minor convenience, with approval/sandbox policy kept separate; both arms remained uncertain at .30. The first-round architecture predicate also stayed below threshold. Access to more files did not automatically fix contract judgment.

Two source disputes remain explicit. The first-round WSL/SSH menu-row proposal conflicts with an archived separate assessment; its teacher tool error supplies no report benefit. The second-round **Windows shell-prompt rewrite** (`AJ-R2-f9cf78df16c6039a`, a control) was reported as drift at .80, but new source review distinguishes case-sensitive substring replacement from token-aware, case-insensitive rewriting. Its archived positive and new related assessment are both preserved. R2 has **one supported teacher report excluding that dispute, or two counting the prior positive**. Established paired recoveries remain **zero either way**; the controls did not receive paired body-only calls. The disputed report is neither an unqualified gain nor a confirmed false report.

## Comparator repair and what the failures mean

The original nine second-round body-only requests retained instructions to use unavailable source tools. Five requested those tools instead of submitting a verdict. Those replies remain unknown and cannot support a no-benefit conclusion.

A first repair corrected that guidance but forced the terminal tool. The provider rejected four requests with HTTP400 because this model does not support forced `tool` or `any` choice; five halted before reservation. There were no model answers and no usage. **$0.127882 remains held as an unknown maximum**, not zeroed or treated as settled spend. Our software development kit (SDK) mock had established serialization, not server capability. This infrastructure failure is not a scientific negative.

The final repair changed only `tool_choice` back to the original `auto`, retaining the corrected supplied-source guidance. All nine cases received new identities; neither failed cases nor favorable outcomes were selected. Root ran one physical smoke request—a one-case compatibility check—and then the other eight under a separate fresh $0.20 ledger. All nine returned valid cited finals: six certain and three uncertain. Independent parsing of the raw receipts exactly matched root's strict observations. Old responses, source labels, first-round uncertainties and the original halted ledger remain unchanged.

## Decision and lessons

Retain the bounded source tools and traces for investigation, but stop this tested recipe as a default production improvement. It clarified two real context gaps, at greater cost, while the useful reports were already produced body-only. The generic trace-derived context replay also added no reports. The evidence supports targeted understanding of helper definitions and context bindings; it does not establish increased duplication-report recall, universal lack of source benefit, or a tested production fallback policy.

The practical lessons are to expose tools that accept the evidence being sought, inspect evidence actually cited rather than retrieval volume, validate a comparator's procedure, and distinguish an accepted partial operation from an added report. Protocol failures and explicit uncertainty must not become false negatives. No further calls or variants are proposed in this experiment.

## Reproduction and accounting appendix

The [machine metrics](data/metrics.json) preserve paired outcomes, uncertainty, costs and the claim-to-evidence map. The [recordings](data/recordings.json) contain all nine corrected second-round pairs, unchanged full function bodies, exact initial teacher and corrected body-only requests, tool schemas, observable source-tool results, sanitized answers and accepted source categories. [Representative answers](CASES.md) give the original decision text beside the interpretation. [Original implementations](data/original/README.md) include the bounded source harness, literal search, final parsing, request adapters, corrected comparator, original evaluation scripts and dependency lockfile. They are archived as text to prevent import side effects.

Run anywhere with Python 3.11+; no package installation, provider, credentials or lab checkout is needed:

```bash
python3 reproduce.py --output /tmp/agentic-recorded-results
python3 native.py
python3 audit.py
python3 reproduce.py --case AJ-R2-79b342568fc7ba88
```

Use a fresh output directory. `reproduce.py` revalidates native source spans and licenses, exact request hashes, terminal protocol and citations, parses the recorded final submissions, recalculates the reporting comparison and sums usage/cost. `native.py` executes the **unchanged original** `strict_submit` and `final_decision` function ASTs from the archived implementation on all 18 recorded finals. It avoids importing the harness adapters, whose top-level code loads other experiment modules. This is a portable recorded-source/final-decision reproduction, not new judge execution, full source-search replay or a full experiment rerun. Teacher tool results are recorded observations; the search universe is not replaced with the 18 selected files.

[Reproduction and acquisition](REPRODUCTION.md) explains exact local Git hydration, archive restoration, original commands and missing full-run inputs. [Provenance](data/provenance.json) records original hashes separately from publication transformations. The [rerun manifest](FULL-RERUN.json) enumerates the source scopes, complete registries and recordings needed for historical replay. Source is redistributed only for the four licensed public pins in [source-pins.json](data/source-pins.json), with [license notices](licenses/). Historical redistribution holds remain source-free; private adopter source, prompts and identifiers are absent. Hidden reasoning and transport identifiers are removed, with original output hashes retained separately.

| Settled research spend | USD |
|---|---:|
| Funded round-one teacher, including controls and four protocol checks | 0.356584 |
| First-round eight body-only controls | 0.088006 |
| Funded round-two teacher, including controls | 0.320782 |
| Original flawed nine body-only controls, preserved | 0.075302 |
| Corrected auto-choice nine controls | 0.085286 |
| **Funded direction total, settled** | **0.925960** |
| Earlier eight-case teacher pilot, separate | 0.252152 |
| Deterministic two-model context replay, separate shared comparison | 0.24912180 |

The failed forced-tool repair additionally retains **$0.127882 unknown reserved maximum**, separate from all settled amounts. The fresh $0.20 repair cap is an allocation, not spend; its settled charge is the $0.085286 above. Old ledgers were not reset. Research funding and cache reuse are distinct from the normal simulated $0.04 estimated deployment ledger; no deployment budget-fit claim follows.

For matched novel cohorts, summed API times were body-only 38.42 seconds versus teacher 38.29 in round one, and corrected body-only 32.12 versus teacher 52.72 in round two. These are API sums, not parallel wall-time speedups. The corrected control used one serial smoke then eight at concurrency four; teachers ran at concurrency four and made multiple rounds. Offline extraction, source-tool CPU and validation are separate. Summed per-case R2 retrieval counts were 249 new source lines, 10 repeated initial-body lines and 61 new lines cited; they are not independent-family counts or proof of improved accuracy.
