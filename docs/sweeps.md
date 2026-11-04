# Adopt dry-lint with a shrinking backlog

A repository can start enforcing new duplication without fixing all its existing debt in one pull request.
The sweep records specific judged duplicate pairs; subsequent checks allow only those unchanged pairs.
Removing an old pair never buys permission to add a different one.

The implementation in this branch adds a repository sweep, a shrinking baseline, strict CI checks and a
README progress block backed by a Shields.io endpoint JSON file. Existing PR prevention totals retain their
meaning: backlog cleanup is counted separately.

## Invariants and validation plan

- [ ] Exercise initialization, unchanged debt, cleanup and reintroduction through the real CLI in temporary Git repos.
- [ ] Reject incomplete judging, missing credentials, invalid baselines and widening of the accepted pair set.
- [ ] Keep suppressed pairs separate from cleaned pairs; avoid cleanup claims from candidate-ranking changes.
- [ ] Verify README updates are idempotent and the generated endpoint follows Shields.io's schema.
- [ ] Run sweeps on CI-esta, pytest-selective, Due and pytest-obligation and record actual backlog counts.
- [ ] Exercise the Action's trusted judging path and required-check behavior for fork contributions.

Sweeps identify work for a maintainer or coding agent. They do not automatically rewrite arbitrary functions.
