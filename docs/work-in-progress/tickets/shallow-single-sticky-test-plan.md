# Shallow checkouts and one sticky

- [x] Reproduce unwanted old-history fetch and three legacy keyed comments before fixing.
- [x] Real shallow Git clones: retain exact PR diff, exclude old history/unrelated branch objects, handle diverged base and missing tracking refs, fail explicitly at the depth bound.
- [x] HTTP transport integration: combine clean/positive scopes, reconcile legacy keys, resolve once, retain human discussion, reject stale heads.
- [x] Full library checks and live GitHub Actions in all three FE PRs: one sticky each with both scopes and shallow peer snapshots.

Evidence: [library CI](https://github.com/gigaverse-app/dry-lint/actions/runs/41638208731),
[common](https://github.com/gigaverse-app/frontend-common/actions/runs/41638266500),
[web](https://github.com/gigaverse-app/gigaverse-web-app/actions/runs/41638270227),
[mobile](https://github.com/gigaverse-app/gigaverse-mobile/actions/runs/41639153468).
The GitHub API showed exactly one complete dry-lint comment on each PR after publishing.
All nine recorded primary/peer snapshot statuses were shallow. The pinned runtime passed 434 tests
with 100% coverage on Python 3.11 and 3.13. A real HTTP server regression also verifies inherited
checkout authorization headers are reset and only the process-scoped token is sent.
