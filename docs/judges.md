# Judges

## Presets: judges and thresholds, chosen together

A threshold means something only for the judges it was measured with: Jev's 0.8 and Claude Sonnet's 0.7 are not
the same bar. So dry-lint chooses the judges and the thresholds together, as a **preset**:

| Preset | Judges | Fails at | Precision / recall | Per pull request |
| --- | --- | --- | --- | --- |
| `jev+sonnet` | Jev, then Claude Sonnet 5.5 (API) on Jev scores in [0.5, 0.91) | 0.7 (reports from 0.6) | 97% / 84% | ~1.1 Sonnet calls, ~$0.004 |
| `jev+claude-code` | the same, through a Claude subscription (`claude` CLI) | 0.7 (from 0.6) | same model and prompt; not measured through the CLI | ~1.1 subscription calls |
| `jev+codex` | Jev, then the ChatGPT subscription's model (`codex` CLI) on [0.5, 0.91) | 0.7 | 96% / 85% | ~1.1 subscription calls, ~14 s each |
| `sonnet` | Claude Sonnet 5.5 (API) on every pair | 0.7 (from 0.6) | 97% / 84% | ~3.4 calls, ~$0.011 |
| `claude-code` | the same, through a Claude subscription | 0.7 (from 0.6) | same model and prompt | ~3.4 subscription calls |
| `jev` | Jev on every pair | 0.8 | 94% / 73% | ~$0.0001 |
| `none` | no judge: candidates are listed, nothing fails | - | - | free |

Measured on the 250-pair gold set ([benchmark](benchmark.md#thresholds-with-a-second-judge)); on gigaverse-backend,
-web-app and -mobile, `jev+sonnet` failing at 0.7 kept 91–100% precision, while Jev alone fell to about 80% on
TypeScript ([other repositories](benchmark.md#other-repositories)). The default,
`preset = "auto"`, takes the first of `jev+sonnet`, `jev+claude-code`, `jev`, `sonnet`, `claude-code`, `none`
whose credentials are in the environment (`TYPESAFE_AI_API_KEY`, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`);
`jev+codex` must be named, because a `codex` login shows in no environment variable. Any field set explicitly
(`judge`, `escalate`, `drop_below`, `report_at`, `fail_at`, or `--fail-at`) wins over the preset's; naming your
own `judge` without a preset runs it alone, as `custom`, with the default thresholds, since no preset was measured
for it. `dry-lint config` prints what would run and why, and every report ends with the same line: the preset,
the judges, the thresholds and the cost.

## Paying with a subscription instead of an API key

- **Claude (Pro, Max, Team):** the `claude-code` judge runs `claude -p` with every tool off and a neutral system
  prompt, and removes `ANTHROPIC_API_KEY` from its environment so the subscription, not the API, pays. Locally,
  log the CLI in; in CI, run `claude setup-token` once and store the token as `CLAUDE_CODE_OAUTH_TOKEN`.
- **ChatGPT:** the `codex` judge runs `codex exec` in an empty folder in a read-only sandbox, on the account's
  default model unless `model` is set. Log it in with `codex login`.

Subscriptions are rate-limited rather than billed, so each run asks them at most `budget.subscription_calls`
(20) times. They are slower than the APIs: about 14 s a pair for `codex` against 2 s for Sonnet's API.

## Budget and cost

```toml
[tool.dry-lint.budget]
usd = 0.25                 # most one run spends on judges with a per-token price (--budget-usd overrides it)
subscription_calls = 20    # most calls one run makes to subscription judges

[tool.dry-lint.prices]     # USD per million input and output tokens, over the built-in table
"my-model" = [1.0, 4.0]
```

Costs are estimated from the prompt's length (2.8 characters per token, measured) and a measured answer length
(150 tokens), at the prices in `costs.py` (Claude Sonnet 5.5: $2 and $10 per million; Jev: $0.04 per million
input). Measured on gigaverse-ai, a Sonnet call is about $0.003. When the budget runs out, the closest look-alikes
have been judged first and the highest first scores escalated first; a pair the first judge could not afford stays
unjudged (and is asked again next run), and one the second could not afford keeps the first judge's answer. The
report says how many. A judge whose price is unknown, such as a custom command, is not budgeted, and its cost
shows as unknown, never as zero.

## Every judge

| Judge | What it is | Cost |
| --- | --- | --- |
| `auto` (default) | Jev when `TYPESAFE_AI_API_KEY` is set, otherwise `none` | |
| `jev` | TypeSafe's System One decision model, prompt `reuse-v2` | about 0.3 s per pair, 8 pairs in parallel |
| `command` | Any program: the prompt (or the candidate as JSON) on stdin, a JSON verdict on stdout; 4 at once | whatever your model costs |
| `anthropic` | Claude through the official SDK (`dry-lint[anthropic]`) with the same DRY prompt and server-side refusal fallbacks; needs `ANTHROPIC_API_KEY`. Default model `claude-sonnet-5-5`; option `effort` | about 2 s and $0.003 per pair, 4 in parallel |
| `gemini` | Gemini over its REST API with the same DRY prompt; needs `GEMINI_API_KEY`, no CLI. Default model `gemini-3.1-pro-preview` | about 12 s per pair, 4 in parallel |
| `claude-code` | Claude through `claude -p` on a Claude subscription; default model `claude-sonnet-5-5` | no per-call cost; rate-limited |
| `codex` | The ChatGPT subscription's model through `codex exec`; `model` optional | no per-call cost; about 14 s per pair |
| `none` | Lists candidate pairs unjudged; never fails the build | free |
| anything installed | A package registering `dry_lint.judges` | |

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
presets set it; spelled out, `jev+sonnet` is:

```toml
judge = "jev"
escalate = { use = "anthropic", model = "claude-sonnet-5-5", between = [0.5, 0.91] }
drop_below = 0.5
report_at = 0.6
fail_at = 0.7
```

With Sonnet re-judging the band, the thresholds can come down: Sonnet's scores are more decisive than Jev's, so
failing at 0.7 is more precise than Jev alone at 0.8 (97% against 94%) and finds more (84% against 73% recall).
Among five second judges compared on the same pairs, Sonnet 5.5 changed its mind least between runs and was the
fastest; avoid Gemini 2.5 Pro. Escalating below 0.5 found nothing more. With an API key set in a developer's
environment, code in the pairs goes to that vendor; set `escalate = "none"`, or `preset = "jev"`, to keep it
local. The stored verdict keeps the first judge's name and records the second in `second_opinion`, so it is reused
like any other.

## Writing a judge

See [plugins.md](plugins.md#judge). Measure it with `dry-lint bench --gold gold.jsonl --judge your-judge`, on the
same gold set as the judge it replaces.
