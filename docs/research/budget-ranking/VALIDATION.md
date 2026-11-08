# Validation

The complete bundle was copied to a fresh temporary directory outside the repository. `python3 -I algorithm.py`, `python3 -I replay.py` and `python3 -I verify.py` passed with a minimal environment, without provider credentials or network requests.

The algorithm check executes only the original allowlisted `feature_order` and `Ledger.select` definitions; archived module top levels do not run. All 25 original candidates match all four frozen orders and funded sets. The result replay checks 124 cases, 248 paid questions, both physical costs, the unchanged 0.80 rule, and the one malformed shared control. It reparses raw public Claude text and compares recorded parsed labels/scores before aggregating original admissions.

The verifier checks selected full-source hashes, absence of held inputs, local Markdown links and manifest hashes. Sensitive-pattern scanning traverses every publication file and decompresses every gzip file. It searches private repository/incident identifiers, common provider token formats and private-key markers. This is an evidence-based scan, not proof that arbitrary unknown secret formats are impossible. Public source includes ordinary API-key parameter names; no credential values were introduced.

Both study background hashes were matched by SHA256 to the separate pinned goldens catalog and its hash-verified dataset manifests. The acquisition script uses exact Git objects; no corpus clone/fetch or refit was performed for publication. Remote proposed-branch links name the intended branch and destination; they become live only after root publishes.

The full repository suite and self-lint were not run: this handoff contains isolated research bundles, with no product or CI edits and no push. This check does not rerun the full retrieval study, authenticate independent labels anew, or make private history reproducible. Those boundaries are in [DATA-CONTRACT.json](DATA-CONTRACT.json).
