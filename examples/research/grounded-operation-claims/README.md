# Grounding repairs some explanations but leaves report-quality problems

The recovery experiment exposed a report-selection problem: a pair of functions can
contain useful shared implementation, but the judge may recommend only a small guard
or a call to an existing helper. This study tests whether an explicit grounding
instruction makes the judge select and explain the independently duplicated operation.

`policy.py` is the exact tested intervention. It appends instructions to the existing
shared-operations prompt: inspect both complete functions, discount existing shared
owners and generic mechanics, identify the remaining contract, cite exact anchors in
both functions, and state caller differences. It changes no source snippets, signature,
documentation, output schema, model, or reporting threshold. The main implementation
continues to use its existing policy; this experiment adds no registered product preset.

Both arms use `claude-haiku-5-5`, a 2,048-token output cap and report threshold 0.50.
The original answers are exact archived observations; treatment answers are new paid
observations. The comparison is paired by exact source and settings, but the answers
were not generated contemporaneously and model nondeterminism is not controlled.
This is a diagnostic of report quality after retrieval, not a matched-budget campaign
replay or an estimate of population precision/recall.

The frozen plan contained 35 questions: 28 development cases and seven previously
source-reviewed T3/OpenHands controls with separate families. Four local validation
failures occurred before a provider client was constructed and were not retried.
Of the 31 actual provider attempts, 27 returned valid answers and four exhausted the
output cap. Failed outputs and their costs remain in the evidence; they are not
negative judgments. All seven controls received valid answers. Fresh token-accounted
spend was **$0.0468082**, below the $0.20 diagnostic ceiling.

| Comparable valid answers | Baseline reports | Grounded reports | Changed reporting decisions |
| --- | ---: | ---: | --- |
| Development, 20 pairs | 15/20 | 15/20 | One suppressed, one added |
| Source-family controls, seven pairs | 5/7 | 5/7 | None |
| Total, 27 pairs | 20/27 | 20/27 | One suppressed, one added |

A report count is not a useful-duplicate count. An independent reviewer assessed 54
shuffled explanations against full source and prior operation context, without arm
names, model identities or scores. The audit found the following results among the 27 comparable pairs:

| Actual explanation quality | Baseline | Grounded |
| --- | ---: | ---: |
| Strictly useful reported claims, development | 3/20 pairs | 4/20 pairs |
| Strictly useful reported claims, controls | 2/7 pairs | 3/7 pairs |
| Strictly useful among all emitted reports | 5/20 reports | 7/20 reports |
| Nonuseful reported claims | 6 | 6 |
| Disputed reported claims | 7 | 7 |
| Mixed useful and unsupported claims | 2 | 0 |

Three explanations gained strict useful credit and one lost it. Two gains repaired
unsupported assertions about otherwise useful attachment-upload and recording-start
operations. A third identified a previously unmentioned LiteLLM authorization rule:
non-admin users may not transition a key into enabled budget throttling. That is new
claim-level evidence on an existing pair, not a newly discovered pair or a count of
additional independent families.

The regression narrowed a shared analysis-finalization operation to writing a bundle
and raising on warnings, but omitted intervening printing. Encapsulating the proposed
steps in one helper could raise before the caller prints. Exact anchors made the
claim easier to audit without guaranteeing a safe abstraction.

The only newly emitted report covered a JSON decode/error wrapper and was nonuseful;
the suppressed report was also nonuseful. Thus unchanged report counts conceal both
explanation repairs and a regression. This does not demonstrate added retrieval recall.

**Decision: keep the policy experimental.** Grounding improved the strict assessment
of two reports net, but six nonuseful and seven disputed reports remain, and four paid
answers failed at the output limit. Do not substitute this diagnostic for a full native
campaign comparison or promote the residual scheduling draft on these numbers.

Several short budget checks are source-grounded but utility-disputed against earlier
pair-level tiny labels. Those old judgments remain unchanged. A separate concrete
family-level extraction proof is testing whether repeated small rules across multiple
owners justify one helper; its result must not be backfilled into this frozen audit.

The private fixture includes complete Candidates, exact rendered prompts, settings,
model/version/output options, original baseline and treatment answers, source proofs,
and split membership. It does not require full TF-IDF matrices because it starts after
candidate selection. The parent retrieval experiments retain the separately pinned
backgrounds; this study makes no new retrieval or corpus-wide coverage claim.

## Reproduce without a provider

The complete mixed-source fixture is private and requires authorized access to
[gigaverse-app/dry-lint-goldens](https://github.com/gigaverse-app/dry-lint-goldens).
It was merged in [corpus PR #9](https://github.com/gigaverse-app/dry-lint-goldens/pull/9)
at `169045b10c8a69b69bc1eb6ffbfc19f1869c6e45`. No access token is supplied by dry-lint.
With an authorized local checkout:

```bash
GOLDENS=/path/to/dry-lint-goldens
FIXTURE=/path/to/new/grounded-operation-claims-v1
git -C "$GOLDENS" checkout --detach 169045b10c8a69b69bc1eb6ffbfc19f1869c6e45
python3 "$GOLDENS/corpus.py" materialize grounded-operation-claims-v1 --out "$FIXTURE"
python3 -I examples/research/grounded-operation-claims/reproduce.py --root "$FIXTURE"
```

This uses Python's standard library, makes no network calls, and executes no target
source. It verifies manifest hashes, reconstructs both exact prompts from frozen
constants, checks source/Candidate/model identities, reparses recorded JSON answers,
recomputes token-accounted spend and reporting decisions, and joins every opaque
explanation to the frozen independent assessment. It reproduces the tables above.
It does not independently regenerate subjective source judgments or rerun retrieval.

Both public Python files are formatted copies; the original byte-exact policy,
canonical SDK parser/runtime at `2aab042c256141383c7c731b7ba6097dd2db53b3`, requests,
answers, failed outputs, root execution provenance and source snapshots remain in
the fixture. The standalone replayer checks the recorded subset with a standard-library
parser, which was compared against the production parser in the original diagnostic.
Its formatted copy was independently rerun against the freshly materialized fixture.
Full baseline/treatment functions retain signatures and documentation. No old-policy
answer is reused as a treatment answer.

A live rerun is a separate paid experiment: use the recorded full Candidate and
policy/model/output settings with an adopter-supplied credential and a fresh ledger.
The provenance executors in the private fixture preserve the original lab invocation;
they are not a portable live CLI and must not be run as part of this offline command.
This study intentionally publishes no credential-discovery or provider-execution path.
