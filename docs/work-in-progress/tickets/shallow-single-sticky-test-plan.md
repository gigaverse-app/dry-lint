# Shallow checkouts and one sticky

- [x] Reproduce unwanted old-history fetch and three legacy keyed comments before fixing.
- [x] Real shallow Git clones: retain exact PR diff, exclude old history/unrelated branch objects, handle diverged base and missing tracking refs, fail explicitly at the depth bound.
- [x] HTTP transport integration: combine clean/positive scopes, reconcile legacy keys, resolve once, retain human discussion, reject stale heads.
- [ ] Full library checks and live GitHub Actions in all three FE PRs: one sticky each with both scopes and shallow peer snapshots.
