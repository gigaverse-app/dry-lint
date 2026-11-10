# Judging defaults

Use **balanced for function duplication** and **agent source review for model ownership**. Adopt this split in CI,
hooks and audits unless the repository documents a concrete cost, credential or measured-quality exception.

| Lane | Default | What a finding means |
| --- | --- | --- |
| Functions | `balanced`: Claude Haiku 5.5, shared-operation prompt, report/fail at 0.5 | A named executable operation has competing implementations; inspect the proposed shared owner |
| Models | Model discovery and optional Jev ranking, followed by agent review | Investigate the complete model family, producers, consumers and ownership; a score never authorizes a merge |

Balanced keeps protected TF-IDF candidates, explores up to 20 neighbours, adds one bounded operation-block neighbour,
and shares a persistent $0.04 budget across a PR's pushes. API judging uses a 2,048-token response limit and no SDK retries.
Deferred or failed judgments are not negative verdicts. Required CI uses `require-complete: 'true'`.
Tests/migrations/scripts remain excluded by default; including them is a repository scope choice, not a reason to
suppress all fixtures. Two wrappers entering the same lifecycle helper are separate; independently implementing
setup/yield/teardown still duplicates behavior.

`auto` selects `balanced` with `ANTHROPIC_API_KEY`, then `balanced-subscription` with `CLAUDE_CODE_OAUTH_TOKEN`,
then `jev` only for existing TypeSafe-only installations, otherwise `none` (detection only). This credential
fallback preserves existing enforcement; it is not the recommended adoption. Pin `preset = "balanced"` in adopting repositories so missing credentials fail visibly. Install
`dry-lint[anthropic]`, or use the Action's `anthropic-api-key` input. The subscription preset shares discovery,
model, prompt and thresholds, but has not been independently calibrated through the CLI.

## One preset everywhere

```toml
[tool.dry-lint]
preset = "balanced"
```

Leave workflow `preset` inputs and hook `--preset` arguments out. Both inherit repository settings. Model review
is enabled separately and does not require the legacy function preset named `agent`.

For an existing baseline, change the repository preset, remove hook overrides, then run:

```bash
dry-lint baseline-migrate --baseline .dry-lint/baseline.json
dry-lint check --baseline .dry-lint/baseline.json --require-complete
```

Migration records the old policy digest and preserves the original pair set, hashes, context, adoption revision
and all debt states, including the last verified revision. It accepts no new debt and credits no cleanup. Commit its small metadata diff with the settings;
review the complete change against the target branch. Never delete/reinitialize the baseline to change a preset.
New findings from broader discovery require review; migration is not an exemption for them.
Excluding a file after adoption does not delete its accepted debt or count as cleanup. The debt remains until
source removal is verified or an in-scope assessment settles it; use explicit reviewed dismissals for intentional copies.

The migration must start from a committed baseline (`HEAD`, or `--baseline-ref <target>`). Repeating it after
adjusting the policy before commit extends its history; it does not reset the original debt. Restore accidental
state/revision edits from that reference before retrying. Run cleanup sweeps after the policy migration lands,
so their evidence and cleanup credit remain separate from the policy change.

Migrated baselines require a release that supports schema 2 in CI and every local hook. Keep an adoption PR
draft until that release reaches `@v1`; refresh cached hook environments as described in the adoption setup.
Unmigrated schema-1 files retain their old wire shape, including when a newer version writes an ordinary sweep.

Legacy Jev and cascade presets remain explicit compatibility choices for existing baselines. Their historical
measurements are in [the benchmark](benchmark.md); they are not current guarantees for the replaced text prompt.
`dry-lint config` prints the resolved setup. Explicit repository overrides still win.

## Who reads the findings: people, or coding agents

Both use balanced for functions. Reserve deeper agent investigation for model ownership and unresolved context.
The old `agent` function preset optimized recall at 43–69% precision. Making it the hook's forced default turned
ordinary pytest adapters into blocking work. Repository owners should document an exception before retaining it.

## AI-926 regression and limits

[gigaverse-ai #3360](https://github.com/gigaverse-app/gigaverse-ai/pull/3360) used Jev `reuse-v2`, `preset=agent`,
without helper context. Its six identical fixture-adapter pairs were false positives. Operation blocks were disabled;
the failure also reproduces before that feature landed. The old prompt only excluded direct delegation between the
pair, while both fixtures actually delegated cleanup to a third owner.

The maintained `dry-operations-v3` prompt distinguishes shared delegation from independently repeated lifecycle
policy. The replaced `concept` and compact prompt names are compatibility aliases, with strict versioned cache
identity. Frozen research artifacts remain historical evidence, not runtime policy.

[Oz's pinned corpus](../examples/oz-fixtures-gold.toml) contains six real adapter pairs and six independent cleanup
pairs. One live Haiku run classified all 12 correctly. Additional curated controls caught 5/6 pytest-obligation
positives with 1/6 false positives, and 5/7 Due positives with 0/3 false positives. These small agent-labelled panels
are regression evidence, not independent population estimates; model output remains variable.

A disappearing finding now means **no longer reported**. Reverts, retrieval changes and changed budgets cannot earn
cleanup credit or supply positive training labels. Only evidenced reductions of accepted baseline debt count toward
cleanup. Legacy sticky/trailer claims are downgraded when read; already published global totals are historical and
are not retroactively recomputed by a local upgrade.

## Paying with a subscription instead of an API key

- **Claude (Pro, Max, Team):** the `claude-code` judge runs `claude -p` with every tool off and a neutral system
  prompt, and removes `ANTHROPIC_API_KEY` from its environment so the subscription, not the API, pays. Locally,
  log the CLI in; in CI, run `claude setup-token` once and store the token as `CLAUDE_CODE_OAUTH_TOKEN`.
- **ChatGPT:** the `codex` judge runs `codex exec` in an empty folder in a read-only sandbox, on the account's
  default model unless `model` is set. Log it in with `codex login`.

Subscriptions are rate-limited as well as billed through their quota, so each run also asks them at most
`budget.subscription_calls` (20) times. A `claude-code` call uses the same model as the API, so it is counted
against `budget.usd` at that model's list price, like an API call. They are slower than the APIs: about 14 s a
pair for `codex` against 2 to 3 s for Sonnet and Opus through the API.

A second judge that fails (an expired login, a reached limit, an outage, a timeout) does not fail the check: its
pairs keep Jev's answer, held to Jev's own 0.8, the report's judging line says which judge failed and why, and
those pairs are asked again on the next run. `bench` refuses to measure instead, so a failure never passes for
Jev's numbers. A failing first judge is still an error.

## Budget and cost

```toml
# .dry-lint.toml ([tool.dry-lint.budget] and [tool.dry-lint.prices] in pyproject.toml)
[budget]
usd = 0.04                 # most judging spends on one pull request, across all its pushes (--budget-usd overrides it)
subscription_calls = 20    # most calls one run makes to subscription judges

[prices]                   # USD per million input and output tokens, over the built-in table
"my-model" = [1.0, 4.0]
```

The budget is for a pull request, not a run: the verdict store keeps what each pull request has spent so far, so a
push that re-judges only its changed pairs spends what is left. A run outside a pull request has the whole budget.
Replaying 184 gigaverse-ai pull requests commit by commit, a pair is judged 1.27 times on average over the life of
its pull request, because a duplicate verdict reopens when its code changes.

Costs are estimated at list price, subscriptions included, from the prompt's length (2.8 characters per token,
measured) and a measured answer length (150 tokens for Sonnet, 220 for Opus), at the prices in `costs.py` (Claude
Sonnet 5.5: $2 and $10 per million; Opus 5.5: $4 and $20; Jev: $0.04 per million input). Measured on gigaverse-ai, a
Sonnet call is about $0.0035 and an Opus call about $0.008. When the budget runs out, the closest look-alikes have
been judged first, and the second judge has taken the first scores nearest the middle of its band first, where the
first judge is least sure. A pair the first judge could not afford stays unjudged (and is asked again by a later
run while the pull request has budget left), and one the second could not afford keeps the first judge's answer,
held to the first judge's own bar. The report says how many. A judge whose price is unknown, such as a custom
command or `codex` on the account's default model, is not budgeted, and its cost shows as unknown, never as zero.

Every sticky comment, clean or not, ends with the judging line and its bill, so `scripts/audit_judging.py OWNER/NAME`
can read what judging really did on recent pull requests: what each spent, how many reached the budget, whether a
judge failed, and how often the check failed or was let through with the override label.

## Every judge

Model declarations have a separate opt-in `jev-models` plugin. It provides ranking and ownership evidence;
every assessed pair remains a coding-agent review task, including low scores. Its measurements and adopter
policy configuration are in [model duplication](model-duplication.md). The function benchmarks above do not
establish model-consolidation accuracy.

| Judge | What it is | Cost |
| --- | --- | --- |
| `auto` (default) | Jev when `TYPESAFE_AI_API_KEY` is set, otherwise `none` | |
| `jev` | TypeSafe's System One decision model, prompt `reuse-v2` | about 0.3 s per pair, 8 pairs in parallel |
| `command` | Any program: the prompt (or the candidate as JSON) on stdin, a JSON verdict on stdout; 4 at once | whatever your model costs |
| `anthropic` | Claude through the official SDK (`dry-lint[anthropic]`) with the same DRY prompt and server-side refusal fallbacks; needs `ANTHROPIC_API_KEY`. Default model `claude-sonnet-5-5`; option `effort` | per pair: Sonnet 2 s and $0.0035, Opus 3 s and $0.008; 4 in parallel |
| `langchain` | Claude through LangChain (`dry-lint[langchain]`), answering in a schema: [structured answers](#structured-answers). Needs `ANTHROPIC_API_KEY`. Default model `claude-haiku-5-5`, `effort = "low"` | per pair with Haiku: 2.3 s and $0.0005; 4 in parallel |
| `gemini` | Gemini over its REST API with the same DRY prompt; needs `GEMINI_API_KEY`, no CLI. Default model `gemini-3.1-pro-preview` | about 12 s per pair, 4 in parallel |
| `claude-code` | Claude through `claude -p` on a Claude subscription; default model `claude-sonnet-5-5` | the model's list price, out of the subscription; rate-limited |
| `codex` | The ChatGPT subscription's model through `codex exec`; `model` optional | no per-call cost; about 14 s per pair |
| `none` | Lists candidate pairs unjudged; never fails the build | free |
| anything installed | A package registering `dry_lint.judges` | |

## Structured answers

The `langchain` judge asks the same question as the `anthropic` judge and gets the answer as a schema,
`DuplicateVerdictPromptSchema`, through LangChain's `with_structured_output`. The provider constrains the output
to the schema, so there is no JSON to find in prose and no answer that fails to parse.

```toml
preset = "balanced-structured"     # balanced's model, prompt, discovery and budget, with this judge
```

or, with your own thresholds, `judge = { use = "langchain", model = "claude-haiku-5-5" }`.

Three things were measured before it shipped ([benchmark](benchmark.md#structured-answers)), and each is a rule
in the code:

- **The reason is the schema's first field.** With the decision first, recall on labelled duplicates fell from
  87% to 48–58%: the model commits before it has compared the functions.
- **The schema is the output format, not a tool.** LangChain's default (a forced tool call) lost 4–8% of answers
  to missing fields. This judge uses `method="json_schema"`, which lost none.
- **Its thresholds are its own.** Its scores sit lower than the text judge's, and its own label lags them, so the
  label is derived from the score and the thresholds, as Jev's is. `balanced-structured` reports and fails at
  0.3, which measured the same as `balanced` at 0.5.

On the same 756 labelled pairs it matched the text judge (86% recall at 8% false reports, against 87% at 8%), at
$0.00049 a pair instead of $0.00062 and 2.3 s instead of 4.1 s. It has not been replayed on pull requests yet,
so `balanced` stays the default and `auto` never picks this preset. It is another judge with another version:
switching re-judges stored pairs once, and a baseline needs `dry-lint baseline-migrate`.

LangChain can trace every prompt, which contains your source, to LangSmith. It does so only when you set its
tracing variables (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`); dry-lint never sets them.

## Jev

`judges/jev.py` sends the two functions as typed state, each with its name, module and code:

```json
{"new_function": {"name": ..., "module": ..., "code": ...}, "existing_function": {...}}
```

It asks three questions:

| Question | Type | Asks |
| --- | --- | --- |
| `same_concept` | noul | One concept that should have a single implementation, parameterized where they differ? |
| `behaves_differently` | noul | Would a caller notice a different result for some input? |
| `owner` | choice | `existing`, `new`, `shared` or `none` |

The `owner` answer is about the pair shown, and it becomes the advice: `existing` says to call the existing
function, `new` to keep the changed function and move the existing one's callers to it, naming both, and `shared`
to extract a helper both call. In a repository-wide `scan` or `sweep` neither function is new (a pair's sides are
only ordered by name), so the advice names the function to keep and the one whose callers move. The judge often
prefers a public function over a private helper. Because functions in the same file are never compared, a
copy placed next to its original pairs with another copy elsewhere, if there is one; the advice can then be to move
that copy's callers to the new function, although the right owner is the original beside it. Read both functions
before following the advice.

Scores are not perfectly repeatable: identical runs can differ by about 0.01, so a pair within a few hundredths
of a threshold can be reported in one run and not the next. The verdict store keeps the first answer for each pair
until either function changes, so a pull request's check does not flip between pushes. Do not tune a threshold to
settle one such pair; decide it on its merits, as debt, a fix, or a recorded decision.

The score is `same_concept × (1 − p(owner = none))`. Jev must think the two are one concept *and* that they should
become one implementation. A pair is
`drifted` when `behaves_differently ≥ drift_at`.

The question wording was tuned against a gold set, and the [benchmark](benchmark.md) numbers belong to that
wording. If you change it, bump `PROMPT_VERSION`; the store then knows the old verdicts came from another prompt.
Then re-measure. Adding call counts and the family of look-alikes to the state did not improve the results, so the
state is only the two functions.

## Any LLM, or any program

```bash
dry-lint check --judge command --judge-command "claude -p --model haiku"
dry-lint check --judge command --judge-command "llm -m gpt-4o-mini"
```

or in the settings, with a `version` so the store knows when its answers change meaning:

```toml
judge = { use = "command", command = "claude -p --model haiku", version = "haiku-dry-1" }
```

By default the command receives the prompt in `judges/command.py`, which uses the same DRY framing as the Jev
questions. With `input = "candidate"` it receives the candidate as one line of JSON instead, the same shape as in
`candidates.json`, for judges written as programs. Either way it must print one JSON object, and any text around
the object is ignored:

```json
{"label": "duplicate", "score": 0.9, "behaves_differently": 0.1, "owner": "existing",
 "why": "both truncate at a word boundary with an ellipsis"}
```

The judge's name is `command:<program>` unless you set `name`. A verdict is only reused by the judge that gave
it, so changing the program means judging again.

[examples/fake_judge.py](../examples/fake_judge.py) is a judge that needs no model, for trying the pipeline.

## A second opinion

`escalate` sends the first judge's scores in a band to a second judge, whose answer replaces the first. The
presets set it; spelled out, `jev+opus` is:

```toml
judge = "jev"
escalate = { use = "anthropic", model = "claude-opus-5-5", between = [0.5, 0.91], first_at = 0.8 }
drop_below = 0.5
report_at = 0.55
fail_at = 0.55
```

With a stronger judge re-judging the band, the thresholds can come down: failing at Opus's 0.55 is more precise
than Jev alone at 0.8 (98% against 94%) and finds more (85% against 73% recall). Sonnet is less precise on the same
pairs (94% at 0.6), so `jev+sonnet` fails at 0.7.
Opus 5.5 is the most precise second judge measured; among five compared on the same band pairs, Sonnet 5.5
changed its mind least between runs and was the fastest; avoid Gemini 2.5 Pro. Claude Haiku 5.5 often scores high while labelling a pair separate, so its scores cannot
place a band. Escalating below 0.5 found nothing more. With an API key set in a developer's
environment, code in the pairs goes to that vendor; set `escalate = "none"`, or `preset = "jev"`, to keep it
local. The stored verdict keeps the first judge's name and records the second in `second_opinion`, so it is reused
like any other.

## Writing a judge

See [plugins.md](plugins.md#judge). Measure it with `dry-lint bench --gold gold.jsonl --judge your-judge`, on the
same gold set as the judge it replaces.
