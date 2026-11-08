# Validation

The entire publication was copied to a fresh temporary directory outside the checkout. `python3 -I algorithm.py`, `python3 -I replay.py` and `python3 -I verify.py` passed with a minimal environment and no credentials or network requests.

The original gate's scoring methods reproduced seven shared operations, two calls, containment 0.40558048873008107 and acceptance for the Azure pair using frozen statistics from 37,604 documents. This does not rebuild the index or embeddings. Recorded-answer replay covers 75 public/held case records, retains all 28 missing novel answers, and keeps one private case's counts/spend separate. The original all-scope static table is retained as an aggregate; private per-case tokens were removed from published row archives and their omission counts are explicit.

Checks cover raw Claude response parsing, original prompt identity hashes, label/score agreement, original policy projections, selected full-source hashes, held-source exclusion, local Markdown links and SHA256SUMS. The sensitive-content scan decompresses gzip archives and checks private repository/incident identifiers, common credential patterns and private-key markers; it cannot prove absence of every unknown secret format.

The three held payloads contain no candidate bodies, rendered prompt text, source excerpts, raw answers or answer prose. `hydrate.py` requires the exact local original ledger SHA256 before restoring a named held case. The public source hydrator reads existing pinned Git objects only. Four paid-case background hashes have exact matches in hash-verified goldens catalog manifests; the held background does not. Acquisition was not a new corpus/refit experiment.

Proposed branch links become live when root publishes; only their intended structure was checked locally. Product tests and self-lint were not run because no product or CI code changed and this worker does not push. Full experiment and provider reruns remain outside the [data contract's portable scope](DATA-CONTRACT.json).
