# Production discovery and feedback

Extend #45 with durable campaign budgets and explicit reviewed feedback. The detector remains stateless.

- [x] CLI campaign journey: multiple revisions share $0.04; repeated trees earn no pacing credit.
- [x] Protected scheduling: exploration cannot consume later baseline capacity; new evidence reopens judgments.
- [x] Provider failure and process interruption: reservation persists before calls; unknown usage remains charged.
- [x] Concurrent reservations cannot overspend; separate branches/PRs have separate campaigns.
- [x] Feedback journey: exact-source dismissal skips repeat judgments; edits reopen; fix requires changed source.
- [x] Staged feedback and source agree; unstaged dismissals cannot clear staged findings.
- [x] Split detect/judge carries provenance and reviewed dismissals; existing formats remain readable.
- [x] Fresh PR replay through the production scheduler, frozen independent positives, live cheap judging.
- [x] Existing baseline regression cohort, local hook smoke, full suite, lint, build and CI.

Validation: 817 tests in Python 3.11/3.13 CI with 100% coverage; cross-platform action installation;
11 fresh PRs / 42 commits and two regression PRs / 16 commits; live installed hook fix/dismiss journey.
See docs/production-discovery-results.md for costs, conditional recall and limitations.
