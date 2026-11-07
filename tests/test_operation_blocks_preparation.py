"""Source preparation must preserve exact region tokens, order and query identity."""

import gc
import weakref

import pytest
from test_operation_blocks import COMPLETE_HELPER, OPERATION, background, fitted, job

from dry_lint.functions import _function_node, node_tokens
from dry_lint.models import Declaration, LanguageAnalysis
from dry_lint.operation_blocks import _block, _representations

from conftest import function


@pytest.mark.parametrize(
    "body",
    [
        OPERATION,
        '    "doc"\n' + OPERATION,
        "    try:\n"
        + "".join("    " + line + "\n" for line in OPERATION.splitlines())
        + "    finally:\n        owner.release_packet(payload)\n",
        "    packet: Packet[UnusedType] = owner.decode_packet(payload)\n"
        "    packet.validate_packet(owner.schema)\n"
        "    packet.attach_receipt(owner.receipt)\n"
        "    return owner.encode_packet(packet)\n",
    ],
)
def test_region_token_sequence_matches_extractor_including_helper(body):
    source = job(body=body)
    original, helper = _representations(source)
    for block in [*original, *([helper] if helper else [])]:
        lines = source.code.splitlines()[block.line - source.line : block.end_line - source.line + 1]
        node = _function_node("def region():\n" + "\n".join(lines))
        assert node is not None
        node.name = ""
        assert block.tokens == node_tokens(node)


def test_region_span_and_node_bounds_remain_inclusive():
    # Four lines are necessary but not sufficient; node limits still apply.
    source = job()
    node = _function_node(source.code)
    assert node is not None
    statements = node.body
    original = _block(source, "straight_run", statements)
    assert original is not None
    for span, eligible in [(3, False), (4, True), (80, True), (81, False)]:
        statements[-1].end_lineno = statements[0].lineno + span - 1
        block = _block(source, "straight_run", statements)
        assert (block is not None) == eligible
        if block:
            assert block.tokens == original.tokens
    dense = job(body=OPERATION.replace("payload)", "[" + ",".join("payload" for _ in range(450)) + "])", 1))
    assert _representations(dense) == ([], None)


def test_cached_standalone_source_uses_current_tokens_and_native_target():
    target = function("copy.py", COMPLETE_HELPER)
    query = function("writer.py", COMPLETE_HELPER)
    comparer = fitted(target, count=400)
    initial = comparer.neighbours(query, 5, lambda f: True)
    assert initial and initial[0][0] is target
    # Source representations may be reused, but a query's full-token floor must
    # always see its current tokens, even when its source key is unchanged.
    query.tokens = ["unknown_token"]
    assert comparer.neighbours(query, 5, lambda f: True) == []
    assert comparer.similarity(query, target) == 0
    query.tokens = list(target.tokens)
    assert comparer.neighbours(query, 5, lambda f: True) == initial
    equivalent = query.model_copy(update={"path": "another.py", "name": "other"})
    assert comparer.neighbours(equivalent, 5, lambda f: True) == initial
    # Name-based self exclusion must not be cached with the source preparation.
    same_name = query.model_copy(update={"path": target.path, "name": target.name})
    assert comparer.neighbours(same_name, 5, lambda f: True) == []


@pytest.mark.parametrize(
    "update",
    [
        {"code": "def work():\n    pass"},
        {"line": 0},
        {"end_line": 0},
        {"path": "writer.ts"},
        {"analysis": LanguageAnalysis(language="typescript", version="1")},
        {"declaration": Declaration(kind="dataclass", fields={})},
    ],
)
def test_cached_standalone_source_invalidates_every_representation_input(update):
    target = function("copy.py", COMPLETE_HELPER)
    query = function("writer.py", COMPLETE_HELPER)
    comparer = fitted(target, count=400)
    assert comparer.neighbours(query, 1, lambda f: True)
    for field, value in update.items():
        setattr(query, field, value)
    assert comparer.neighbours(query, 1, lambda f: True) == []
    assert comparer.shared(query, target) == []


def test_fallback_preparation_does_not_poison_original_retained_anchors():
    # 65 helpers drop the anchor only in the fallback route. A straight region
    # must keep its original winner, including after standalone cache reuse.
    query = job("query.py")
    target = job("copy.py")
    helper_body = OPERATION.replace(
        "    packet.validate_packet(owner.schema)",
        "    try:\n        packet.validate_packet(owner.schema)\n    finally:\n        cleanup()",
    )
    helpers = [job(f"helper{i}.py", body=helper_body) for i in range(65)]
    comparer = fitted(target, *helpers, count=7000)
    first = comparer.neighbours(query, 1, lambda f: f is target)
    assert first and first[0][0] is target
    original = comparer._query_blocks(query)
    snapshot = [block.retained for block in original]
    comparer._query_blocks(query, fallback=True)
    assert [block.retained for block in original] == snapshot
    assert comparer.neighbours(query, 1, lambda f: f is target) == first
    comparer.index([target, *background(400)])
    fresh = fitted(target, count=400)
    assert comparer.neighbours(query, 1, lambda f: True) == fresh.neighbours(query, 1, lambda f: True)


@pytest.mark.parametrize("nodes, eligible", [(19, False), (20, True), (400, True), (401, False)])
def test_region_behaviour_node_floor_and_ceiling(nodes, eligible):
    argument = "42" if nodes == 19 else "payload"
    source = job(
        body=f"    unique_call({argument})\n    other_call()\n    record = owner.schema\n    return record"
        + "; pass" * max(0, nodes - 20)
    )
    blocks, helper = _representations(source)
    assert bool(blocks) == eligible
    assert helper is None


def test_source_cache_releases_previous_preparation_and_query_objects():
    target = job("copy.py")
    comparer = fitted(target)
    query = job("query.py")
    source_ref = weakref.ref(query)
    blocks = [weakref.ref(block) for block in comparer._query_blocks(query)]
    assert blocks
    comparer._query_blocks(query, fallback=True)
    del query
    gc.collect()
    assert source_ref() is None  # caching source text must not retain a Function
    comparer._query_blocks(job("next.py", body=OPERATION.replace("packet", "message")))
    gc.collect()
    assert all(ref() is None for ref in blocks)
    comparer.index([])
    assert comparer._query_key is None
    assert comparer._query_original == comparer._query_fallback == []
