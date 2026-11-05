# Discovery with a coding agent in the loop

Optimize useful discoveries per interruption. A coding agent can inspect a finding, consolidate a real shared
operation, or explain why the functions have different contracts. A cheap judge can therefore use a lower
reporting threshold than an unattended blocking check. The initial target is at least one confirmed real finding
per three false positives (25% precision), while improving recall and bounding false reports per commit.

`balanced` now brings this workflow into production: cheap shared-operation judging, a persistent campaign
budget, protected baseline retrieval and paced exploration, including same-file candidates. See the
[production setup and feedback contract](production-discovery.md). `agent-haiku` retains its original baseline-only
behavior for comparisons. Existing unattended presets remain available.

## Local feedback

```yaml
repos:
  - repo: https://github.com/gigaverse-app/dry-lint
    rev: v1
    hooks:
      - id: dry-lint
        additional_dependencies: ["dry-lint[hooks]"]
        args: [--preset, balanced, --env-file, .env, --budget-usd, '0.04']
```

Run `pre-commit install`. Python, JavaScript and TypeScript changes trigger the hook. It reads source from the
Git index, including staged additions and deletions, so an unstaged repair cannot clear a staged duplicate.
Pre-commit manages an isolated Python environment; it does not launch the project's `uv` under Git's exported
environment. The optional dotenv file supplies only judge credential variables, without overriding exported
credentials or interpolating other variables. Keep it untracked. Export `ANTHROPIC_API_KEY` instead if preferred.
The explicit preset requires a usable judge; missing credentials are an error rather than an unjudged clean pass.

A duplicate exits 1. Inspect the shared operation and preserve callers' authorization, transaction, error and
ordering contracts when extracting it. Stage the repair and retry. For an intentional distinction, add a narrow
`# dry-lint: distinct-from path::qualified_name` with the reason beside the function. Avoid blanket ignores as
an automatic response. The hook runs at commit time; it is not a server-side push gate.

Local balanced runs share a $0.04 campaign allowance across revisions, keyed by branch or explicit `--session`.
Reservations survive failures and process restarts. Hosted CI and local hooks use separate storage; a strict CI cap
requires persistent state. See [budget scope](production-discovery.md#cumulative-allowance).

## Feedback and adaptation

Keep three outcome types distinct:

| Observation | Meaning for calibration |
| --- | --- |
| Reviewer confirms shared behavior and the agent fixes it | Confirmed positive, linked to evidence and repair |
| Reviewer documents different contracts | Confirmed negative, with a narrow source suppression |
| Finding disappears, check is bypassed, model fails, or code is deleted | Unknown until explicitly reviewed |

A fix is useful feedback when the reviewer confirms what it fixed. A disappearing pair alone does not establish
that the original finding was correct. Cache reuse must not multiply one decision into many independent labels.
Record pair identity, both source hashes, judge/prompt/policy versions, first report, reviewer decision, repair
commit and time spent. Count repeated interruptions separately from unique findings and first discoveries.

Track retrieval recall before judging, reported recall after judging, first-discovery commit, false reports per
commit (including repeats), confirmed findings per minute, provider cost and p50/p95 latency. Report unknown
labels separately. A fixed reference panel plus randomly sampled below-threshold pairs is needed to estimate
misses; feedback on reported pairs alone cannot measure recall or safely tune thresholds.

Do not automatically lower thresholds merely because reports become rare. Rarity can mean a cleaner codebase,
a different kind of change, or a broken detector. Compare versioned policies on a rolling, independently reviewed
sample, stratified by repository, function size, new versus edited code, and shared-operation family. Change one
knob at a time; use hysteresis and a minimum sample before switching. Roll back when the 25% precision floor or
the interruption bound fails. Initial trials use at most three false reports per commit, not as a claim that all
developers will tolerate that load. Explicit fix/dismiss decisions now live in `.dry-lint-feedback.json`; automatic threshold control remains future work.

## Budget and eventual discovery

Every distinct source revision is another opportunity. Prefer baseline candidates first. Exploration and second
opinions share a bounded allowance that cannot consume reserved later-baseline calls or dollars. Unspent pacing
credit can carry forward, capped at the campaign's exploration allowance. A rerun of the same head earns no
additional credit. Changed evidence invalidates old judgments; an unchanged failed paid answer is charged and
remains unresolved. Deferred second opinions can run on later commits without paying for the first answer again.

The cascade reuses the production escalation contract: first-judge scores in a half-open interval receive a
second opinion, regardless of label. A successful second answer becomes the reporting decision; a failed or
unaffordable request retains the first decision at its own threshold. The replay records both stage identities,
actual usage, reservations, selected candidates and per-commit decisions. Second opinions do not count as new
retrieval coverage. Preserve these distinctions when implementing the scheduler in the runtime.

At four cents, a stronger second opinion can cost the opportunity to inspect many more pairs. Compare escalation
against simply lowering the cheap judge's threshold. Conservative maximum-output reservation also matters:
even the compact Sonnet prompt with a 512-token cap reserves more than one cent for a tiny pair. A one-cent
exploration allowance can therefore admit no second opinion, even when its eventual actual cost is much lower.

## Promotion decisions

The [production validation](production-discovery-results.md) now supports selecting `balanced` for coding-agent
hooks: the frozen policy passed the known-positive, budget, baseline and aggregate precision checks. The noisier
individual PR and latency limits are recorded there. Automatic threshold adaptation is still future work.

Use a separate profile when the audience or cost of a false positive changes, as with an agent-reviewed local
hook versus unattended CI. Update `balanced` only when one frozen policy improves recall on independent new
families, preserves baseline positives across long PRs, satisfies the interruption and precision bounds, and
works through the real runtime with persistent budgets, retries and cache invalidation. A promising replay is
insufficient. Compare matched $0.04 budgets and report physical experiment spend separately from counterfactual
replay cost. Retrieval-pool recall is conditional on the reviewed panel, never exhaustive repository recall.

Keep explicit high-precision and high-recall profiles for different interruption tolerances, rather than naming
every experimental scheduler configuration a public profile. General defaults and auto-selection remain unchanged.
