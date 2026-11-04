# Judges

## Presets: judges and thresholds, chosen together

A threshold means something only for the judges it was measured with: Jev's 0.8 and Claude Sonnet's 0.7 are not
the same bar. So dry-lint chooses the judges and the thresholds together, as a **preset**:

| Preset | Judges | Reports and fails at | Precision / recall within $0.04 a PR | Average cost a PR |
| --- | --- | --- | --- | --- |
| `jev+opus` | Jev, then Claude Opus 5.5 (API) on Jev scores in [0.5, 0.91) | 0.55 | 98% / 85% (99% / 90% unbudgeted) | ~$0.005 |
| `jev+claude-code` | the same, through a Claude subscription (`claude` CLI) | 0.55 | same model and prompt; not measured through the CLI | ~$0.005 of subscription use |
| `jev+sonnet` | Jev, then Claude Sonnet 5.5 (API) on [0.5, 0.91) | 0.7 (reports from 0.6) | 97% / 84% | ~$0.0035 |
| `jev+claude-code-sonnet` | the same, through a Claude subscription | 0.7 (from 0.6) | same model and prompt | ~$0.0035 of subscription use |
| `jev+codex` | Jev, then the ChatGPT subscription's model (`codex` CLI) on [0.5, 0.91) | 0.7 | 96% / 85% | ~1.1 subscription calls, ~14 s each |
| `sonnet` | Claude Sonnet 5.5 (API) on every pair | 0.7 (from 0.6) | 97% / 63% (84% unbudgeted) | ~$0.007 |
| `claude-code` | the same, through a Claude subscription | 0.7 (from 0.6) | same model and prompt | ~$0.007 of subscription use |
| `jev` | Jev on every pair | 0.8 | 94% / 73% | ~$0.0002 |
| `none` | no judge: candidates are listed, nothing fails | - | - | free |

Measured on the 250-pair gold set and simulated on each pull request's own candidates under the default budget,
every push included ([benchmark](benchmark.md#within-a-budget)). On gigaverse-backend, -web-app and -mobile,
`jev+sonnet` failing at 0.7 kept 91–100% precision, while Jev alone fell to about 80% on TypeScript
([other repositories](benchmark.md#other-repositories)). There, within the budget, `jev+opus` and `jev+sonnet`
tie, and TypeScript precision falls to 83–89% with either, so keep `warn-only` on TypeScript
([`jev+opus` elsewhere](benchmark.md#jevopus-and-the-budget-elsewhere)). The default,
`preset = "auto"`, takes the first of `jev+opus`, `jev+claude-code`, `jev`, `sonnet`, `claude-code`, `none` whose
credentials are in the environment (`TYPESAFE_AI_API_KEY`, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`); the
others must be named. On gigaverse-ai, `jev+sonnet` costs a third less than `jev+opus` but blocks about twice as many separate pairs.
`sonnet` and `claude-code` have no cheap first judge to fall back on, so on the largest pull requests the budget
runs out and pairs stay unjudged: that is why `jev` comes before them. Any field set explicitly (`judge`,
`escalate`, `drop_below`, `report_at`, `fail_at`, or `--fail-at`) wins over the preset's; naming your own `judge`
without a preset runs it alone, as `custom`, with the default thresholds, since no preset was measured for it.
`dry-lint config` prints what would run and why, and every report ends with the same line: the preset, the judges,
the thresholds and the cost.

Each threshold belongs to the judge whose scores it was measured on. With a second judge, its answers meet the
preset's thresholds, and the first judge's answers that it did not see (outside the band, or once the budget has
run out) meet the first judge's own bar, `escalate.first_at`: 0.8 for Jev. Without that, a large pull request that
ran out of budget would fail on Jev scores of 0.55, where Jev alone is right about two times in three.

## Who reads the findings: people, or coding agents

Choose the judging for whoever reads the findings, not for the best score on a benchmark.

- **A person** reading a pull request comment pays for each false positive with attention, and a red check holds up a
  merge. Every wrong finding also teaches them to skim the next one. Put precision first: an escalating preset such
  as `jev+opus` (98% precision), and a `fail_at` that blocks only what is nearly certain.
- **A coding agent** pays seconds. It opens both functions, decides, and either reuses the existing one or records
  why they differ (`# dry-lint: distinct-from ...`), which settles the pair for good. A missed duplicate costs a copy
  that drifts. Put recall first, with a fast, cheap judge and a low threshold: the agent is the second judge, so
  paying Claude Opus to judge a finding that an agent will check anyway buys little.

**High enough** is a range, not a maximum, for both:

| Reader | Recall | Precision | Judging |
| --- | --- | --- | --- |
| Person: PR comment, required check | as high as precision allows | about 95% or more of what blocks; reports may warn below it | `jev+opus` or `jev+sonnet` |
| Coding agent: hook, agent loop, `--format json` | about 90% or more | about one in two or better: below that, agents start ignoring findings as people do | Jev, or another cheap judge, at a low threshold |

The measurements support the split. Jev alone, at 0.6, keeps 95% recall at 70% precision on gigaverse-ai
([benchmark](benchmark.md#results)), for about $0.0002 a pull request against about $0.005 for `jev+opus`. On the
gigaverse-backend, -web-app and -mobile gold sets, it keeps 90% to 100% recall at 0.6, with about one finding in two
real. That is plenty for an agent to check, and too noisy to block a person's merge.

One repository can serve both readers. CI keeps a precision preset for the comment and the check. A coding agent runs
`dry-lint check --staged --preset jev --format json`: the JSON lists every judged pair with its score, not only
the ones the preset reports, so it can review everything from 0.6 up. A local run keeps its verdicts in the git
directory and CI keeps its own in the Actions cache. Even in one store, a verdict is reused only by judging that
would have given it: a second opinion only for the same second judge, and Jev's own answer in the escalation band
never for a run that escalates. So a `jev` run and a `jev+opus` run can share a store, and adding a second judge
re-judges the cached first answers it would have seen.

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
[tool.dry-lint.budget]
usd = 0.04                 # most judging spends on one pull request, across all its pushes (--budget-usd overrides it)
subscription_calls = 20    # most calls one run makes to subscription judges

[tool.dry-lint.prices]     # USD per million input and output tokens, over the built-in table
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

| Judge | What it is | Cost |
| --- | --- | --- |
| `auto` (default) | Jev when `TYPESAFE_AI_API_KEY` is set, otherwise `none` | |
| `jev` | TypeSafe's System One decision model, prompt `reuse-v2` | about 0.3 s per pair, 8 pairs in parallel |
| `command` | Any program: the prompt (or the candidate as JSON) on stdin, a JSON verdict on stdout; 4 at once | whatever your model costs |
| `anthropic` | Claude through the official SDK (`dry-lint[anthropic]`) with the same DRY prompt and server-side refusal fallbacks; needs `ANTHROPIC_API_KEY`. Default model `claude-sonnet-5-5`; option `effort` | per pair: Sonnet 2 s and $0.0035, Opus 3 s and $0.008; 4 in parallel |
| `gemini` | Gemini over its REST API with the same DRY prompt; needs `GEMINI_API_KEY`, no CLI. Default model `gemini-3.1-pro-preview` | about 12 s per pair, 4 in parallel |
| `claude-code` | Claude through `claude -p` on a Claude subscription; default model `claude-sonnet-5-5` | the model's list price, out of the subscription; rate-limited |
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
