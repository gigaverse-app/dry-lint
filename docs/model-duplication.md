# Detect duplicated model ownership

The action and staged hook now include a model pass by default; see [adoption and opt-outs](model-adoption.md).
The standalone model extractors also propose Pydantic/dataclass and TypeScript/Zod declarations for consolidation
review. Retrieval is mechanical and permissive. A judge or coding agent decides whether the overlap represents
one authority and how to preserve independent contracts. No adopter code is imported or executed.

## Try it

Use a separate model-check configuration. A file goes to the first matching extractor, so listing both
`python` and `python-models` does not run both passes. Keep the ordinary function check as a separate invocation.

```toml
# .dry-lint/config.toml in a checkout used for the model pass
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

Keep the baseline and optionally add bounded discovery routes:

```toml
[discovery]
enabled = true
comparers = [
  { use = "tfidf", min_similarity = 0.7, min_similarity_small = 0.7, max_df = 1.0, neighbours = 3 },
  { use = "model-shape", min_similarity = 0.35, min_fields = 2, neighbours = 10 },
]
```

Use `[tool.dry-lint.discovery]` when configuring through `pyproject.toml`. Exploration is opt-in and preserves
the baseline's pairs and protected budget. Run scheduled checks with `--session model-review`; see
[protected exploration](protected-exploration.md) for cumulative budgets, revision identity and persistence.
Every route records its own similarity; no learned ranker or score averaging is involved.

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
- Opt-in `luau-models` recognizes top-level Luau record aliases and named Lua table literals through tree-sitter.
  It collects explicit data fields, preserving types and defaults for review, without expanding inheritance,
  factories or referenced types. See [Luau model shapes](luau.md#record-and-table-model-shapes).
- Hashes retain annotations, defaults, decorators, validators and Zod constraints. Full-file context digests
  invalidate judgment when local usage changes even if declarations do not.

Limitations: custom imported Python bases, dynamic factories and nested declarations are not resolved.
Renamed fields, small subsets of large models, cross-language mappings and fourth-ranked neighbours can be
missed. Cross-file types/consumers are not resolved; same-file context is capped at 8,000 characters per side.
These limits require repository review before acting. Comment-only edits conservatively reopen context caches.

## Adopter policies

An adopting repository can supply pair rules by filename, class name and, for workspace sources, repository.
For example, after verifying this project's actual schema owners:

```toml
[[policies]]
name = "prompt-domain-independence"
left = { paths = ["src/prompts/*"], names = ["*PromptSchema"], role = "structured LLM answer" }
right = { paths = ["src/domain/*"], role = "conformed application model" }
reason = "Prompt schemas evolve independently to improve LLM results."
action = "review"
priority = -5

[[policies]]
name = "published-api-compatibility"
left = { paths = ["src/public_api/*"], role = "published Developer API contract" }
right = { paths = ["src/product/*"], role = "internal Product contract" }
reason = "The published API has a longer compatibility lifetime than coordinated Product releases."
action = "discard"
```

Use `[[tool.dry-lint.policies]]` in `pyproject.toml`. These paths and rules are illustrative; dry-lint ships no
Gigaverse-specific exemption. In particular, a directory named `developer_api` may contain private capability
contracts rather than the actual public facade. Match the authoritative owners in the adopting repository.

Matching is symmetric. Within one selector, every dimension must match; patterns within a dimension are ORed.
Patterns are case-sensitive `fnmatch` over repository-relative forward-slash paths, symbol names (`Class` or
`Owner.method`) and `owner/repository` origin. `*` can cross path separators. Omitted dimensions match everything;
repository selectors require workspace origin metadata. Both sides must match, so a public/private rule does
not discard two public models. Ambiguous selectors retain both possible role claims.

`review` attaches guidance and keeps the candidate. Higher `priority` values receive earlier review slots;
multiple matched priorities add. Protected baseline slots still precede exploration. `discard` is an explicit
adopter decision: the pair stays in candidate/report JSON with its rule and reason but consumes no judge calls.
Any matching discard wins. Existing skip reasons take precedence in the display; all matched policies remain
in JSON. Policy edits reopen cached judgments and source-bound dismissals. Configured roles are claims for the
coding agent to verify, not automatic runtime type resolution.

## Optional Jev triage

Replace the judge settings with the following to use the adopter's `TYPESAFE_AI_API_KEY`:

```toml
judge = { use = "jev-models", model = "jev-1.14.0", context = false }
escalate = "none"
```

These are top-level settings in `.dry-lint/config.toml`, before any table headers. The plugin records separate scores
for shared authority, policy-required separation, established roles, same-owner specialization, existing reuse
and missing context. `shared_authority` ranks the review queue; it is never multiplied by a boundary score to
manufacture a final decision. Every assessed pair remains a coding-agent review task, even at a low score.
Strict checks require those tasks to be resolved; use `--warn-only` while adopting. Explicit discard policies
and source-bound agent feedback can settle pairs without an LLM call.

`context = true` adds bounded same-file context. It does not resolve imported types, trace consumers or verify
declared roles. The agent should inspect those sources selectively and record a justified decision using the
existing feedback workflow. A manually configured escalation judge can replace the first verdict, so keep
escalation disabled for this triage workflow. Function presets and automatic judge selection are unchanged.

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

## Measured probes, 2026-11-05

These are agent source reviews of private pinned repositories, not human ground truth or a measurement of
repository-wide recall. Borderline cases remain review work. Raw source, labels and provider responses are
kept outside the code PR.

| Repository / pinned commit | Declarations | Baseline pairs | Additional TF-IDF | Additional wider Dice |
| --- | ---: | ---: | ---: | ---: |
| gigaverse-ai / `292bb323f2c7865ad04d80e81a67de191eac6de1` | 1,851 | 273 | 174 | 1,087 |
| gigaverse-backend / `22dfbe180c6704101658a088cc269a25fa9c82dd` | 335 | 27 | 24 | 62 |
| gigaverse-web-app / `03477c910588f88a0d93e10fc7618bfa3e41efee` | 1,978 | 603 | 506 | 1,521 |

The production detector preserves all 903 baseline pairs and produces 4,277 unique pairs with the exploration
configuration above. TF-IDF owns a pair before wider Dice when both retrieve it. Wider Dice includes both
lower overlap and deeper neighbours. Full scans took 8.20 / 2.01 / 2.94 seconds on Windows/Python 3.14, individual
observations rather than a performance benchmark. Default exclusions plus test/spec, `__tests__`,
`*.generated.*` and node_modules exclusions were used; other generated files, including `*.gen.ts`, remained.

### Corrections to the original probe

The original positive pool was revised from 26 to 24 after the repository owner clarified two independent
schema boundaries: structured LLM answer versus conformed model, and private Product capability versus stable
public Developer API contract. The original 42-pair holdout is now 17 duplicate, 24 separate and one borderline.
The original atomic model-contracts judge retained 11/17 useful consolidations, rejected five and left one
unanswered; it flagged 0/24 separate cases. These corrected labels supersede the initial field-only judgments.

Concrete misses included `TranslationApiResult` / `WidgetApiResult`, which share an API receipt and decoding
flow, and `CommunityStreamResult` specializations, whose result-producing tools share stream identity. Their
consumers establish useful partial reuse even though the outer results differ. Prompt schemas remain separate.
`EventParticipantPage` / `CursorPage` is a same-public-owner pagination specialization; the private/public
compatibility rule does not exempt duplication inside that one public contract.

A follow-up 48-pair diagnostic sample contained 13 useful consolidations, 30 separate cases and five borderline
cases. Of 24 TF-IDF-only pairs, six were useful, representing three families: participant targets, invitation
payloads and authentication schemas. Of 24 wider/lower-Dice pairs, seven were useful. Thus the earlier claim
that TF-IDF added no useful candidates was specific to a small positive pool and did not generalize.
The six TF-IDF positives were all excluded by the default two-common-field minimum. Allowing one common field
also recovered them, but increased the baseline union to 2,214 pairs versus 1,607 for baseline plus TF-IDF.

On that diagnostic sample, sorting by Dice put 3 useful pairs from 2 families in the first 8 and 6 from 3 families
in the first 16. The exploratory declaration-only Jev questions put 8 useful pairs from 7 families in the first
8 and 12 from 9 families in the first 16. Adding indiscriminate local context reduced those counts to 6/11;
consumer excerpts gave 6/11 as well. This supports cheap triage followed by targeted source investigation;
it does not show that more context is generally harmful or that these scores are calibrated probabilities.
Those exploratory questions differ from the generic production plugin; its fresh evaluation is reported below.

### Consolidation experiment

An isolated consumer prototype extracted a shared generic CLI API receipt/decoder and shared stream-result
identity. It passed 41 focused tests. A rescan reduced model pairs from 273 to 268. The 38 functions in the two
CLI modules still produced 68 pairs; no new function pair crossed the detector threshold. Existing render
similarity stayed 0.876 and send similarity changed from 0.676 to 0.672. Consolidation made the remaining shared
workflow easier to inspect, but this experiment did not demonstrate a newly uncovered function duplicate.
The consumer patch was not shipped, and live LLM/service compatibility was not tested.

### Fresh production-plugin evaluation

Two independent source reviewers, blinded to scores and each other's labels, reviewed 54 new pairs: six from
each repository in each of baseline, TF-IDF-only and wider-Dice-only strata. Previously reviewed keys were
excluded; one recognized case was replaced before judging. They agreed on 49/54 labels. Source adjudication
of the five disagreements produced 11 useful consolidations, 42 separate cases and one borderline case.
The strata yielded 6/18, 1/18 and 4/18 useful pairs respectively. These are stratified sample yields, not
population precision. Five of the eleven useful cases require exploration beyond the unchanged baseline.

The actual `jev-models` plugin (`model-ownership-v1`, `jev-1.14.0`) made 114 live requests: those 54 pairs plus
three ownership controls, with declarations only and with same-file context. No questions were tuned against
these answers. Sorting uses raw shared-authority score, with stable pair-key ties; borderline cases consume a
review slot but do not count as useful. Families group positive edges sharing a declaration.

| Ranking on the same 54 pairs, higher is better | Useful in first 8 / families | Useful in first 16 / families | Average precision |
| --- | ---: | ---: | ---: |
| Mechanical Dice | 1 / 1 | 1 / 1 | 0.222 |
| Mechanical field TF-IDF | 1 / 1 | 1 / 1 | 0.210 |
| Jev declarations | 6 / 6 | 9 / 8 | 0.758 |
| Jev with same-file context | 4 / 4 | 8 / 8 | 0.618 |

Declaration requests used 74,567 input tokens; local-context requests used 139,542. At the configured input
price, the 57 requests in each arm cost $0.002983 and $0.005582 respectively. These are provider-reported token
usage multiplied by the configured price, not reconciled invoices. A hypothetical 0.6 declaration-score gate
would retain 8/11 useful cases and flag 3/42 separate cases plus the borderline case. This is why the plugin
keeps low-scoring candidates available for agent review.

The three useful cases below that hypothetical gate show what the coding agent adds:

| Pair | Jev score | Evidence that changes the decision |
| --- | ---: | --- |
| `CompactMetricParityCheck` / `ProviderProbeCheck` | 0.45 | Sibling Locust diagnostics emit the same frozen named check result. Provider `required` flags specialize the check; keep its required-only aggregation separate. |
| `ActorOutcome` / `ActorRecycleOutcome` | 0.56 | Both producers populate identity from the same pool actor. Share identity/diagnostics while preserving provisioning versus recycling statuses and extra fields. |
| Pre-room `searchSchema` / `NavigateToRoomCreationOptions` | 0.55 | The navigation helper builds exactly the route's search parameters, hiding some in an untyped dictionary. Promote one search contract and infer the navigation portion; preserve title masking and mode normalization. |

Ownership controls also expose the limits of atomic questions. Private/public community summaries received
shared-authority scores 0.23/0.25; prompt/conformed chapter models received 0.29/0.30. However, the chapter
boundary fact itself scored only 0.32/0.45 despite the supplied policy. Same-public-owner pagination scored
only 0.51/0.52 on shared authority but 0.88/0.87 on specialization. Do not use a single atomic threshold to
authorize either consolidation or dismissal. Explicit, correctly scoped adopter discard rules are deterministic.
An additional production-detector scan of all 1,534 AI pairs applied exact path/class discard rules to the two
reviewed cross-owner controls: both were filtered, while same-public-owner pagination remained eligible.

Source investigation changed decisions concretely: scheduled invitations and live role changes repeat the
same label normalization despite different identity selectors; rendition maintenance reports repeat execution
provenance under an existing shared evidence module; LiveKit publication summaries copy canonical SDK fields
and a caller projects them field-for-field. These support partial reuse while preserving endpoint validation,
report completion semantics and recording lifecycle. In contrast, actual image dimensions versus target
dimensions, mutually exclusive image-source modes and role definitions versus assignments remain separate.

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
