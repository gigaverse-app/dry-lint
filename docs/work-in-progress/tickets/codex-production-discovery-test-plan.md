# Production discovery and feedback

Extend #45 with durable campaign budgets and explicit reviewed feedback. The detector remains stateless.

- [ ] CLI campaign journey: multiple revisions share $0.04; repeated trees earn no pacing credit.
- [ ] Protected scheduling: exploration cannot consume later baseline capacity; new evidence reopens judgments.
- [ ] Provider failure and process interruption: reservation persists before calls; unknown usage remains charged.
- [ ] Concurrent reservations cannot overspend; separate branches/PRs have separate campaigns.
- [ ] Feedback journey: exact-source dismissal skips repeat judgments; edits reopen; fix requires changed source.
- [ ] Staged feedback and source agree; unstaged dismissals cannot clear staged findings.
- [ ] Split detect/judge carries provenance and reviewed dismissals; existing formats remain readable.
- [ ] Fresh PR replay through the production scheduler, frozen independent positives, live cheap judging.
- [ ] Existing baseline regression cohort, local hook smoke, full suite, lint, build and CI.
