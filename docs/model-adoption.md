# Default model review and adoption

Model review runs alongside function checks in the action and staged hook, with an explicit opt-out.
Adopters may declare model ownership policies; dry-lint must not infer a repository's architectural boundaries
from generic request/response names. Atomic scores prioritize review and cannot authorize consolidation.

The adoption ratchet records exact, source-reviewed duplicate pairs. Existing allowances cannot grow,
survive changed evidence, or reopen after cleanup. Intentional boundaries belong in documented policies or
pair-specific reviewed dismissals, not in duplicate debt.

## Controls

The action defaults to `models: true`. Set that input to `false` to skip the model pass. Its
`models-checked` output confirms that the pass completed, including when no models changed. The hook and
CLI accept `--no-models`. Repository configuration can control each entry point independently:

```toml
[models] # [tool.dry-lint.models] in pyproject.toml
enabled = true
sticky = true
hook = true
baseline = ".dry-lint/models.json" # optional, after initialization
```

`sticky = false` disables the action's model pass; `hook = false` disables the automatic staged pass.
An explicit CLI `--models` overrides the repository opt-out. Function-only peer indexes remain function-only;
model comparison includes the local repository and any explicitly checked-out peers.

Models use the existing Python/TypeScript model extractors and model-shape comparer. With the adopter's
TypeSafe key, `jev-models` prioritizes their review. With another function judge but no TypeSafe key, model
candidates go directly to source review without a provider call. With judging disabled, candidates are listed
without blocking. Model ranking has a $0.01 ceiling against the existing shared PR spend ledger; function
judging retains its own configured ceiling. Exhausting ranking budget never dismisses a model candidate.

## Adopter policies

Policies are opt-in. dry-lint has no built-in prompt, public API, filename or class-name exemptions.
Use `models.policies` for model-only rules; existing top-level `policies` still apply to both passes.

```toml
[[models.policies]]
name = "prompt-schema-isolation"
reason = "Prompt schema families evolve independently of application models."
action = "discard"
left = { reachable_from = ["*PromptSchema"], role = "private prompt schema family" }
right = { not_reachable_from = ["*PromptSchema"], role = "application contract" }

[[models.policies]]
name = "public-api-review"
reason = "Check published compatibility before proposing a shared component."
action = "review"
priority = -5
left = { paths = ["src/public_api/*"], role = "public contract" }
right = { paths = ["src/domain/*"], role = "product contract" }
```

Selectors combine path and qualified class-name globs and match in either orientation. Reasons and matched
rules accompany the candidate. Changing a matched rule invalidates its reviewed evidence and cached ranking.
Prefer `review` when a directory contains mixed ownership; `discard` is an explicit decision to suppress
matching pairs, including future ones. See [model discovery](model-duplication.md) for selector details.

Python model selectors also support `reachable_from` and `not_reachable_from`: globs over file-local roots
that reach the declaration through annotations or bases, including itself. They follow nested classes,
quoted references and ordinary type aliases. Imported types are not reclassified; a prompt referencing an
application type is an ownership violation, not an exemption for the application model. These are static
adapter facts, not a runtime schema expansion. TypeScript selectors currently support paths and names only.

### Optional schema ownership checks

Some adopters require LLM schemas to be private to their prompt/call file. The root plus its transitive
nested structured types and bases is its **prompt schema family**. Only the root needs the identifying suffix.
Application code consumes a converted, validated **application model**. This is a repository policy, not a
universal rule for every dry-lint adopter. Configure the actual LLM APIs before enabling the check:

```toml
[models.schema_policy]
root_suffix = "PromptSchema"
include = ["src/*"]
methods = ["with_structured_output"]
functions = [{name = "myapp.llm.structured", position = 1, keyword = "response_model"}]
chain_bases = ["myapp.llm.StructuredChain"]
```

Run `dry-lint schema-check --base origin/main` in CI, or add the opt-in `dry-lint-schema-policy` pre-commit
hook. `schema-check --staged` reads indexed source and configuration. `--all` audits existing violations.
The command reports root naming, cross-file imports/references, and application models embedding prompt
types. It returns 1 for findings, independently of judge credentials; configuration errors return 2.
Ordinary HTTP response models are not LLM sinks. Methods are an explicit adopter assertion; prefer qualified
functions or chain bases where names are ambiguous. Scalar/string output is not a structured model.

Existing issues reopen when their file changes; newly introduced dependencies also reopen unchanged
consumers. Unresolved dynamic roots require source review. Static checks do not follow arbitrary re-exports,
generated schemas or instance dataflow, and cannot prove the absence of prompt objects in application state.
Coding agents must verify the full runtime boundary. Renaming a mixed-use model does not repair isolation.

## Establish and maintain reviewed debt

1. Export the current inventory with `dry-lint detect --all --out candidates.json`, then render review evidence
   with `dry-lint judge --candidates candidates.json --judge none --report report.json`. Keep these execution
   artifacts outside the source PR.
2. Read declarations, nested types, construction sites and consumers. For each actionable existing model pair,
   run `dry-lint feedback accept PAIR --from report.json --reason "shared owner and proposed consolidation" --reviewer NAME`.
   For an intentional boundary, use `feedback dismiss` with its concrete reason or an adopter policy.
   Acceptance requires unchanged staged source; it does not suppress a new duplicate by itself.
3. Run `dry-lint model-baseline --init` against committed source. Commit `.dry-lint/models.json` and the reviewed
   `.dry-lint-feedback.json` decisions, then set `models.baseline` as above. Only accepted source-bound pairs
   enter the baseline. Unreviewed pairs remain unknown, not accepted debt or confirmed duplication.
4. After consolidation, stage the repair, run `dry-lint model-baseline --update --staged`, then stage the updated
   baseline. Checks require resolved allowances to be retired before the repair can land, preventing later
   reintroduction. Without `--staged`, the command audits committed source. A removed declaration can retire debt; an exact reviewed dismissal
   is counted separately. A renamed copy with unresolved neighbours does not earn cleanup credit.

Checks validate the proposed baseline against the target ref (HEAD for the hook). They cannot change the
original pair set, replace hashes, or reopen cleaned/dismissed debt. Source edits invalidate allowances.
Atomic model scores never initialize debt, clear it, or authorize a new allowance. The baseline is a bounded
inventory of reviewed opportunities, not a claim that all possible duplication has been found.

## Verification plan

- Exercise default model detection, independent opt-outs, and combined function/model reports in real temporary repositories.
- Preserve model candidates across the split detect/judge action and show them in the sticky report.
- Prove unchanged debt is allowed, changed/new duplicates block, and removed allowances cannot be reused.
- Prove policy changes invalidate evidence and atomic negatives cannot create or clear accepted debt.
- Run the revised workflow on gigaverse-ai and gigaverse-backend, reviewing actual ownership and consumers
  before recording their initial model debt.
