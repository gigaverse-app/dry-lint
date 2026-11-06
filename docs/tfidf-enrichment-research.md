# Research plan: teach TF-IDF about related implementations

Status: documentation, fragment, containment and token-audit probes are complete. A protected name-weight
channel improves funded retrieval on development and holdout, but actionable-report evidence is limited.
Production retrieval, judging and budgets remain unchanged. [Frozen backgrounds](benchmark-backgrounds.md)
now preserve the corpus context of the public and private source goldens.

## Objective and budget

Find more actionable duplicates whose implementations use different vocabulary or syntax, by enriching sparse
TF-IDF evidence with documentation, contextual concept relationships, and reviewed consolidation examples.
Keep the existing estimated **$0.04 per-PR judge budget contract**. Experiment spending is unrestricted by the
user, but a production proposal must demonstrate useful findings within that same operating budget. This is
not a proposal for a hard provider-metered ceiling. Record measured provider usage separately from estimates.

Start with sparse enrichment, not another embedding replacement. Keep the existing detector model-free and
stateless. Any learned artifacts would be built offline, versioned, and consumed deterministically by an
experimental comparer. Slow model work must stay outside ordinary detection, behind an appropriate cache.
Adopters supply their own credentials; private repository evidence must not become a shared training corpus
without authorization.

## Evidence that motivates this plan

| Existing evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| [Embedding benchmark](benchmark.md#detector-tf-idf-and-embeddings): TF-IDF ranks 12/13 seed pairs first; jina and Qodo each rank 10/13. TF-IDF indexes 7,195 functions in 4.4 seconds on CPU. | The sparse baseline is strong and inexpensive on that task. | Embeddings are universally worse. Their AUC was 0.85-0.86 versus 0.66, but the judged negatives were TF-IDF mistakes, favoring embeddings on that measure. |
| [Semantic signal trial](semantic-signal-trial.md): unweighted API, argument-binding, and field-flow tokens recover one fresh AI positive but lose two old backend positives when combined. | Adding evidence to one vector can dilute similarity and change which neighbors get scarce slots. | All weighted or documentation-based enrichment will fail. These were particular static features, added without extra weighting. |
| [Channel trial](channel-trial.md): additional channels recover real pairs; combined novel samples contain about 14-15% positives versus 38% in the baseline sample. | More candidates can consume judge budget less productively. | Repository-wide precision or recall. Samples were small, deliberately stratified, and assistant-labeled. |
| [Earlier research](research-plan.md#representations-we-can-reuse): hand-written synonym groups did not improve results; comments and docstrings were listed as untried. | Global synonym replacement is a weak starting point. | Contextual associations learned from descriptions or refactors have been tested. |
| Snapshot pair from the pytest-selective case study: frozen-corpus score 0.275425; full pinned-repository score 0.309721; both below the 0.5 floor. | Corpus composition changes weights, but neither run retrieved this pair. | A full sweep rescued it. That earlier explanation was unsupported; [PR #99](https://github.com/gigaverse-app/dry-lint/pull/99) corrects it. |

These results justify experiments, not a predicted improvement. Broader retrieval must earn its share of the
fixed judge budget. Retaining baseline candidates in a union does not guarantee they remain funded.

## What relationships should mean

Learn a shared operation or responsibility while retaining differences that matter to consolidation.

| Example | Useful common evidence | Differences that must remain visible |
| --- | --- | --- |
| `for`, `while`, `map`, list comprehension | Iteration; sometimes transform-and-collect or filtering | Laziness, early exits, termination, ordering, effects, exception timing |
| Semaphore, mutex, event | Coordination between concurrent tasks | Capacity limiting, mutual exclusion, signaling; these are not interchangeable contracts |
| `copyfile`, `copy2` | Copy a file | Metadata preservation, which mattered to the pytest-selective cleanup |
| Two functions consolidated into a helper | A shared operation that had multiple implementation owners | Caller-specific policy, input validation, lifecycle, and the extracted region's boundaries |
| Two thin callers after extraction | Use of the same operation | They now share its implementation and should usually cease to be duplicate findings |

A relationship can mean exact alias, alternative implementation under stated conditions, same operation with
different guarantees, or merely the same topic. Do not flatten these into one synonym list or assume that
relatedness is transitive. A mutex and an event sharing a concurrency label does not establish duplicated logic.

## Sources of enrichment

1. **Docstrings and local comments.** Associate text with its owning function or statement region. Strip
   boilerplate and repeated license/tool text. Preserve useful contracts such as “preserves timestamps” or
   “must remain independent.” A bag of words can lose negation, so such text is evidence, not an automatic rule.
2. **Markdown documentation.** Resolve explicit symbol references, source links, and examples to their code.
   Start with these high-confidence associations. Module-level or nearby documentation has weaker ownership;
   attaching the same README to every function would create artificial similarity.
3. **API documentation and import resolution.** Give known APIs contextual operation labels, retaining
   qualified identity and guarantees. A name such as `Event` requires resolution before assuming concurrency.
4. **Reviewed consolidations.** Align pre-change duplicated regions with the extracted shared helper. Record
   which behavior was intentionally preserved or corrected. A merge alone does not prove equivalence, and a
   helper extraction does not make entire caller functions equivalent.
5. **Reviewed non-duplicates and post-consolidation code.** Include independent policies, tests that must remain
   separate, adapters, and already-shared implementations. These teach when topical similarity is unhelpful.
6. **Safe transformed examples.** Generate restricted, behavior-preserving alternatives, such as a simple
   append loop and comprehension. Preserve scope and effect assumptions; arbitrary loop rewrites are unsafe.
7. **Repository history.** Identifier renames and description changes can supply vocabulary correspondences.
   Co-changing files are weaker evidence: coupling or adjacent functionality need not mean duplication.

Each association needs source revision, symbol/region, relationship type, confidence, and derivation version.
Missing or unresolved documentation should leave the baseline usable. Generated summaries or concept labels
are an optional later experiment with cached outputs, explicit generation cost, and code-grounded review.

## Sparse representations to compare

### A. Weighted documentation counts

Add selected docstring/comment terms to the existing sparse fingerprint with a small, bounded contribution.
Compare ordinary shared word tokens with a separate documentation field. Shared tokens allow a term in one
function's code to match another's description; field separation makes weighting easier but needs an explicit
cross-field matching rule. Limit contributions by unique concepts or capped counts so verbose documentation
does not overwhelm code. Do not duplicate text to simulate weight under sublinear term frequency.

This directly tests the user's proposal to enrich TF-IDF counts. Compare against an unweighted additive control
to distinguish useful information from the effect of weighting. Freeze a small parameter grid on development
data before evaluating held-out cases.

### B. Contextual concept tokens

Add sparse tokens such as `op:transform_collect`, `op:file_copy`, or `contract:preserve_metadata` when evidence
supports them. Keep original syntax and API tokens. Derive labels first from conservative AST patterns and
explicit documentation associations, then test learned mappings separately.

A loop should not acquire `op:transform_collect` just because it iterates. Similarly, `topic:concurrency` is
weaker evidence than a shared admission policy. Cap generic concepts and count repeated mentions once in an
ablation. Inspect whether the existing document-frequency filter removes broad concept tokens; do not exempt
all concepts automatically, since common concepts can flood neighbor slots.

### C. Learned sparse expansion

Build a contextual association table offline from code-description pairs and reviewed examples. For a token
or small feature pattern, it proposes a few related concept terms with weights and provenance. Apply only a
bounded one-hop expansion; avoid uncontrolled chains such as “event -> synchronization -> every lock.”

Contrast raw co-occurrence with associations discounted by commonness and checked against non-duplicates.
Small repositories may not contain enough independent examples to learn reliable links. Keep support counts,
hold out refactor families, and compare repository-local mappings with reviewed reusable mappings. This can
learn vocabulary relationships while retrieval remains a sparse weighted lookup and cosine calculation.

### D. Soft token matching

As an alternative to inserting extra counts, score selected related token pairs as partial matches using the
same bounded association table. This avoids physically repeating terms, but it is a different similarity
function and must be evaluated separately. Candidate generation must also use the association edges: changing
only the scorer will not surface pairs that never share an inverted-index posting. Bound expansion and measure
runtime. If using a normalized soft-cosine formulation, ensure the token-similarity matrix has the mathematical
properties it requires; arbitrary association weights are not automatically a valid cosine metric.

### E. Separate fields or channels

Compare single-vector enrichment with independently normalized code, documentation, and concept scores. A
weighted field combination bounds how much added text can change the code score. Another variant retrieves a
small enrichment candidate pool alongside baseline TF-IDF and merges their rankings.

Neither weighted fields nor reserved retrieval slots guarantee preservation of baseline findings. Track
displacement both before and after budget selection. Earlier channel results make this a control and an
engineering choice to measure, not the assumed winner.

### F. Learn which candidates deserve judging

Use a small offline-trained ranker over sparse similarities and interpretable features: shared operation,
contract differences, documentation confidence, overlap with an extracted region, existing delegation to a
shared helper, and estimated judge cost. Compare with simple fixed weights first. Its target is actionable
duplication, not general semantic relatedness. A difference may signal valuable drift rather than a negative.

Keep this experiment separate from representation experiments so gains can be attributed. Do not treat prior
judge scores or identifiers of labeled examples as deployable features. A cost-aware ranking must not merely
favor trivial short functions; report which valuable expensive findings it displaces.

### G. Embeddings as a secondary research tool

Retain pretrained code/text embeddings, fine-tuning on reviewed pairs, and contrastive transformed examples as
comparators or offline sources of candidate concept links. They are not the first production proposal. This
tests whether their knowledge can yield a small inspectable sparse mapping without their per-run indexing
cost. Any distilled mapping still requires validation; model-generated associations are not ground truth.

Relevant primary research: [CodeRetriever](https://arxiv.org/abs/2201.10866) uses code documentation and comments
to learn code-text and code-code representations for search. [ContraCode](https://parasj.github.io/contracode/)
uses transformed programs to learn related representations. These support the learning mechanisms; neither
establishes better budgeted duplicate detection for dry-lint or validates sparse distillation.

## Experiment order and controls

| Stage | Experiment | Main question |
| --- | --- | --- |
| 0 | Reproduce baseline on pinned full repositories and inventory documentation coverage | Which misses arise from extraction, floor, ranking, suppression, budget, or judgment? |
| 1 | Docstrings/comments: unweighted control, capped weighted counts, separate fields | Does local intent text help without diluting known positives? |
| 2 | Add explicitly linked Markdown passages; compare shuffled symbol-text associations | Does correct documentation ownership add information beyond generic vocabulary? |
| 3 | Conservative operation tokens with contract-specific counterexamples | Can alternative syntax share useful sparse evidence without merging unrelated patterns? |
| 4 | Learn bounded contextual expansion from reviewed history; compare hand-written and co-occurrence controls | Does learning improve on the failed global synonym approach? |
| 5 | Compare expanded counts, soft matching, and separate retrieval channels | Which use of the same evidence yields the best funded candidate set? |
| 6 | Fixed-weight versus learned and cost-aware ranking | Can additional recall reach the judge productively within $0.04? |
| 7 | Only if justified, embeddings or generated summaries as offline teachers | Does learned semantic knowledge add value beyond cheap sparse sources? |

Run one source or mechanism at a time before combinations. Include documentation-removal and stale/misleading
documentation controls, generic synchronization examples, independent policies, and post-refactor adapters.
Stop advancing a variant when its new evidence mostly consumes slots with topical matches. Preserve negative
results and useful code rather than tuning indefinitely against the same examples.

## Evaluation and adoption gate

- Fit IDF on the full pinned repository, not only the gold functions. Freeze the split before learning mappings
  or choosing weights. Keep all variants of a refactor in one split; use repository/time holdouts as well.
- PR #90 and #91 goldens and earlier regression panels are development/regression evidence after this work has
  inspected them. Add independently reviewed held-out pairs; do not call repeatedly tuned goldens fresh proof.
  Prevent future refactor text, case studies describing a gold answer, or later commits from leaking into a
  historical replay. Public pretrained models may have unknown prior exposure, which limits independence.
- Sample novel proposals blind to variant and score; include a comparable baseline sample. Record ambiguous
  labels and adjudication. Unknown pairs are not automatically false positives, and assistant agreement is not
  an independent human panel. Keep task-run evidence outside the code PR and link concise findings.
- Measure known-positive retrieval, candidate rank, floor failures, displacement, and actionable yield per
  candidate source. Small incomplete gold sets measure known-pair retention, not exhaustive repository recall.
- Measure the full path: proposed -> filtered -> selected within budget -> judged -> reported. Report true and
  false findings, missed previously reported positives, judge calls, estimated and measured spend, cold/warm
  indexing time, memory, and documentation coverage. Distinguish candidate yield from final report precision.
- Keep judge version, prompt, reporting thresholds, cache policy, and estimated $0.04 contract fixed for the
  comparison. Replay candidate admission first; use live judging for new pairs with repeated runs where verdict
  variability could explain the gain. Account for actual cache behavior in PR-sequence replays.
- Pre-register the final held-out comparison after development. Require more actionable true reports with no
  increase in false reports or loss of established protected findings on that comparison. Report sample sizes
  and uncertainty; a tiny favorable result warrants more evidence, not a general superiority claim. A tradeoff
  that fails those conditions is a finding to discuss, not an automatic production change.

Measure offline artifact-building or model costs separately and amortized per PR. A free-looking judge run
must not hide an expensive rebuild. Determine an acceptable indexing-time ceiling from baseline CI use before
the final trial, rather than choosing it after seeing the winner.

## Integration if an experiment succeeds

Implement comparison changes through the existing plugin boundary. Version the experimental comparer and any
artifact by source revisions, extraction/association rules, and corpus policy. Documentation edits must update
affected retrieval inputs even if code is unchanged. Check whether the current change selector notices those
edits, and keep that proposed behavior distinct from scoring changes.

Never reuse verdicts under the production comparer identity for changed experimental scores. Retrieval evidence
and human decisions have different owners: explicit distinct-from decisions remain in code/configuration;
the verdict store is not a repository of human policy. If artifact persistence changes a core file format,
review the format contract and bump its schema. Prototype without changing production stores first.

Deliver an experiment summary with reproducible commands, pinned revisions, the selected configuration,
positive and negative examples, budgeted outcomes, and limitations. Only then propose a runtime change. A
well-supported decision to retain current TF-IDF is also a valid research outcome.

## First probe results

**Decision: do not promote capped docstring/comment additions to production.** They can recover a real lexical
miss, but the tested variants fail to improve known-pair retrieval without regressions. This is an exploratory
retrieval screen, not a final accuracy or $0.04 effectiveness benchmark. No live judge calls were needed because
the variants failed the retrieval gate.

### Frozen method

The experiment used dry-lint `55443cf`, Python 3.14, and production extraction/filtering with the default
three-neighbor limit, 0.5/0.3 floors, and mutual-nearest backlog rule. The full repositories supplied IDF:

| Repository revision | Functions | Functions with description terms | Labeled pairs: duplicate / separate |
| --- | ---: | ---: | ---: |
| pytest-selective `ae1306377dda82d1d0a6fa0b43dbb612d69d72b2` | 272 | 158 | 8 / 0 |
| gigaverse-backend `22dfbe180c6704101658a088cc269a25fa9c82dd` | 5,057 | 2,914 | 33 / 97 |
| gigaverse-ai `78467d3e72508d355eb1fcf923f290a7a69980ef` | 9,907 | 6,988 | 7 / 13 |

The labels are the existing backend 110-pair panel, the semantic trial's 40-pair panel, and pytest-selective's
eight before-cleanup positives. All are regression/development evidence, not a new held-out population sample.
After-cleanup adapters and the mixed-revision pytest-obligation panel were not included in this full-corpus
probe. Compare each variant to this run's baseline; current filtering differs from older trial releases.

Extract the owning Python function's docstring and comments, excluding nested function/class comments, ordinary
string literals, and tool directives. Split words with the existing identifier splitter plus a fixed prose
stop list. Keep at most the first 32 unique terms per function. Repeated prose cannot increase its contribution.
No Markdown text, synthesized concepts, learned associations, new thresholds, or extra candidate slots enter
this experiment. The two weights and cap were fixed before scoring.

- **Unweighted:** append each retained term once as an ordinary `w:` token, using production sublinear TF-IDF.
- **Weighted:** for each token, add `alpha * IDF` if it occurs in the description to its existing unnormalized
  code TF-IDF weight, then normalize the combined vector. Test `alpha = 0.25` and `0.5`. IDF/document-frequency
  filtering sees the union of code and description vocabulary. This is an explicit weighted contribution,
  not repeated text to approximate a fractional count.
- **Shuffled control:** permute entire descriptions between functions with seed 1117, using weight 0.25.
  The control retains the description inventory but removes correct function ownership.

The local probe reused production `TfidfIndex`, `TfidfComparer`, and `Detector`; experimental similarities never
entered the verdict store. Checks covered comment ownership, multiline string indentation, directive/literal
exclusion, the 32-term cap, repetition invariance, zero-weight parity with production vectors and neighbors,
and matching a description term against a code term. Full-corpus scans and targeted score/rank diagnostics
were saved outside the repository alongside the probe scripts. No task-run dumps or private source packets
are included in this PR.

### Retrieval outcome

`Check` means the labeled pair is proposed directly in at least one direction and survives filtering. `Scan`
requires mutual first neighbors. Known separate pairs retrieved are potential judge work, not false reports.

| Variant | Known duplicates in check, of 48 (higher better) | Known duplicates in scan, of 48 (higher better) | Known separate pairs in check, of 110 (lower better) |
| --- | ---: | ---: | ---: |
| Baseline | 46 | 41 | 97 |
| Unweighted descriptions | 44 | 38 | 88 |
| Weight 0.25 | 46 | 40 | 98 |
| Weight 0.5 | 45 | 39 | 95 |
| Shuffled descriptions, weight 0.25 | 46 | 38 | 98 |

The 0.25 variant preserves the identity of every baseline check positive, but adds no known positive. Its loss
of a scan positive is a rank change: the active-showcase duplicate remains above the floor at 0.517, but a
recent-trigger helper wins the first neighbor slot at 0.533. Unweighted enrichment instead drives that same
duplicate from 0.551 to 0.474, below the 0.5 floor. It also loses the backend picture-queue and durable-attempt
duplicates from check. Aggregate counts alone would hide the AI panel's swap of one positive for another.

There is a concrete positive signal: unweighted descriptions bring the repeated campaign-community selection
pair from **0.466 to 0.515**, making it retrievable in both check and scan. Shared campaign vocabulary appears
among the strongest matching terms. The 0.25 version reaches only 0.482. These observations establish that
enrichment can surface this known miss, not that the current weighting scheme is a net improvement.

The motivating pytest-selective snapshot pair remains missed:

| Variant | Similarity | Retrieved above the 0.5 floor? |
| --- | ---: | --- |
| Baseline | 0.309721 | No |
| Unweighted descriptions | 0.295284 | No |
| Weight 0.25 | 0.312421 | No |
| Weight 0.5 | 0.311621 | No |

Both snapshot functions have relevant descriptions, so absent documentation does not explain this failure.
Adding their different prose changes normalization and document frequencies without enough matching weight.

The 0.25 scan introduces 87 previously absent candidate pairs across the three repositories and removes 90;
these are unadjudicated changes, not 87 new duplicates. Its sole added pytest-selective pair is a wrapper and
the filename predicate it already calls, illustrating why additional retrieval is not automatically useful.
Shuffling descriptions preserves the same check-positive count as correct descriptions, further limiting
what can be inferred from that count alone.

The single-run AI index setup rose from about 0.43 seconds to 1.04 seconds at weight 0.25; the whole scan plus
gold scoring rose from 17.3 to 27.4 seconds. These are exploratory wall times, not a controlled performance
benchmark; the prototype also performs a redundant index construction. No speedup is claimed.

### What this changes in the research plan

Keep descriptions as a plausible source of evidence, but do not ship raw or lightly weighted prose addition.
The recovered campaign pair supports trying the field-separated alternative already listed in stage 1:
preserve baseline code weights/IDF, represent description evidence separately, and measure bounded additional
matching and ranking. That is a next experiment, not an implemented fix or a promise of improvement. A candidate
union would still need to prove that useful extra pairs reach the judge without displacing baseline findings
within $0.04. Learned contextual concepts and Markdown associations remain untested by this probe.

## Mining merged consolidations and continuing the loop

### Evidence from actual changes

Recent consolidation PRs provide before implementations, the new shared owner, and surviving after callers.
They are a better source of realistic challenges than constructing more toy synonyms. A shared call is a
discovery lead, however, not a duplicate label: some changes centralize a convention or move an existing owner
without removing two implementations. Review the operation and its contracts before accepting the example.

This iteration inspected 21 merged PRs across nine repositories: backend-common, ci-esta, dry-lint, Due,
frontend-common, gigaverse-ai, gigaverse-backend, gigaverse-mobile and gigaverse-web-app. The mining pass used each merge
commit's first parent as the before revision and the merge result as after. PR descriptions helped discovery;
the source diff determined attribution. In particular, Due's recovery consolidation belongs to #183, not #190.

| Repository | Merged PRs inspected |
| --- | --- |
| backend-common | #251, #293 |
| ci-esta | #98, #106 |
| dry-lint | #73 |
| Due | #180, #183, #190 |
| frontend-common | #915, #925, #1084 |
| gigaverse-ai | #2997, #3317, #3325 |
| gigaverse-backend | #5358, #5359, #5361, #5522 |
| gigaverse-mobile | #3935 |
| gigaverse-web-app | #4328, #4346 |

Mining shared new callees, retained owners and removed helpers produced 300 leads. A spanning forest per
proposed owner, plus explicitly inspected deleted-helper cases, reduced these to 136 review packets. This
avoids treating every edge in one large consolidation as independent evidence. Two model reviews received
before/after source and proposed-owner code, without retrieval scores or variant identities. Agreement at
confidence at least 0.85 in both reviews forms the strict tier; lower-confidence agreement remains provisional.
These are model-assisted labels, not independent human gold, and the models share a provider family.

| New evidence tier | Before duplicates | Before separate | After separate |
| --- | ---: | ---: | ---: |
| Strict | 14 | 33 | 41 |
| All consensus, including strict | 60 | 70 | 112 |

The 60 new positives expand the earlier 48-positive challenge to **108**, with 46 of the additions explicitly
provisional. The 242 new rows span 70 proposed-owner families. Disagreements and uncertainty are quarantined.
Some reviewed leads expose duplication that remains after the PR; a merged consolidation is not proof that
every nearby operation was consolidated. Deleted functions have no invented after-state negative. Surviving
after callers are negative controls only when both reviews find the meaningful duplication removed.

[The public Due panel](../examples/due-consolidation-gold.toml) contributes seven source-reviewed before
positives and three after controls from [#180](https://github.com/gigaverse-app/due/pull/180),
[#183](https://github.com/gigaverse-app/due/pull/183) and
[#190](https://github.com/gigaverse-app/due/pull/190). Each excerpt has an immutable revision, source identity,
source URL, SHA-256 and rationale. These seven are a subset of the 60, not additional positives. They cover raw
row locking, clock transport, recovery/delivery, subprocess orchestration, effect-attempt setup and retry
fixtures. One same-file positive documents a retrieval-policy exclusion. Private source and review packets
remain outside this public repository. Exact Due syntax requires Python 3.12+ for extraction; older supported
Python versions still validate the fixture format and provenance.

### Frozen development split and budget accounting

Reserve whole PR families backend-common #293, frontend-common #925, gigaverse-mobile #3935 and
gigaverse-web-app #4346 as holdout. Keep Due and its vendored backend lineage together in development.
Previously inspected panels are development evidence. Do not randomly split related pairs or let after code
teach a before-time index. Through the fragment probe the holdout remained unscored. The later protected
name-weight channel passed the development retrieval gate and was then evaluated once on this holdout.

The new development panel contains 176 rows: 48 positives and 128 separate controls across 26 PR/phase
batches and 48 proposed-owner families. These 48 positives are from the newly mined panel, not the original
48. Full tracked Python and TypeScript source, excluding migrations, supplies each revision's corpus. This
diagnostic scope intentionally includes tests and scripts. Of the 48 positives, 41 pass cross-file and other
pair filters, and only 26 also fall within default file scope. Report these exclusions separately from ranking
failures; broader retrieval cannot fix a pair that policy excludes.

For each PR/phase batch, query both sides of its labeled pairs against the full repository. Use the production
Ledger and unchanged Sonnet concept-judge cost estimate to select candidates within $0.04. This is a cold,
PR-sized diagnostic batch, not a reconstruction of the original CI diff, cache or provider bill. A funded
positive means its pair receives a judge slot, not that a live judge confirms it. No live classifier evaluation
was run for these variants. Unknown candidates are neither credited as duplicates nor counted as false reports.

### Separate fields and protected retrieval

The second iteration preserves the original code TF-IDF and creates an independently normalized description
index with the same 32-term cap. Score `code + alpha * (1 - code) * description` for fixed weights 0.1 and 0.2.
Python ownership rules remain as in the first probe. TypeScript uses comment nodes inside the extracted
function, excluding nested function comments and directives; leading JSDoc outside that span is unavailable.

The third iteration preserves baseline neighbors and appends at most one description neighbor, requiring
description similarity at least 0.65 and code similarity at least 0.15. Place all baseline candidates before
extras during budget selection so extras cannot displace baseline funded findings.

The fourth iteration replaces that extra channel with exact normalized Python AST statement fragments:
windows of one to three statements, 25 to 200 AST nodes, at most 64 fragments per function, with consistent
local-name normalization while preserving callees, attributes and literals. Ignore fragments appearing in more
than `max(2, 0.005 * corpus_size)` functions. Append at most one neighbor with code similarity at least 0.1,
ranked by the largest shared fragment; protect the baseline batch as above. TypeScript uses baseline retrieval.
This is an exploratory structural signal, not learned synonymy or a production plugin.

| Variant | Retrieved positives / 48 | Funded positives / 48 | Funded known separate / 128 | All funded candidates |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 15 | 15 | 7 | 88 |
| Separate descriptions, weight 0.1 | 15 | 15 | 7 | 89 |
| Separate descriptions, weight 0.2 | 15 | 14 | 7 | 90 |
| Protected description neighbor | 15 | 15 | 7 | 90 |
| Protected exact fragment neighbor | 15 | 15 | 7 | 95 |

All variants retrieve six strict-tier positives. The 0.2 bonus loses funding for a previously funded backend
policy-assembly positive despite retaining it in retrieval. No tested variant gains a fixed-panel positive.
The fragment channel funds seven additional candidate occurrences; preliminary source inspection suggests
fixture-loading and sport-selection operations worth reviewing, but also repeated assertions and shared-call
controls. These post-selection leads are not retroactively added to the frozen panel or claimed as validated
recall gains. They need separate adjudication and future held-out confirmation.

**Decision: retain production retrieval and the existing budget contract.** Raw documentation, separated
documentation and this bounded exact-fragment probe have not passed the promotion gate. The larger challenge
shows why the earlier near-saturated panel was insufficient: useful consolidations often extract a small
operation from otherwise different functions, and some misses are deliberate scope exclusions. Next, review
the newly surfaced fragment candidates and diagnose missed operation boundaries before changing thresholds
or learning a vocabulary. A block-level representation may be more useful than adding prose to a whole-function
vector, but these results do not yet establish that claim. Markdown-derived and learned synonym expansion
remain untested.

### Next registered probe: protected token containment

Test whether partial overlap is lost mainly through whole-function normalization. Reuse original behavior
tokens and corpus IDF, excluding function-name and control-flow tokens from this additional signal. Compute
the IDF mass of the shared token set divided by the smaller function's total IDF token mass. Require at least
eight shared tokens, including three call/attribute/schema-key tokens, containment at least 0.75, and original
cosine at least 0.1. Rank by containment, then shared IDF mass; append at most one allowed neighbor beyond
baseline. Preserve the full baseline batch before budget selection. These parameters are fixed before scoring
this probe. Repeat the development diagnostic first; inspect holdout only if a variant passes the existing gate.
This uses no new vocabulary, documentation, labels or learned expansion at retrieval time. Review all newly
funded candidates separately to detect extra false reports, including unknown pairs outside the frozen panel.

### Registered token audit ablations

Inspect full development-repository matrices before choosing token changes. Test two variants separately:
remove `the and for with from into that this are was were has have had its our their these those` only from
`fn:` and `w:` features; or multiply `fn:` weights by 0.5 before renormalizing. Keep each revision's original
IDF and the unchanged retrieval floors, neighbor count and judge budget. Preserve negation and domain/API
identifiers. These fixed ablations test whether English glue or excessive name weight hurts retrieval; they
are not permission to tune the holdout or assume all rare names and common API calls are noise.

The name-weight ablation recovered two development positives but lost another. Register a follow-up with the
same 0.5 weight and unchanged floor: retain baseline neighbors, append at most one allowed alternative from
the name-weighted index, and put the complete baseline batch first for funding. This tests the observed signal
without accepting the observed displacement. It does not change the gold or inspect holdout.

## Corpus audit and follow-up results

### Preserve the evidence, including scope

Captured 31 diagnostic backgrounds for the mined panels, plus the four original-panel/pytest-selective-after
backgrounds, and separate configured-scope snapshots for all 31 mined revisions. Private gold rows now reference
immutable snapshot hashes by scope profile. Public Due, pytest-selective and pytest-obligation goldens
reference nine maintained sparse fixtures, including pytest-obligation's two additional revision captures.
The format retains raw document frequencies, per-function
term counts, source hashes, corpus order, scope, extractor choices, Python version and extraction fingerprint.
It reproduces original TF-IDF weights and raw ranking without relying on today's checkout. See
[capture and replay](benchmark-backgrounds.md); these artifacts are inputs, not benchmark output dumps.

Configured-scope captures show why a repository revision alone is insufficient:

| Before snapshot | Diagnostic functions | Configured-scope functions |
| --- | ---: | ---: |
| backend-common #251 | 3,276 | 1,167 |
| dry-lint #73 | 1,410 | 1,282 |
| Due #180 | 2,336 | 1,257 |
| gigaverse-ai #2997 | 29,405 | 9,743 |
| gigaverse-backend #5358 | 20,092 | 5,112 |
| gigaverse-web-app #4328 | 7,147 | 7,105 |

For AI #2997, `w:mock` has IDF 2.97 in diagnostic scope and 7.55 in configured scope. The same term becomes
rare when most tests disappear. These are different matrices, not interchangeable approximations. The follow-up
therefore repeats candidate selection with each pinned repository's actual include/exclude and filtering
settings, while retaining the experimental estimated $0.04 budget per diagnostic change batch.

### Inspect feature weight before declaring noise

Across those six diagnostic corpora, function-name features contribute 26–32% of average squared vector
weight. High-frequency retained examples include `fn:the` and `fn:and`. These words survive because the
identifier tokenizer's stop list is not an English stop list. Generic API features from the audited set
(`get`, `set`, `append`, `extend`, `items`, `values`, `keys`, `len`, `str`, `int`, `dict`, `list`, `isinstance`,
`cast`, `none`, `true`, `false`) contribute only 0.6–1.6% by the same measure. Singleton vocabulary ranges
from roughly 32% to 47%; rarity alone does not establish usefulness or noise.

Inspection also confirms that a method call can contribute call, attribute and word features. That is existing
intentional behavior, not proof that all three should be removed. Annotation syntax is already excluded.
The audit supports controlled family-weight and naming-glue ablations; it does not justify a broad new stop list.

### Development screen

All rows below use the same 48-positive/128-separate new development panel and diagnostic backgrounds.
Funded means admitted by the unchanged Ledger; it is not a live duplicate verdict.

| Variant | Funded positives | Funded known separate | All funded candidates |
| --- | ---: | ---: | ---: |
| Baseline | 15 | 7 | 88 |
| Protected IDF containment | 15 | 7 | 141 |
| Remove fixed naming-glue words | 15 | 7 | 87 |
| Halve name weight in primary ranking | 16 | 8 | 105 |
| Protected extra name-weighted neighbor | 17 | 8 | 115 |

Containment spends more slots without gaining a fixed-panel positive. Removing glue changes one candidate,
with no known recall gain. Primary name weighting gains two provisional positives but loses another; the
protected variant retains every baseline positive and gains both. Strict-tier positive counts remain unchanged.
This protected variant alone was selected for the reserved four PR families, without further weight tuning.

| Corpus profile | Development funded positives | Development funded known separate | Holdout funded positives | Holdout funded known separate |
| --- | --- | --- | --- | --- |
| Diagnostic, baseline → protected | 15 → 17 / 48 | 7 → 8 / 128 | 7 → 8 / 12 | 3 → 5 / 54 |
| Configured, baseline → protected | 13 → 14 / 48 | 6 → 6 / 128 | 7 → 8 / 12 | 3 → 5 / 54 |

Configured scope contains only 26 eligible development positives; all 12 holdout positives remain eligible.
The configured runs fund 75 → 93 candidates in development and 42 → 53 in holdout. The added fixed-panel
positives are provisional partial operations, not new strict-tier wins. These are still PR-sized diagnostic
batches built from gold query functions, not historical PR diff/cache replays. The holdout is now observed and
must not become a repeatedly tuned source of allegedly independent confirmation.

The original 48-positive/110-separate development regression panel was also replayed against its three pinned
backgrounds. The protected channel retains every baseline positive and raises check recall from 46/48 to 47/48
and scan recall from 41/48 to 43/48. It retrieves 100 rather than 97 known separate pairs in check. The campaign
selection pair is the new check positive; casefold/module resolution is the other added scan positive. These
are retrieval results without a historical PR funding claim; the motivating snapshot pair still misses.

### Live judge and evidence review

Reviewed all newly funded candidates separately from their retrieval scores and then called the unchanged
Sonnet concept judge. Exact repeated requests reuse private evaluation results; none enters the production
verdict store. This is a paired candidate-set comparison, not repeated stochastic judge sampling.

- Exact fragments: seven extras, no report at 0.8. Two pairs receive provisional duplicate agreement from
  source reviewers, but the normal judge calls their shared operation incidental.
- Protected name channel, diagnostic development: 27 extras, one report at 0.8. Both source reviews agree
  that it repeats Due's current-revision possible-provider-entry query, but confidence is only 0.70/0.72.
  The two newly retrieved fixed-panel positives still receive separate verdicts from the normal judge.
- Diagnostic holdout: eight extras, two reports for identical regex escaping across runtime UI and codemod
  code. Reviewers disagree about the value of sharing an owner across that boundary. Keep them disputed,
  rather than crediting them as improvements or silently changing the gold.
- Configured development: 18 extras, the same one provisional agreed report. Configured holdout: 11 extras,
  no reports. The disputed codemod comparisons disappear with the correct scope.

No additional report contradicts consensus separate labels in these configured batches, but one provisional
agreed report is insufficient evidence of preserved production precision. Neither the fixed-panel gains nor
the mined consolidation history should override a disagreement about the useful operation boundary.

**Decision:** keep the name-weighted channel experimental. The audit has produced a measurable retrieval
signal and better reproducibility, but has not established an end-to-end production recall improvement.
The next evaluation should replay actual configured PR changes and caches, retain the old 48-positive regression
panel, and use fresh PR-family holdouts. It should examine the judge's treatment of meaningful partial operations
with controls for boilerplate and already-shared delegation. Do not lower report thresholds or broaden prompts
based only on these cases; earlier prompt trials already showed precision regressions. Learned Markdown or
refactor-derived synonym expansion remains a separate, untested hypothesis.
