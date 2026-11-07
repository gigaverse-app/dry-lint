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
5. Deduplicate parents and return the best previously unseen eligible function. Scores and ties are deterministic.
   The returned Candidate preserves both native functions, signatures, documentation, coordinates and context.

The implementation is [`operation_blocks.py`](../src/dry_lint/operation_blocks.py); exact frequency and tie
rules are also documented in the [plugin contract](plugins.md#bounded-python-operation-blocks). These bounds
make work predictable, but they also create misses: a useful operation may be too small, occur after the first
12 regions, use different call names or lack a rare anchor. A zero block score does not establish different
behavior. The comparer identity is `operation-blocks:1`, and its score does not permit changed-code verdict reuse.

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
