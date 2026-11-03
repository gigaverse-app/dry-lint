# Agent-reviewed discovery and uncertain-judge escalation

Use the coding agent as the final reviewer of local findings. Evaluate a 25% confirmed-finding precision floor
(at least one real finding per three false positives), with false interruptions per commit and recall reported
separately. Never infer confirmation from a disappeared candidate. Explicit fixes and false-positive decisions
are feedback; bypasses, unavailable judges and unreviewed disappearances remain unknown.

- [ ] Local hooks: real pre-commit integration, staged Python/TypeScript, committed pre-push snapshots, rejected
  duplicate then successful repair/specific suppression; keep unstaged work and existing hooks intact.
- [ ] Credentials: explicit environment or optional local dotenv, no secret values in output/config; isolated hook
  dependencies; verify installations in backend and AI worktrees.
- [ ] Cascade replay: reuse the existing escalation contract; real SDK/fake provider for both paid stages,
  uncertain first scores, failed/deferred second opinions, identity changes and exact evidence invalidation.
- [ ] Scheduling: reserve future baseline calls/dollars and second-opinion capacity at a cumulative $0.04 per PR;
  spend each cached observation once per counterfactual; repeated heads do not earn credit or hide paid failures.
- [ ] Development then freeze: evaluate previous histories, freeze thresholds/routing before fresh judgments;
  independently review fresh PRs with new positive families and negative controls. Physical research cap: $5.
- [ ] Feedback design: controlled threshold changes from confirmed outcomes; retain an unbiased exploration/audit
  sample and separate agent-loop utility from autonomous blocking quality. No automatic global threshold changes.
- [ ] Full tests, Ruff, build, detector self-check, exact-head CI and Conventional Commits PR titles.
