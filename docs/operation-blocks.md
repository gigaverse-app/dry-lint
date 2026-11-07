# Operation blocks: find a helper's work inside a larger function

The `operation-blocks` comparer targets Python functions that repeat a useful operation inside different
surrounding workflows. Whole-function similarity can be low because one function contains much more unrelated
work. Comparing complete syntax regions can recover that match while still giving the judge both full functions.

Use it after TF-IDF exploration when you are looking for repeated parsing/validation, error translation,
resource handling or other multi-step helper operations. It is a poor fit for one-line wrappers, generic logging,
or methods whose only resemblance is common library APIs. It currently supports Python, not TypeScript or model
declarations. See [choosing a comparer](discovery-comparers.md) for the configuration and paired trial procedure.

## A concrete example

These simplified functions contain the same packet-processing operation:

```python
def make_packet(owner, payload):
    packet = owner.decode_packet(payload)
    packet.validate_packet(owner.schema)
    packet.attach_receipt(owner.receipt)
    return owner.encode_packet(packet)


def send_order(owner, payload, transport):
    owner.authorize_delivery()
    try:
        packet = owner.decode_packet(payload)
        packet.validate_packet(owner.schema)
        packet.attach_receipt(owner.receipt)
        encoded = owner.encode_packet(packet)
    except PacketError:
        owner.record_delivery_failure()
        raise
    return transport.send(encoded)
```

The useful question is whether `send_order` can call `make_packet` inside its existing `try` block. Authorization,
failure recording, exception propagation and sending remain in the caller. This is an illustrative mechanism,
not a measured corpus result or a recommendation to merge the whole functions.

Contrast two wrappers that both already call `make_packet`: they share an implementation. Or contrast two
functions that both log, loop and close something but apply different ownership or cancellation rules. Shared
syntax is insufficient; the judge must inspect the actual contracts and existing helper ownership.

## What the comparer does

```text
Full indexed functions -> corpus token frequencies and bounded region index
Changed full function  -> complete syntax regions -> rare operation anchors
                                                    |
                                      bounded parent shortlist
                                                    |
                                guarded region-to-region comparison
                                                    |
                                      complete function candidate
```

1. Parse the function into whole compound statements and consecutive straight-line statement runs. A region
   never includes a nested function or class body. Large regions are rejected rather than cut into arbitrary
   windows; compound suites are visited through depth three.
2. Keep at most 12 regions in source order. Each spans 4–80 lines and 20–400 executable syntax nodes, has at
   least eight distinct behavior tokens and two nongeneric calls. Function-name tokens are excluded from the
   region representation.
3. Use frequencies from the **complete function background**, not just the query or gold snippets. Rare calls,
   attributes and literal keys select potential matching parents. Common logging and collection operations
   do not act as meaningful anchors.
4. Bound lookup to eight anchors per region, 64 postings per anchor and 64 candidate parents. Oversubscribed
   anchors are dropped. Each region match needs three shared concrete operations, two shared calls and a retained
   shared anchor. Its cosine must reach 0.65 and the full-function cosine must reach 0.10.
5. Deduplicate parents and return the best previously unseen eligible function. If the original region route
   has no eligible winner, try a second index with at most one complete helper body added per function. This
   body excludes its docstring, rejects nested owners, and passes the same size, operation and score guards.
   Its independently capped postings preserve the original route and scores. The fallback has at most 13
   regions, 6,656 posting visits and 10,816 region comparisons. Scores and ties are deterministic.
   The returned Candidate preserves both native functions, signatures, documentation, coordinates and context.

The implementation is [`operation_blocks.py`](../src/dry_lint/operation_blocks.py); exact frequency and tie
rules are also documented in the [plugin contract](plugins.md#bounded-python-operation-blocks). These bounds
make work predictable, but they also create misses: a useful operation may be too small, occur after the first
12 regions, use different call names or lack a rare anchor. A zero block score does not establish different
behavior. The comparer identity is `operation-blocks:2`, and its score does not permit changed-code verdict reuse.

## Why the complete-helper fallback matters

A helper can perform a single operation across a short setup, a `try`/`finally` and a return. Each region may
be too small to qualify alone, so version 1 never retrieves it. Version 2 can compare the complete helper body
while preserving its exception and cleanup boundaries in the returned source:

```python
def commit_staged(path):
    token = acquire_staging(path)
    try:
        publish_staging(token)
    finally:
        release_staging(token)
    return receipt_for(path)
```

The fallback adds a representation; it does not move `release_staging` out of `finally`, label the function a
duplicate, or replace an original region winner. An earlier winner can still consume the available retrieval
slot, and a later scheduler can still displace another candidate under a fixed budget. Retrieval preservation
and report preservation therefore require separate checks.

## What has been measured

In the frozen Python source-supported panel, adding the original block route after baseline3 plus explicit
TF-IDF20 increased positive pairs funded under a synthetic $0.04 allowance from **35/39 to 37/39**. It also
increased separate pairs funded from **35/80 to 38/80**. These are candidate exposures, not production reports,
and the source-supported subset is smaller than the complete historical label inventory.

A useful concrete case was LiteLLM's existing access-token error helper versus a longer Responses configuration
function repeating its error translation. Whole-function cosine **0.347608** missed the explicit exploration
floor of **0.35**; region cosine **0.976964** exposed an affordable pair. A Sonnet shared-operations answer at
**0.80** and independent source inspection supported reusing the helper while retaining caller-specific headers,
credential choice and exception behavior. The exact original concept-policy answer was not obtained, so this
is a diagnostic benefit, not proof of a default-production report gain.

A later research-only filter removed regions already represented in an earlier neighbour. That filter lost
the token-error opportunity and a useful atomic-file commit helper report. **It is not included here.** An
operation appearing elsewhere does not prove that this caller already delegates to the right helper.

Keep the route opt-in for partial-operation exploration. Measure added useful reports, displaced reports and
runtime in your repository before recommending it broadly. Neither the tested research judge settings nor the
synthetic allowance should be silently substituted for an adopter's configured policy.

## Complete-helper follow-up

The new helper representation was tested against the original block route, with the earlier TF-IDF routes
preserved. On 37 newly funded candidate pairs, independent source review found 11 bounded useful extractions,
5 tiny conveniences and 21 already-shared, related or separate pairs. Sonnet/shared-operations at the diagnostic
.80 reporting rule emitted three bounded useful reports: TLS-context construction, streaming hook/text
accumulation, and custom key-policy invocation. These are partial extractions with caller-specific guards,
error handling and ownership retained.

A separate cold-campaign comparison used the actual balanced Haiku policy, a 2,048-token output hold and
independent .04 ledgers. Across the full admission delta, 38 pairs became funded and 28 prior pairs lost funding.
New reports included 10 bounded useful operations, 2 tiny ones and 5 source-unsupported reports. Lost prior
reports included 1 bounded useful operation, 1 tiny one and 2 source-unsupported reports. Thus the selected
panel gained **nine net bounded useful reports**, while adding three net unsupported reports. This supports an
opt-in capability with a measured precision tradeoff, not a default-policy recommendation. Reports on common
admissions cancel in this delta comparison; this is not an overall precision/recall estimate.

The balanced run is a native cold-query admission simulation using real pinned source, not observed historical
PR traffic or a settlement-timing replay. Thirty-four of the initial 37 candidates overlap prior family proxies
and three are development cases; there is no fresh confirmation candidate family. The ten bounded additions
span nine frozen proxy components, which are not independently established semantic families. Seven canonical Jev questions
truncate a body at 8,000 characters. All Claude questions and source reviews contain complete native functions;
the partial Jev inputs remain explicitly marked in the records. Exact model, input and policy matches are required
for cached answers, and each arm still pays its normal logical charge.

The extra representation has a runtime cost. In the measured LiteLLM background, cold indexing rose from
27.46 to 41.94 seconds; a paired warm query batch rose from 2.45 to 3.97 seconds. Original winners and scores
were preserved in 964 sampled winning queries, and representation/posting parity was checked across 119,312
available native function occurrences. A separate Due/pytest extension reconstructed 14 exact backgrounds
and 115 labeled pair/background combinations: both original and helper routes retained their funded outcomes.
These observations support bounded regression confidence, not a claim of zero future regressions.

The [helper-recovery study](https://github.com/gigaverse-app/dry-lint/pull/115) supplies the frozen implementation,
exact prompts and recorded answers, source-review boundaries, budgets, and provider-free reproduction. Full
retrieval refitting requires the separately identified complete backgrounds; never fit IDF on just the selected
source examples. See the [research index](research-results.md) for the other directions and their conclusions.
