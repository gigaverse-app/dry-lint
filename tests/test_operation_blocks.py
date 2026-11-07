"""Native parent retrieval, syntax boundaries and production discovery integration."""

import pytest

from dry_lint.detector import Detector
from dry_lint.models import Declaration, LanguageAnalysis
from dry_lint.operation_blocks import _blocks
from dry_lint.plugins import load
from dry_lint.settings import PluginChoice, Settings

from conftest import Repo, function

OPERATION = """\
    packet = owner.decode_packet(payload)
    packet.validate_packet(owner.schema)
    packet.attach_receipt(owner.receipt)
    return owner.encode_packet(packet)
"""


def job(path="a.py", name="deliver", body=OPERATION):
    return function(path, f"def {name}(owner, payload):\n{body}")


def background(count=20):
    return [job(f"noise{i}.py", f"noise{i}", f"    return unique_{i}(argument_{i})\n") for i in range(count)]


def fitted(*functions, count=20):
    comparer = load("comparers", PluginChoice(use="operation-blocks"))
    comparer.index([*functions, *background(count)])
    return comparer


def test_native_parents_scores_shared_operations_and_standalone_queries():
    target = job("b.py", "deliver_copy")
    query = job()
    comparer = fitted(target)
    near = comparer.neighbours(query, 1, allowed=lambda f: True)
    assert near[0][0] is target  # no fragment Function or copied/mutated evidence
    assert near[0][1] == pytest.approx(1)
    assert comparer.similarity(query, target) == near[0][1]
    assert "call:decode_packet" in comparer.shared(query, target)
    assert len(comparer.shared(query, target, limit=1)) == 1
    assert comparer.similarity_reusable is False
    assert comparer.name == "operation-blocks" and comparer.version == "1"
    assert comparer.neighbours(query, 0, allowed=lambda f: True) == []
    assert comparer.neighbours(query, 3, allowed=lambda f: False) == []
    # Querying must neither fit its tokens nor give it indexed position zero.
    assert comparer.tfidf.size == 21
    assert comparer.functions[0] is target
    assert comparer.neighbours(target, 3, allowed=lambda f: True) == []


def test_revised_same_qualname_uses_actual_query_and_reindex_clears_state():
    old = job()
    target = job("b.py")
    comparer = fitted(old, target)
    changed = job(body="    return unrelated_operation()\n")
    assert changed.qualname == old.qualname
    assert comparer.neighbours(changed, 3, allowed=lambda f: True) == []
    assert comparer.similarity(changed, target) == 0
    assert comparer.shared(changed, target) == []
    assert comparer.neighbours(old, 3, allowed=lambda f: True)[0][0] is target
    saved = old.model_copy()
    old.code = changed.code
    assert comparer.neighbours(old, 3, allowed=lambda f: True) == []
    old = saved
    comparer.index([])
    assert comparer.neighbours(old, 3, allowed=lambda f: True) == []
    assert not comparer._postings and not comparer._full_vectors
    comparer.index([old, target, *background()])
    assert comparer.neighbours(old, 1, allowed=lambda f: True)[0][0] is target


@pytest.mark.parametrize(
    "body",
    [
        "    logger.info(payload)\n    logger.debug(payload)\n    logger.warning(payload)\n    return logger.error(payload)\n",
        "    a = owner.decode_packet(payload)\n    b = owner.decode_packet(a)\n"
        "    c = owner.decode_packet(b)\n    return owner.decode_packet(c)\n",
        "    return owner.decode_packet(payload)\n",  # below the region size floor
    ],
)
def test_scaffolding_and_single_operation_controls_do_not_retrieve(body):
    query, target = job(body=body), job("b.py", body=body)
    comparer = fitted(query, target)
    assert comparer.neighbours(query, 3, allowed=lambda f: True) == []
    assert _blocks(query) == []


def test_parse_language_declaration_and_actual_span_boundaries():
    good = job()
    variants = [
        good.model_copy(update={"code": "def broken(:"}),
        good.model_copy(update={"code": "class Model: pass"}),
        good.model_copy(update={"path": "a.ts"}),
        good.model_copy(update={"analysis": LanguageAnalysis(language="typescript", version="1")}),
        good.model_copy(update={"declaration": Declaration(kind="dataclass", fields={"x": "str"})}),
        good.model_copy(update={"line": 0, "end_line": 0}),
        good.model_copy(update={"line": 5, "end_line": 4}),
    ]
    for query in variants:
        assert _blocks(query) == []
        assert fitted(good).neighbours(query, 3, allowed=lambda f: True) == []
        assert fitted(good).similarity(query, good) == 0
    # A native Python adapter can explicitly support a nonstandard path.
    assert _blocks(
        good.model_copy(update={"path": "source", "analysis": LanguageAnalysis(language="python", version="1")})
    )


def test_nested_owners_are_never_part_of_parent_regions():
    nested = "    if payload:\n        def inner():\n" + "\n".join("        " + line for line in OPERATION.splitlines())
    nested += "\n        class Local:\n            pass\n"
    parent = job(body=nested)
    assert _blocks(parent) == []
    # A real run after nested definitions is still in the outer owner.
    parent = job(body=nested + OPERATION)
    blocks = _blocks(parent)
    assert len(blocks) == 1 and blocks[0].kind == "straight_run"
    assert blocks[0].line > 8
    assert fitted(parent, job("b.py")).neighbours(parent, 1, allowed=lambda f: True)


def test_compound_suites_async_handlers_and_match_are_scoped():
    body = "    try:\n" + "".join("    " + line + "\n" for line in OPERATION.splitlines())
    body += "    except ValueError:\n" + "".join("    " + line + "\n" for line in OPERATION.splitlines())
    body += "    finally:\n        owner.close()\n"
    blocks = _blocks(job(body=body))
    assert {block.kind for block in blocks} == {"Try", "straight_run"}
    assert len(blocks) == 3
    match = "    match payload:\n        case {'value': value}:\n"
    match += "".join("        " + line + "\n" for line in OPERATION.splitlines())
    assert {block.kind for block in _blocks(job(body=match))} == {"Match", "straight_run"}
    async_job = function(
        "async.py",
        "async def work(owner, payload):\n    async with owner.session():\n"
        + "".join(
            "    " + line.replace("owner.decode_packet", "await owner.decode_packet") + "\n"
            for line in OPERATION.splitlines()
        ),
    )
    assert {block.kind for block in _blocks(async_job)} == {"AsyncWith", "straight_run"}


def test_oversized_runs_are_not_windowed_and_parent_regions_are_capped():
    assert _blocks(job(body=OPERATION.replace("return ", "result = ") * 21)) == []
    body = (OPERATION.replace("return ", "result = ") + '    "boundary"\n') * 13
    blocks = _blocks(job(body=body))
    assert len(blocks) == 12
    assert all(block.kind == "straight_run" and block.end_line - block.line == 3 for block in blocks)


def test_full_function_and_region_cosine_floors_are_independent():
    target = job("b.py")
    padding = "".join(f"    noise_{i} = task_{i}(argument_{i})\n" for i in range(500))
    query = job(body=padding + '    "boundary"\n' + OPERATION)
    comparer = fitted(query, target)
    assert comparer._best(comparer._query_blocks(query), comparer._query_blocks(target))[0] == pytest.approx(1)
    assert comparer.similarity(query, target) == 0  # full-function cosine below .1
    assert comparer.neighbours(query, 3, allowed=lambda f: True) == []

    padding = "".join(f"    noise_{i} = unrelated_{i} + distinct_{i}\n" for i in range(18))
    query = job(body=padding + OPERATION)
    comparer = fitted(query, target)
    score = comparer._best(comparer._query_blocks(query), comparer._query_blocks(target))[0]
    assert 0.1 < score < 0.65
    assert comparer.similarity(query, target) == 0  # region cosine below .65
    assert comparer.neighbours(query, 3, allowed=lambda f: True) == []


def test_two_distinct_shared_calls_are_required_even_with_shared_attributes():
    query = job()
    target = job(
        "b.py",
        body=OPERATION.replace("validate_packet", "check_result")
        .replace("attach_receipt", "bind_result")
        .replace("encode_packet", "serialize_result"),
    )
    comparer = fitted(query, target)
    left, right = comparer._query_blocks(query)[0], comparer._query_blocks(target)[0]
    assert len(left.operations & right.operations) >= 3
    assert len(left.calls & right.calls) == 1
    assert left.retained & right.retained
    assert comparer.neighbours(query, 3, allowed=lambda f: True) == []


def test_duplicate_parent_dedup_allowed_filter_and_deterministic_ties():
    query, first, second = job(), job("b.py"), job("c.py")
    duplicate = first.model_copy()
    comparer = fitted(query, second, first, duplicate, count=400)
    assert [f.path for f, _ in comparer.neighbours(query, 10, allowed=lambda f: True)] == ["b.py", "c.py"]
    assert comparer.neighbours(query, 1, allowed=lambda f: f.path == "c.py")[0][0] is second
    assert comparer.neighbours(query, 1, allowed=lambda f: True)[0][0] is first
    comparer.index([first, second, query, duplicate, *background(400)])
    assert [f.path for f, _ in comparer.neighbours(query, 10, allowed=lambda f: True)] == ["b.py", "c.py"]


def test_anchor_postings_and_parent_pool_bounds():
    # Many eligible regions in a few parents must drop a common posting entirely,
    # rather than truncate it and bias results toward the first indexed functions.
    body = (OPERATION.replace("return ", "result = ") + '    "boundary"\n') * 12
    repeated = [job(f"r{i}.py", body=body) for i in range(6)]
    comparer = fitted(*repeated, count=600)
    assert not comparer._postings
    assert comparer.neighbours(repeated[0], 3, allowed=lambda f: True) == []
    bodies = [OPERATION.replace("packet", f"packet_{i}").replace("return ", "result = ") for i in range(12)]
    query = job(body='    "boundary"\n'.join(bodies))
    targets = [job(f"target{i:02}_{j}.py", body=body) for i, body in enumerate(bodies) for j in range(6)]
    comparer = fitted(query, *targets, count=750)
    assert len(comparer._pool(query, comparer._query_blocks(query))) == 64
    assert all(len(block.anchors) <= 8 for blocks in comparer._parents for block in blocks)
    assert all(len(posting) <= 64 for posting in comparer._postings.values())
    assert len(comparer.neighbours(query, 100, allowed=lambda f: True)) == 64


def test_detector_discovery_keeps_baseline_and_fills_one_unseen_native_pair(tmp_path):
    repo = Repo(tmp_path / "operations")
    for i in range(4):
        repo.write(
            f"copy{i}.py", f'def deliver_{i}(owner, payload):\n    """Full native documentation."""\n' + OPERATION
        )
    repo.write("noise.py", "\n".join(f.code + "\n" for f in background(500)))
    repo.commit()
    settings = Settings(exclude=[])
    original = Detector.for_repository(repo.root, settings)
    changed = next(f for f in original.functions if f.path == "copy0.py")
    baseline = original.candidates([changed])
    assert len([c for c in baseline if c.lane == "baseline"]) == 3
    settings = Settings.model_validate(
        {
            **settings.model_dump(),
            "discovery": {
                "enabled": True,
                "comparers": [{"use": "operation-blocks", "neighbours": 1}],
            },
        }
    )
    # Add a fifth parent after the baseline has already filled its three slots.
    repo.write("copy4.py", 'def deliver_4(owner, payload):\n    """Keep signature and documentation."""\n' + OPERATION)
    repo.commit()
    detector = Detector.for_repository(repo.root, settings)
    baseline_detector = Detector.for_repository(repo.root, Settings(exclude=[]))
    changed = next(f for f in detector.functions if f.path == "copy0.py")
    baseline = baseline_detector.candidates([changed])
    candidates = detector.candidates([changed])
    assert [c for c in candidates if c.lane == "baseline"] == [c for c in baseline if c.lane == "baseline"]
    extra = [c for c in candidates if c.lane == "exploration"]
    assert len(extra) == 1
    assert extra[0].comparer == "operation-blocks:1" and not extra[0].similarity_reusable
    assert extra[0].new.code == changed.code and "Full native documentation" in extra[0].new.code
    assert extra[0].existing.code.startswith("def deliver_")
    assert len({c.key for c in candidates}) == len(candidates)
    # Explicit TF-IDF-20 stays before the block route; it already owns this pair.
    settings.discovery.comparers.insert(
        0,
        settings.discovery.comparers[0].model_validate(
            {"use": "tfidf", "min_similarity": 0.35, "min_similarity_small": 0.35, "neighbours": 20}
        ),
    )
    detector = Detector.for_repository(repo.root, settings)
    assert all(c.comparer.startswith("tfidf:") for c in detector.candidates([changed]))


@pytest.mark.parametrize("settlement", ["ignore", "discard"])
def test_detector_skips_settled_unseen_pairs_before_the_block_cap(tmp_path, settlement):
    repo = Repo(tmp_path / "settled")
    for name in ("a", "b", "c", "d"):
        suffix = "    # dry-lint: ignore\n" if name == "c" and settlement == "ignore" else ""
        repo.write(f"{name}.py", f"def deliver(owner, payload):\n{suffix}" + OPERATION)
    repo.write("noise.py", "\n".join(f.code + "\n" for f in background(400)))
    repo.commit()
    settings = Settings(
        exclude=[],
        neighbours=1,
        policies=[
            {
                "name": "separate-owner",
                "reason": "intentional separation",
                "action": "discard",
                "left": {"paths": ["a.py"]},
                "right": {"paths": ["c.py"]},
            }
        ]
        if settlement == "discard"
        else [],
        discovery={
            "enabled": True,
            "comparers": [{"use": "operation-blocks", "neighbours": 1}],
        },
    )
    detector = Detector.for_repository(repo.root, settings)
    query = next(f for f in detector.functions if f.path == "a.py")
    pairs = detector.candidates([query])
    assert [(c.existing.path, c.lane) for c in pairs if c.lane != "relative"] == [
        ("b.py", "baseline"),
        ("d.py", "exploration"),
    ]
