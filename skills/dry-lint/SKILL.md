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
| Jev key + Anthropic API key | `jev+sonnet` (recommended) | 0.7 | 97% / 84% | about $0.004 |
| Jev key + Claude subscription (Pro, Max, Team) | `jev+claude-code` | 0.7 | same model as above | no per-call cost; ~1 call |
| Anthropic API key only | `sonnet` | 0.7 | 97% / 84% | about $0.011 |
| Jev key + ChatGPT subscription (`codex` CLI) | `jev+codex` (named only) | 0.7 | 96% / 85% | no per-call cost; ~1 call, ~14 s |
| Claude subscription only | `claude-code` | 0.7 | same model as above | no per-call cost; ~3 calls |
| Jev key only | `jev` | 0.8 | 94% / 73% | about $0.0001 |
| Nothing | `none` | - | lists candidates, never fails | free |

Measured on a 250-pair gold set from 600 gigaverse-ai pull requests ([benchmark](../../docs/benchmark.md)).
`preset = "auto"` (the default) takes the first row whose credentials are in the environment. A subscription
preset is chosen automatically only when `CLAUDE_CODE_OAUTH_TOKEN` is set; name it to use a logged-in CLI.

**API keys:** `TYPESAFE_AI_API_KEY` for Jev, `ANTHROPIC_API_KEY` for Claude (`pip install 'dry-lint[anthropic]'`).

**A subscription instead of an API key** is usually cheaper for a team that already pays for one:

- Claude: install the `claude` CLI and log in. For CI, run `claude setup-token` once and store the long-lived
  token as the secret `CLAUDE_CODE_OAUTH_TOKEN`. dry-lint removes `ANTHROPIC_API_KEY` from the CLI's
  environment, so the subscription, not the API, is used. All tools are off: the CLI only reads the prompt.
- ChatGPT: install the `codex` CLI and `codex login`; set `preset = "jev+codex"` (it runs in an empty folder, in a
  read-only sandbox). It uses the account's default model unless you set `model`.

Subscriptions are rate-limited rather than billed, so a run asks them at most `budget.subscription_calls` times.

## 3. Write the settings

```toml
[tool.dry-lint]
preset = "jev+sonnet"          # or leave "auto"
# Explicit values win over the preset's:
# fail_at = 0.8                # fail only above this judge score; report_at warns from a lower one
# escalate = "claude-code"     # the same thresholds, through a subscription
[tool.dry-lint.budget]
usd = 0.25                     # most a run spends on priced judges; riskiest pairs are judged first
subscription_calls = 20
```

When the budget runs out, the remaining pairs keep the first judge's answer (or stay unjudged, and are asked
again next run); the report says how many. A judge with an unknown price (a custom command) is not budgeted and
its cost shows as unknown, never as zero. Add prices under `[tool.dry-lint.prices]` as
`"model-name" = [input_usd_per_million, output_usd_per_million]`.

## 4. Wire it in

- **GitHub Actions:** [docs/github-action.md](../../docs/github-action.md). Pass the keys as secrets
  (`typesafe-api-key`, `anthropic-api-key`); `fail-at` overrides the threshold per workflow.
- **pre-commit:** the `dry-lint` hook checks staged functions.
- **By hand or from an agent:** `dry-lint check` (since the default branch), `dry-lint scan` (the backlog).

## 5. When it is wrong

A false positive is a decision that belongs next to the code, not in the verdict store:

- one pair: `# dry-lint: distinct-from <qualified name>` in the new function;
- one function: `# dry-lint: ignore`;
- a family of deliberate look-alikes: a `[[tool.dry-lint.patterns]]` entry with a `reason`;
- one pull request: the `dry-lint: override` label.

`dry-lint explain A B` shows why a pair was or was not reported.

## 6. Change thresholds only with a measurement

Lowering `fail_at` finds more duplicates and fails more pull requests; raising it does the reverse. Before
changing it, measure on your own code:

```bash
dry-lint bench --gold gold.jsonl                    # the configured judges, with 90% intervals
dry-lint bench --gold gold.jsonl --preset jev       # another preset on the same pairs
```

A gold set is JSON lines of labelled pairs ([format](../../docs/benchmark.md#running-it)). Label at least 200
pairs, most from the scores where decisions happen; report every number with its interval, because a handful of
heavily weighted pairs can move a point estimate by ten points.
