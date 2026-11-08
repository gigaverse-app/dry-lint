# A small repeated rule can justify a family-level recommendation

**Accept one scoped refactoring-family example.** At one pinned LiteLLM revision,
18 optional-budget validation guards in ten functions can share one helper. The
concrete local patch removes **67 net lines and 16 executable statements**, including
helper overhead; removing one newly unused import brings the complete patch to 68
lines saved. Independent source review accepted this bounded family and its
proposed-after already-shared negative control.

This changes the unit of useful review. Earlier pair-level judgments called the
short guards tiny or disputed. Those judgments remain intact. The new evidence is a
single multi-owner consolidation task, not 45 positive pairs inferred from ten owners,
not 18 newly discovered families, and not a merged upstream refactoring.

## The actual extraction

Every eligible site implements the same rule: an unset budget is allowed; otherwise
it must be finite and nonnegative. Failure raises HTTP 400 with the same field-named
error format. The proposed helper is:

```python
def validate_nonnegative_budget(value: float | None, field_name: str) -> None:
    if value is not None and (not math.isfinite(value) or value < 0):
        raise HTTPException(
            status_code=400,
            detail={"error": f"{field_name} must be a non-negative finite number. Received: {value}"},
        )
```

Each inline guard becomes one call at its original position. For example,
`validate_nonnegative_budget(data.max_budget, "max_budget")` preserves the field label
and original validation order. The extraction leaves cross-field comparisons,
authorization checks, caller-specific errors and existing private adapters intact.
The complete proposed change is in [extraction.patch](extraction.patch).

| Source owners | Guard sites |
| --- | ---: |
| Team create/update | 6 |
| Organization create/update | 4 |
| Budget create/update | 4 |
| Key generate/update | 2 |
| Two existing key-validation helpers | 2 |
| Total: ten function owners in four modules | 18 |

The two helpers are real implementation owners; their existing callers are delegates
and contribute no extra copies. There are three field variants: nine `max_budget`,
seven `soft_budget`, and two `team_member_budget` sites. The patch touches five files,
including the existing common utility module where the shared validator is placed.

## Evidence and limits

Source is `BerriAI/litellm` at
`fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f`. The mechanical scan parsed 3,111 scoped
Python files with no parse failures. Its complete-AST match is exhaustive for this
exact rule and message shape in that scope, not for every semantically equivalent
validator. Enterprise, tests, generated files and explicit capture exclusions are
outside the scope. Source snapshots, license, Git blob IDs, complete owner bodies,
source spans and before/proposed-after hashes are retained with the evidence.

Eight focused tests passed, including exact guard behavior, validation precedence,
whole-file AST change boundaries and mutation controls. The independent audit added
4,080 stable-value/order checks; 558 model-field samples reproduced after canonical
sorting. The coordinator verified the frozen inputs and reran the eight tests from a
relocated copy. Cases include None, finite values, zero/signed zero, negatives,
NaN/infinities, booleans and invalid Python inputs. Field-slice admission tests use
Pydantic; they do not execute complete request models or the LiteLLM application.

A real counterexample bounds equivalence: a property returning a different value on
successive reads may behave differently after extraction. The original guard can read
a field repeatedly; a helper argument reads it once. Acceptance is therefore limited
to ordinary stable stored budget fields. Stateful properties, arbitrary subclasses,
custom operators, concurrent mutation and monkeypatched globals are outside the proof.
FastAPI was unavailable in the test environment: tests compare exact exception-
constructor arguments, not live HTTP responses, middleware or serialization. Import
cycles and full application integration remain untested. This is a reviewable local
proposal, not an upstream-ready patch or a measured incident reduction.

Near-matches were retained as counterexamples: organization-v2 guards use HTTP 422;
a model-specific guard rejects None; finite-only spend validation permits negatives.
The proposed helper must not silently replace those contracts. After the scoped patch,
one implementation serves ten delegates through 18 calls. That is an already-shared
negative control for this exact operation, not a historical merged-PR negative.

## What retrieval does and does not establish

All ten owner identities and full-body hashes match the same frozen 37,604-function
background. Raw whole-function TF-IDF has 90 directed relationships among these
members; these are membership diagnostics, not 90 positive gold rows. Self is excluded;
ties use descending exact cosine and ascending frozen document position.

| Diagnostic | Result |
| --- | ---: |
| Raw top-one/top-three directed member hits | 6/90 and 10/90 |
| Same-file directions | 18/90 |
| Below the default query-length score floor | 80/90 |
| Below the balanced TF-IDF floor of 0.35 | 56/90 |
| Queries finding any sibling under default TF-IDF-only rules | 2/10 |
| Queries finding any sibling under balanced TF-IDF-only rules | 9/10 |

These floor settings are explicit diagnostic assumptions, not inferred adopter
configuration. The default comparer uses 0.5, or 0.3 for query functions shorter than
six lines; baseline TF-IDF excludes same-file targets. The balanced TF-IDF arm uses
0.35 and twenty neighbors, including same-file targets. Other filters, operation blocks,
judging and campaign budget are not part of that table.

A separate actual current-main Detector check includes operation blocks and uses
`update_key_fn` alone as the changed function. It emits four candidates, none of the
other nine direct rule owners. Some candidates delegate to existing validators, so
this is **not proof of zero baseline opportunity** or additional useful reports. The
full ten-owner batch is also preserved separately; its query counts must not be pooled
with independent single-query diagnostics. Exact rule expansion demonstrates complete
family coverage and a concrete extraction benefit; end-to-end detector gain is unmeasured.

## Decision

Use this as a family-level benchmark and an advisory consolidation example. The
concrete saved implementation and preserved contract justify one task even though
individual short overlaps may be poor standalone reports. A future general family
method must show similar value on additional rules and retain incompatible neighbors;
this study does not justify a hard-coded budget-validator product feature or a global
threshold change. Existing pair labels, product defaults and CI remain unchanged.

## Reproduce without a provider

The public files contain the extraction implementation, tests, proposed patch and
retrieval scripts. Full source snapshots, independent reviews and the complete
TF-IDF background live in the private
[corpus dataset, PR #10](https://github.com/gigaverse-app/dry-lint-goldens/pull/10).
Access to that repository is required. Pin it to merge
`ab31d5baa6d57c368ebb81586e91f677965cbe8e`; the dataset is
`budget-family-proof-v1`. It adds one accepted family and one proposed-after control,
**zero pair-positive labels**. LiteLLM source retains its [MIT notice](LITELLM-LICENSE).

Use Python 3.14.4 with Pydantic 2.14.2 and the system `patch` command, as tested.
For retrieval, use a dry-lint environment installed from the locked dependencies at
`2aab042c256141383c7c731b7ba6097dd2db53b3`. Keep the virtual environment's Python
path intact: resolving its symlink to the system interpreter loses installed packages.
Set these paths to your local checkouts; output directories must not exist:

```bash
PY=/absolute/path/to/venv/bin/python
CORPUS=/absolute/path/to/dry-lint-goldens
STUDY=/absolute/path/to/dry-lint/examples/research/budget-family-proof
FIXTURE=/tmp/budget-family-fixture

"$PY" "$CORPUS/corpus.py" materialize budget-family-proof-v1 --out "$FIXTURE"
"$PY" "$STUDY/reproduce.py" --fixture "$FIXTURE" --out /tmp/budget-family-proof

PYTHONPATH="$FIXTURE/retrieval/runtime/src" "$PY" "$STUDY/detect.py" \
  --fixture "$FIXTURE" --out /tmp/budget-family-detector \
  --query litellm/proxy/management_endpoints/key_management_endpoints.py::update_key_fn

PYTHONPATH="$FIXTURE/retrieval/runtime/src" "$PY" "$STUDY/family-tfidf-diagnostic.py" \
  --background "$FIXTURE/retrieval/background.json.gz" \
  --inventory "$FIXTURE/proof/inventory.json" --out /tmp/budget-family-ranks
```

The proof command verifies frozen source hashes, rebuilds the proposed extraction,
runs all eight tests and compares metrics plus all 558 model-field samples. Expected:
one family, 18 sites, ten owners, 16 statements and 67 guard-extraction lines saved.
The Detector command verifies the pinned runtime and source identities, then recomputes
and exactly compares all four recorded candidates. Omitting `--query` reproduces the
separate ten-owner batch. The rank command rebuilds the production index and writes
all 90 directional ranks/scores plus explicit score-floor and same-file diagnostics.
No command calls a judge or needs a provider key.

Public Python files are formatted for reading; the proof wrapper executes the original
hash-bound `proof/study.py` and `proof/test_equivalence.py` in the private fixture.
`accepted-families.jsonl` and `proposed-after-controls.jsonl` hold the reviewed records;
the original pending-review producer record remains unchanged. `audit/AUDIT.json`
contains the independent verdict and its conditions. Some archived reviewer scripts
retain original lab paths; they are provenance, not the portable entry point above.
Relocated proof and current-Detector reproduction both passed. The proof remains
limited to the stated stable-field contract and does not test full app integration.
