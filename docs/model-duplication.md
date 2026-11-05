# Detect duplicated model ownership

Use the opt-in model extractors to propose Pydantic/dataclass and TypeScript/Zod declarations for consolidation
review. Retrieval is mechanical and permissive. A judge or coding agent decides whether the overlap represents
one authority and how to preserve independent contracts. No adopter code is imported or executed.

## Try it

Use a separate model-check configuration. A file goes to the first matching extractor, so listing both
`python` and `python-models` does not run both passes. Keep the ordinary function check as a separate invocation.

```toml
# .dry-lint.toml in a checkout used for the model pass
extractors = ["python-models", "typescript-models"]
comparer = { use = "model-shape", min_fields = 2, min_similarity = 0.65 }
neighbours = 3
preset = "none"
```

```bash
dry-lint detect --base origin/main --out /tmp/model-candidates.json
```

The JSON retains field types, full declaration source, bounded same-file context and source digests. Give it
to the coding agent doing the change. Without a judge these are look-alikes, not confirmed findings. Existing
inline decisions, indexes, reports, verdict stores and budget handling are reused.

For the measured optional LLM review, remove `preset = "none"` and add the following settings. Install
`dry-lint[anthropic]` and supply the adopter's own `ANTHROPIC_API_KEY`.

```toml
judge = { use = "anthropic", prompt_policy = "model-contracts", max_tokens = 512 }
escalate = "none"
drop_below = 0.6
report_at = 0.6
fail_at = 0.6
```

Start with `dry-lint check --base origin/main --warn-only`. These are experimental review settings, not a
recommendation to block merges automatically. A prompt-input command judge also accepts `model-contracts`;
JSON-input commands receive the candidate and own their prompt. Jev and other judges remain available, but
their function-judging benchmark numbers do not establish model-judging accuracy.

## Retrieval and supported scope

`model-shape` uses an inverted field index and symmetric Dice overlap:
`2 * shared_fields / (left_fields + right_fields)`. It requires two shared names and score 0.65. Types, defaults
and validation remain review evidence rather than hard filters: their differences may be the drift to find.

- Python recognizes explicit imported Pydantic bases (including Ninja schemas), dataclass decorators, aliases
  and local descendants. Only declared annotations contribute. Local inherited-field overrides, ClassVars,
  InitVars and private fields do not become copied-field evidence.
- TypeScript recognizes top-level interfaces and object aliases; Zod recognizes directly declared object
  literals, aliases and chained refinements. It does not expand `extends`, `Pick`, `Omit`, inferred types or
  schema references into artificial copies. Nested objects remain one field.
- Same-file model pairs are eligible. Ordinary function matching retains its existing same-file policy.
- Hashes retain annotations, defaults, decorators, validators and Zod constraints. Full-file context digests
  invalidate judgment when local usage changes even if declarations do not.

Limitations: custom imported Python bases, dynamic factories and nested declarations are not resolved.
Renamed fields, small subsets of large models, cross-language mappings and fourth-ranked neighbours can be
missed. Cross-file types/consumers are not resolved; same-file context is capped at 8,000 characters per side.
These limits require repository review before acting. Comment-only edits conservatively reopen context caches.

## What the coding agent owns

Find construction/conversion sites, inspect consumers and layers, and name the authority to reuse or promote.
A meaningful shared component can be appropriate without merging whole contracts. State which validation and
serialization behavior stays at each boundary, then test the affected callers.

Independent validation, lifecycle, invariants, security/exposure, versioning and wire promises can justify
separation: public allowlists, provider payloads, immutable events versus mutable state, different units or
identities, discriminated commands and independent test oracles. Request/response is one example, not a blanket
exemption. Different consumers, paths, suffixes and a missing shared module alone do not justify duplication.
Recognize inheritance, composition and derived schemas as existing reuse. A pair judge's dismissal is evidence,
not architectural proof; insufficient context should prompt investigation.

## Measured probe, 2026-11-05

The actual implementation scanned committed source on Windows/Python 3.14. Timings are single full-inventory
runs, including git reads, extraction and candidates. Default exclusions plus test/spec, `__tests__`,
`*.generated.*` and node_modules exclusions were used; other generated files, including `*.gen.ts`, remained.

| Repository / pinned commit | Declarations | Candidate pairs | Seconds |
| --- | ---: | ---: | ---: |
| gigaverse-ai / `292bb323f2c7865ad04d80e81a67de191eac6de1` | 1,851 | 273 | 8.54 |
| gigaverse-backend / `22dfbe180c6704101658a088cc269a25fa9c82dd` | 335 | 27 | 2.02 |
| gigaverse-web-app / `03477c910588f88a0d93e10fc7618bfa3e41efee` | 1,978 | 603 | 2.04 |

Development labels cover 74 initial pairs (30 AI, all 14 backend, 30 web) plus 20 broader challenge pairs.
They are agent source reviews, not human ground truth. Three initial labels were corrected after investigating
context/disagreements; original labels and reasons were retained. Borderlines are excluded from precision/recall.
The 26 positives helped tune retrieval, so this is diagnostic evidence, not population-wide recall.

The retrieval trial indexes all 4,164 declarations and measures directed new-to-existing recall@3. TF-IDF uses
the existing engine with floor 0.7 and max_df 1; the semantic variant adds split field/class-name words.
Candidate counts below are directed edges, not unique pairs.

| Mechanical retrieval | Known positives retrieved / 26 | Directed candidates |
| --- | ---: | ---: |
| Dice, 3 common fields, floor 0.7 | 16 | 602 |
| Dice, 2 common fields, floor 0.7 | 24 | 1,133 |
| Dice, 2 common fields, floor 0.65 (selected) | 26 | 1,607 |
| Field TF-IDF | 23 | 2,139 |
| Name + field TF-IDF | 20 | 978 |
| Union of selected Dice and field TF-IDF, up to 6 neighbours | 26 | 2,694 |

Two-field contracts included dimensions, billing intervals and domain UI state. Lowering the floor recovered
schema variants sharing two of three fields. The union added 1,087 edges without a known positive, so it is not
shipped. This does not show that ensembles cannot help broader or renamed-field cases.

An actual schema-only COMA run using Valentine 1.1.0 matched 24/26 positives and all 44 negatives at aggregate
score 0.7; at 0.9 it matched 19 positives and 15 negatives. These are symmetric aggregates of pairwise column
correspondence, not a full-repository retrieval benchmark. Correspondence does not establish shared ownership.

The first prompt excused copies because of separate renderers, standalone scripts or a missing shared module.
Version 2 recovered 14/16 development positives with 0/39 negative findings at score 0.6. Two borderline
requests remained unanswered after malformed responses. Prompt version and output limit identify cached answers.

A fresh seed-91 sample excluded both declaration files used in development/challenge labels: 20 AI, 2 backend,
20 web. Initial labels were frozen before judging: 9 positive, 25 negative, 8 borderline. The same prompt caught
7/9 positives and flagged 1/25 negatives: 87.5% precision and 77.8% recall on decidable labels. One borderline
request remained unanswered after retry (41/42 completed). Mechanical proposal precision on these initial
labels is 9/34 = 26.5% excluding borderline cases, or 9/42 = 21.4% confirmed positives counting uncertainty as
review work. This sample tests judgment, not retrieval recall outside candidate output. Independent repository
reviews are reported below and supersede those initial labels for architectural conclusions.

### Repository-aware review versus pair judgment

Two coding-agent reviewers independently reviewed all 42 frozen pairs without seeing any labels or judge
answers. They checked pinned declaration source and relevant callers, serializers, validators and consumers.
They agreed on 37/42 labels (88.1%); the five disagreements were adjudicated against those source sites.
The resulting set has 17 actionable consolidations, 23 separate contracts and 2 borderline cases. These are
still model-assisted labels, not independent human ground truth, and agreement does not establish correctness.

| On the same 42 candidates | Result |
| --- | ---: |
| Mechanical proposals with an actionable consolidation | 17/42 (40.5%) |
| Mechanical proposal precision excluding borderline cases | 17/40 (42.5%) |
| Pair judge positive findings accepted by repository review | 11/11 |
| Useful consolidations retained by pair judge | 11/17 (64.7%) |
| Useful consolidations rejected / unanswered by pair judge | 5 / 1 |
| Distinct contracts incorrectly flagged by pair judge | 0/23 |

The distinction is often a **shared component**, not a whole-model merge. Repository review identified a
stream-scope identity shared across distinct tool results, a reusable API-result envelope, a validated proof
component copied across parsing stages, and domain fields preserved through registration and token adapters.
Their outer validation/lifecycle contracts remain independent. Conversely, public exposure rules, hot-path
summaries and distinct DSL discriminators with already-shared validation should stay separate. One initial
false positive became a useful partial extraction after inspecting the shared coverage-field semantics.

This supports keeping the mechanical candidate visible to the coding agent. The atomic judge is useful
prioritization evidence but, in this sample, using its negative answers as a final gate loses 6/17 useful
opportunities. It does not prove a general coding-agent advantage: reviewers had more context, different models
and an explicit component-extraction rubric. No automated refactor or runtime compatibility test was performed
in the consumer repositories.

Each reviewer also found two positive pairs through domain/use-site searches independently of detector output.
All four were extracted and retrieved in the directed top three: two lease-response mirrors, a shared role-badge
contract and a duplicated moderation-tooltip contract. This tiny positive-only audit supports retrieval but
does not measure repository-wide recall or precision.

## Reproduce

```bash
uv run scripts/model_probe.py --repository ai=../gigaverse-ai \
  --repository backend=../gigaverse-backend --repository web=../gigaverse-web-app --out /tmp/models
uv run scripts/model_judge_probe.py --candidates /tmp/models/ai.candidates.json \
  --out /tmp/model-judgments --limit 30 --env-file /secure/adopter.env
uv run scripts/model_retrieval_trial.py --inventory /tmp/models/ai.inventory.json \
  --labels /private/reviewed-labels.json --out /tmp/retrieval.json
# Optional research comparison, not a runtime dependency:
uv run --with valentine==1.1.0 scripts/model_retrieval_trial.py \
  --inventory /tmp/models/ai.inventory.json --labels /private/reviewed-labels.json \
  --out /tmp/retrieval-coma.json --coma
```

Repeat `--inventory` and `--labels` for combined datasets. Label rows contain `new`/`existing` qualified names,
`label` (`duplicate`, `separate`, `borderline`) and `reason`. Outputs contain private source; keep them outside
the checkout. Checkpoints preserve successful answers; missing answers cause a nonzero exit. Receipts record
this run's tokens, time and policy without credentials. Frozen private snapshots and labels are not published
with the library, so reproducing these precise numbers requires access to the reviewed corpus.

## Related work

Existing function similarity uses TF-IDF/cosine over behavior tokens that intentionally discard many type
annotations. Models require a contract-preserving representation. [Valentine](https://github.com/delftdata/valentine)
provides COMA/Cupid and other schema matchers; [Magneto](https://github.com/VIDA-NYU/magneto-matcher) combines small
and large language models for schema matching; [SemStruct](https://arxiv.org/abs/2605.30729) uses semantic and
structural table evidence. [NiCad](https://github.com/CordyJ/Open-NiCad) addresses near-miss code clones.
These adjacent benchmarks do not establish state of the art for architectural model consolidation.
