---
name: dry-lint
description: Set up and tune dry-lint, the pull-request check that flags new code re-implementing a concept the codebase already has. Use to install it in a repository or in CI, to choose the judges and thresholds (presets), to pay with API keys or with a Claude or ChatGPT subscription, to set a cost budget, to silence false positives, or to measure a change with a gold set.
license: Apache-2.0
---

# Setting up dry-lint

dry-lint proposes look-alike pairs for the functions a change touched (no model, seconds), and judges decide
whether each pair is one concept implemented twice. **The judges and the thresholds are chosen together, as a
preset**: a threshold means something only for the judges it was measured with. Start from a preset; set fields
explicitly only when you have a reason, and re-measure when you do.

## 1. See what would run

```bash
uvx --from git+https://github.com/gigaverse-app/dry-lint dry-lint config
```

It prints the preset in effect, the credentials it found (names only), the judges, the thresholds, the budget,
the cost per pair, and every preset with what it still needs. Every report ends with the same line, so a
pull request always says which judges ran, on which thresholds, and what they cost.

## 2. Choose how to pay

| You have | Preset | Fails at | Precision / recall | Cost per pull request |
| --- | --- | --- | --- | --- |
| Jev key + Anthropic API key | `jev+opus` (recommended) | 0.55 | 98% / 85% | about $0.005 |
| Jev key + Claude subscription (Pro, Max, Team) | `jev+claude-code` | 0.55 | same model (Opus) as above | about $0.005 of subscription use |
| Jev key + Anthropic API key, cheaper | `jev+sonnet` (named only) | 0.7 | 97% / 84% | about $0.0035 |
| Jev key + ChatGPT subscription (`codex` CLI) | `jev+codex` (named only) | 0.7 | 96% / 85% | ~1 call, ~14 s |
| Jev key only | `jev` | 0.8 | 94% / 73% | about $0.0002 |
| Anthropic API key only | `sonnet` | 0.7 | 97% / 63% (large PRs run out of budget) | about $0.007 |
| Claude subscription only | `claude-code` | 0.7 | same model as above | about $0.007 of subscription use |
| Nothing | `none` | - | lists candidates, never fails | free |

Measured on a 250-pair gold set from 600 gigaverse-ai pull requests, within the default budget of $0.04 a pull
request, every push included ([benchmark](../../docs/benchmark.md#within-a-budget)).
`preset = "auto"` (the default) takes the first row whose credentials are in the environment. A subscription
preset is chosen automatically only when `CLAUDE_CODE_OAUTH_TOKEN` is set; name it to use a logged-in CLI.

**API keys:** `TYPESAFE_AI_API_KEY` for Jev, `ANTHROPIC_API_KEY` for Claude (`pip install 'dry-lint[anthropic]'`).

**A subscription instead of an API key** is usually cheaper for a team that already pays for one:

- Claude: install the `claude` CLI and log in. For CI, run `claude setup-token` once and store the long-lived
  token as the secret `CLAUDE_CODE_OAUTH_TOKEN`. dry-lint removes `ANTHROPIC_API_KEY` from the CLI's
  environment, so the subscription, not the API, is used. All tools are off: the CLI only reads the prompt.
- ChatGPT: install the `codex` CLI and `codex login`; set `preset = "jev+codex"` (it runs in an empty folder, in a
  read-only sandbox). It uses the account's default model unless you set `model`.

A subscription call is counted against the budget at its model's list price, the same as an API call, and a run
also asks a subscription at most `budget.subscription_calls` times, because subscriptions are rate-limited.

## 3. Write the settings

```toml
[tool.dry-lint]
preset = "jev+opus"            # or leave "auto"
# Explicit values win over the preset's:
# fail_at = 0.8                # fail only above this judge score; report_at warns from a lower one
# escalate = { use = "claude-code", model = "claude-opus-5-5", between = [0.5, 0.91], first_at = 0.8 }
#                              # the same judging, through a subscription (preset jev+claude-code)
[tool.dry-lint.budget]
usd = 0.04                     # most judging spends on a pull request, all pushes, at list price
subscription_calls = 20
```

The verdict store remembers what each pull request has spent, so later pushes spend what is left. When the
budget runs out, the riskiest pairs have been judged; the rest keep the first judge's answer, held to the first
judge's own threshold (or stay unjudged, and are asked again while budget remains); the report says how many. A judge with an unknown price (a custom command) is not budgeted and
its cost shows as unknown, never as zero. Add prices under `[tool.dry-lint.prices]` as
`"model-name" = [input_usd_per_million, output_usd_per_million]`.

## 4. Wire it in

Use `gigaverse-app/dry-lint@main` until v1 launches, then `@v1`. Use published major-version tags for
established Actions (for example, `actions/checkout@v7`); do not substitute commit hashes.

- **GitHub Actions:** [docs/github-action.md](../../docs/github-action.md). Pass the keys as secrets
  (`typesafe-api-key`, `anthropic-api-key`); `fail-at` overrides the threshold per workflow.
- **pre-commit:** the `dry-lint` hook checks staged functions.
- **By hand or from an agent:** `dry-lint check` (since the default branch), `dry-lint scan` (the backlog).
- **For a coding agent's own loop:** a cheap judge with high recall is enough, because the agent judges again:
  `dry-lint check --staged --preset jev --format json` lists every judged pair with its score; review those from 0.6
  up. Keep the escalating presets (`jev+opus`) for what people read and what blocks a merge
  ([who reads the findings](../../docs/judges.md#who-reads-the-findings-people-or-coding-agents)).

## 5. When it is wrong

A false positive is a decision that belongs next to the code, not in the verdict store:

- one pair: `# dry-lint: distinct-from <qualified name>` in the new function;
- one function: `# dry-lint: ignore`;
- a family of deliberate look-alikes: a `[[tool.dry-lint.patterns]]` entry with a `reason`;
- one pull request: the `dry-lint: override` label.

If you are the coding agent reading a finding, you are its final judge. Open both functions. If they are one
concept, reuse or extend the existing one rather than keeping the copy. If they are not, add the `distinct-from`
line with the reason they differ, so no one is asked again.

`dry-lint explain A B` shows why a pair was or was not reported.

## 6. Change thresholds only with a measurement

Lowering `fail_at` finds more duplicates and fails more pull requests; raising it does the reverse. Before
changing it, measure on your own code:

```bash
dry-lint bench --gold gold.jsonl                    # the configured judges, with 90% intervals
dry-lint bench --gold gold.jsonl --preset jev       # another preset on the same pairs
dry-lint bench --replay 50                          # what check would have done on the last 50 commits
dry-lint bench --replay 50 --fail-at 0.9            # the same verdicts at a stricter threshold, at no cost
```

Before turning dry-lint on, or changing a preset or `fail_at`, replay the repository's recent history: it shows
which pull requests would have failed or warned and what judging cost, from verdicts kept in the store. Add
`--label 100` (with `OPENROUTER_API_KEY`, about $3) to learn what that judging would catch, miss and block wrongly
on this repository, and to get a gold set for `bench --gold`.

A gold set is JSON lines of labelled pairs ([format](../../docs/benchmark.md#running-it)). Label at least 200
pairs, most from the scores where decisions happen; report every number with its interval, because a handful of
heavily weighted pairs can move a point estimate by ten points.
