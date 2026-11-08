"""Family retrieval invariants through real native extraction, without judges."""

import json
import textwrap

import pytest
from pydantic import ValidationError

from dry_lint.extractors import PythonExtractor
from dry_lint.models import Declaration, LanguageAnalysis, Run
from dry_lint.operation_families import FamilyBatch, FamilyLimits, PythonOperationFamilies

OPERATION = """\
    decoded = codec.decode(payload)
    decoded.validate("strict")
    return codec.encode(decoded)
"""
GUARD = """\
    if value is not None and value < 0:
        raise ValueError("negative")
"""


def owners(body=OPERATION, count=3, *, prefix="job", signature="codec, payload"):
    """Native functions in distinct files, with source unrelated to nomination internals."""
    extractor = PythonExtractor(min_lines=1)
    return [extractor.functions(f"{prefix}{i}.py", f"def {prefix}{i}({signature}):\n{body}")[0] for i in range(count)]


def nominate(functions, **limits):
    return PythonOperationFamilies(FamilyLimits(**limits)).nominate(functions)


def test_three_full_owners_one_unconfirmed_family_roundtrip_and_benefit():
    functions = owners('    """Complete native documentation."""\n' + OPERATION)
    functions[0].origin = Run(repository="org/repo", head="commit")
    functions[0].context = "# caller policy stays here"
    batch = nominate(functions)
    assert len(batch.nominations) == 1
    family = batch.nominations[0]
    assert family.status == "unconfirmed"
    assert len(family.owners) == 3
    assert family.benefit.model_dump() == {
        "repeated_statements": 9,
        "replacement_statements": 3,
        "shared_statements": 3,
        "shared_owner_overhead": 1,
        "removable_statements": 2,
    }
    assert {member.function.code for member in family.owners} == {function.code for function in functions}
    assert all(len(member.regions) == 1 for member in family.owners)
    assert len({member.source_id for member in family.owners}) == 3
    assert FamilyBatch.model_validate_json(batch.model_dump_json()).model_dump() == batch.model_dump()
    assert json.loads(batch.model_dump_json())["schema"] == 1
    with pytest.raises(ValidationError):
        type(family).model_validate({**family.model_dump(), "status": "confirmed"})
    functions[0].code = "mutated input after nomination"
    assert all(member.function.code != functions[0].code for member in family.owners)


def test_alpha_renaming_keeps_references_and_changes_source_not_operation_identity():
    functions = owners()
    renamed = owners(OPERATION.replace("decoded", "parsed").replace("payload", "packet"), signature="codec, packet")
    before, after = nominate(functions).nominations[0], nominate(renamed).nominations[0]
    assert before.operation_id == after.operation_id
    assert before.nomination_id != after.nomination_id
    assert "parsed" in after.owners[0].regions[0].bindings.values()
    reordered = nominate(list(reversed(functions)))
    assert reordered.model_dump() == nominate(functions).model_dump()


@pytest.mark.parametrize(
    "changed",
    [
        OPERATION.replace('"strict"', '"relaxed"'),
        OPERATION.replace("codec.encode(decoded)", "codec.encode(payload)"),
        OPERATION.replace(".validate", ".invalidate"),
        OPERATION.replace("codec.decode(payload)", "codec.decode(payload + 1)"),
    ],
)
def test_literals_calls_operators_and_binding_relationships_are_not_erased(changed):
    functions = owners()[:2] + owners(changed, count=1, prefix="variant")
    assert not nominate(functions).nominations


@pytest.mark.parametrize("before,after", [("< 0", "<= 0"), ("< 0", "< 1"), ("< 0", "< False"), ("and", "or")])
def test_exact_guard_identity_preserves_control_operator_and_literal_types(before, after):
    positive = owners(GUARD, count=4, signature="value")
    negative = owners(GUARD.replace(before, after), count=4, prefix="other", signature="value")
    families = nominate(positive + negative).nominations
    assert len(families) == 2
    assert {frozenset(member.owner_id for member in family.owners) for family in families} == {
        frozenset(function.qualname for function in group) for group in (positive, negative)
    }


def test_disconnected_pairs_and_transitive_chains_never_make_three_owners():
    # A/B share decode, B/C share load, C/D share upload. No shared operation
    # has three owners, even though the pair graph is connected.
    operations = [
        OPERATION.replace("return codec.encode(decoded)", "codec.encode(decoded)"),
        OPERATION.replace("codec", "database")
        .replace("decode", "load")
        .replace("encode", "save")
        .replace("return ", ""),
        OPERATION.replace("codec", "remote")
        .replace("decode", "upload")
        .replace("encode", "close")
        .replace("return ", ""),
    ]
    functions = []
    for i, indexes in enumerate(((0,), (0, 1), (1, 2), (2,))):
        # A compound boundary preserves independently complete operations.
        body = "".join(f"    if flag{index}:\n" + textwrap.indent(operations[index], "    ") for index in indexes)
        functions += owners(
            body, count=1, prefix=f"chain{i}", signature="codec, database, remote, payload, flag0, flag1, flag2"
        )
    assert not nominate(functions).nominations
    assert not nominate(
        owners(count=2) + owners(OPERATION.replace("decode", "load"), count=2, prefix="disconnected")
    ).nominations


@pytest.mark.parametrize(
    "body",
    [
        "    return shared(payload)\n",
        "    return await shared(payload)\n",
        "    answer = shared(payload)\n    return answer\n",
        "    answer = await shared(payload)\n    return answer\n",
    ],
)
def test_shared_helper_delegates_do_not_count_as_implementation_owners(body):
    assert not nominate(owners(body, count=8)).nominations


def test_helper_implementation_keeps_callers_but_not_delegate_owners():
    source = "def shared(codec, payload):\n" + OPERATION
    source += "\ndef caller(codec, payload):\n    return shared(codec, payload)\n"
    functions = PythonExtractor().functions("helpers.py", source) + owners(count=2)
    family = nominate(functions).nominations[0]
    helper = next(member for member in family.owners if member.function.name == "shared")
    assert helper.local_callers == ["helpers.py::caller"]
    assert all(member.function.name != "caller" for member in family.owners)


def test_tail_deep_suites_and_exception_context_are_retained():
    body = "    marker = 1\n" * 150
    body += "    try:\n" + "        if enabled:\n" + "            while waiting:\n" + "                if ready:\n"
    body += "                    if proceed:\n" + textwrap.indent(OPERATION, "                    ")
    body += "    finally:\n        cleanup()\n"
    functions = owners(body, signature="codec, payload, enabled, waiting, ready, proceed")
    # Force oversized containing compounds out; complete child runs survive.
    batch = nominate(functions, max_region_nodes=27)
    family = next(f for f in batch.nominations if ".decode" in f.owners[0].regions[0].code)
    region = family.owners[0].regions[0]
    assert region.span.line > 150
    assert len(region.enclosing) == 5
    assert "finally:" in family.owners[0].function.code


def test_overlapping_compound_and_inner_regions_have_one_source_owner():
    functions = owners("    if enabled:\n" + textwrap.indent(OPERATION, "    "), signature="codec, payload, enabled")
    families = nominate(functions).nominations
    assert len(families) == 1
    assert families[0].owners[0].regions[0].kind == "If"
    assert families[0].benefit.repeated_statements == 12
    assert nominate(functions).stats.skipped["overlap_owner_floor"] == 1


def test_repeated_sites_count_once_each_but_do_not_manufacture_owners():
    body = GUARD + "    other_work()\n" + GUARD
    functions = owners(body, count=3, signature="value")
    family = nominate(functions).nominations[0]
    assert len(family.owners) == 3
    assert all(len(owner.regions) == 2 for owner in family.owners)
    assert family.benefit.repeated_statements == 12
    assert not nominate(functions[:1] * 8).nominations


def test_parser_byte_columns_decorators_multiline_methods_and_semicolons():
    source = '''\
class Container:
    @decorate("é")
    def work(self, codec, payload):
        """Line one.
        Documentation two.
        """
        decoded = codec.decode(payload); decoded.validate("é")
        return codec.encode(decoded)
'''
    functions = [PythonExtractor().functions(f"module{i}.py", source)[0] for i in range(3)]
    region = nominate(functions).nominations[0].owners[0].regions[0]
    assert region.span.line == 7 and region.span.end_line == 8
    assert region.span.column == 8
    assert region.code == 'decoded = codec.decode(payload); decoded.validate("é")\n        return codec.encode(decoded)'
    assert region.span.end_column == len(b"        return codec.encode(decoded)")
    # Two compounds on a physical line are syntactically impossible; a straight
    # semicolon run remains complete, with exact byte rather than character offsets.
    functions = owners('    first = "é"; second = first + "x"; return second\n')
    region = nominate(functions).nominations[0].owners[0].regions[0]
    assert region.span.end_column == len('    first = "é"; second = first + "x"; return second'.encode())


def test_imports_globals_nonlocals_and_nested_binding_scopes_are_conservative():
    base = owners()
    # codec is a parameter in base, but a global in the new version.
    global_ = owners(OPERATION, prefix="global", signature="payload")
    assert nominate(base).nominations[0].operation_id != nominate(global_).nominations[0].operation_id
    imported = owners("    import library as codec\n" + OPERATION, signature="payload")
    other = owners("    import other_library as codec\n" + OPERATION, signature="payload")
    assert nominate(imported).nominations[0].operation_id != nominate(other).nominations[0].operation_id
    nested = owners("    def hidden():\n" + textwrap.indent(OPERATION, "    ") + "    return hidden()\n")
    assert not nominate(nested).nominations
    comprehensions = owners("    decoded = [payload for payload in values]\n    decoded.sort()\n    return decoded\n")
    assert not nominate(comprehensions).nominations


def test_exception_and_pattern_capture_binding_relationships():
    body = """\
    try:
        consume(payload)
    except ValueError as error:
        annotate(error)
        raise error
"""
    first = nominate(owners(body)).nominations[0]
    renamed = nominate(owners(body.replace("error", "failure"))).nominations[0]
    assert first.operation_id == renamed.operation_id
    pattern = """\
    match payload:
        case {"value": value, **rest}:
            consume(value)
            consume(rest)
            return value
"""
    assert (
        nominate(owners(pattern)).nominations[0].operation_id
        == nominate(
            owners(
                pattern.replace("value,", "item,")
                .replace("consume(value)", "consume(item)")
                .replace("return value", "return item")
            )
        )
        .nominations[0]
        .operation_id
    )


def test_source_identity_changes_with_docs_context_origin_and_location_only():
    before = owners()
    after = [f.model_copy(update={"context": "changed contract", "origin": Run(head="new")}) for f in before]
    left, right = nominate(before).nominations[0], nominate(after).nominations[0]
    assert left.operation_id == right.operation_id
    assert left.nomination_id != right.nomination_id
    for function in after:
        function.line += 20
        function.end_line += 20
    assert nominate(after).nominations[0].nomination_id != right.nomination_id


@pytest.mark.parametrize(
    "limit,value,reason",
    [
        ("max_function_bytes", 1, "function_bytes"),
        ("max_source_bytes", 1, "source_bytes"),
        ("max_function_nodes", 1, "function_nodes"),
        ("max_region_nodes", 1, "region_nodes"),
        ("max_region_bytes", 1, "region_bytes"),
        ("max_output_source_bytes", 1, "output_source_bytes"),
        ("max_functions", 2, "function_limit"),
        ("max_regions", 1, "region_limit_functions"),
    ],
)
def test_limits_fail_closed_without_truncated_evidence(limit, value, reason):
    batch = nominate(owners(), **{limit: value})
    assert not batch.nominations
    assert batch.stats.skipped[reason] > 0


def test_owner_cap_drops_entire_overfull_family_and_candidate_caps_are_deterministic():
    assert not nominate(owners(count=4), max_owners=3).nominations
    first = owners()
    second = owners(OPERATION.replace("decode", "unpack"), prefix="second")
    functions = first + second
    batch = nominate(functions, max_candidates=1)
    assert len(batch.nominations) == 1
    assert batch.stats.skipped["candidate_limit"] == 1
    assert batch.model_dump() == nominate(list(reversed(functions)), max_candidates=1).model_dump()
    batch = nominate(functions, max_operation_ids=1)
    assert len(batch.nominations) == 1
    assert batch.stats.skipped["operation_id_limit"] == 3


def test_ambiguous_and_invalid_native_sources_are_not_silently_accepted():
    functions = owners()
    conflict = functions[0].model_copy(update={"code": functions[0].code.replace("decode", "unpack")})
    assert not nominate(functions + [conflict]).nominations
    for changed in (
        {"line": 0},
        {"end_line": 999},
        {"name": "different"},
        {"code": "invalid Python\n" * 4},
        {"analysis": LanguageAnalysis(language="typescript", version="1")},
        {"declaration": Declaration(kind="dataclass", fields={})},
    ):
        batch = nominate([f.model_copy(update=changed) for f in functions])
        assert not batch.nominations
        assert batch.stats.skipped


def test_nonpositive_small_operations_are_not_ranked_as_savings():
    batch = nominate(owners(GUARD, signature="value"))
    assert not batch.nominations
    assert batch.stats.skipped["nonpositive_benefit"] >= 1


def test_per_owner_region_site_and_caller_limits_keep_complete_source():
    body = GUARD + "    do_work()\n" + GUARD
    batch = nominate(owners(body, count=4, signature="value"), max_sites_per_owner=1)
    assert all(len(member.regions) == 1 for member in batch.nominations[0].owners)
    assert batch.stats.skipped["sites_per_owner"] == 4
    batch = nominate(owners(body, count=4, signature="value"), max_regions_per_function=1)
    assert batch.stats.skipped["regions_per_function"] > 0
    batch = nominate(owners(body, count=4, signature="value"), max_regions=1)
    assert batch.stats.skipped["region_limit"] == 1
    batch = nominate(owners(count=5), max_owners=3)
    assert batch.stats.skipped["overfull_family_sites"] == 1
    source = "def shared(codec, payload):\n" + OPERATION
    source += "".join(f"\ndef caller{i}(codec, payload):\n    return shared(codec, payload)\n" for i in range(3))
    batch = nominate(PythonExtractor().functions("module.py", source) + owners(count=2), max_callers=1)
    member = next(member for member in batch.nominations[0].owners if member.function.name == "shared")
    assert member.local_callers == ["module.py::caller0"]
    assert batch.stats.skipped["callers"] == 2


def test_overlap_recomputes_positive_benefit_after_source_allocation():
    # Three owners contain a much larger enclosing operation; three additional
    # owners contain only the guard. Allocating the enclosing region leaves a
    # three-owner two-statement guard with zero net statement savings.
    inside = "    if enabled:\n" + textwrap.indent(GUARD + OPERATION, "    ")
    functions = owners(inside, signature="value, enabled, codec, payload")
    functions += owners(GUARD, prefix="guard", signature="value")
    batch = nominate(functions)
    assert batch.stats.skipped["overlap_benefit_floor"] == 1
    assert len(batch.nominations) == 1


def test_nonexecutable_compound_and_invalid_symbol_table_do_not_nominate():
    batch = nominate(owners('    if True:\n        "only documentation"\n'))
    assert batch.stats.skipped["single_statement"] == 3
    # ast.parse permits this, the symbol table correctly rejects conflicting scope.
    body = "    value = 1\n    global value\n    return value\n"
    batch = nominate(owners(body))
    assert batch.stats.skipped["parse_unavailable"] == 3


def test_aliases_at_one_physical_source_site_are_not_independent_owners():
    native = owners(count=1)[0]
    aliases = [native.model_copy(update={"owner": f"Alias{i}"}) for i in range(3)]
    assert not nominate(aliases).nominations


def test_changed_filter_precedes_ranking_caps_and_keeps_full_owner_background():
    small = owners()
    large = owners(OPERATION.replace("    return", "    decoded.freeze()\n    return"), count=8, prefix="large")
    generator = PythonOperationFamilies(FamilyLimits(max_candidates=1))
    assert generator.nominate(small + large).nominations[0].owners[0].owner_id.startswith("large")
    batch = generator.nominate(small + large, changed={small[0].qualname})
    assert len(batch.nominations) == 1
    assert {owner.owner_id for owner in batch.nominations[0].owners} == {f.qualname for f in small}
    assert batch.stats.scanned_functions == len(small + large)
    assert batch.stats.skipped["unchanged_families"] == 1
    assert not generator.nominate(small + large, changed=set()).nominations
    assert not generator.nominate(small + large, changed={"missing.py::owner"}).nominations


def test_changed_filter_precedes_overlapping_unrelated_family_allocation():
    inner = "    if inner:\n" + textwrap.indent(OPERATION, "    ")
    outer = "    if outer:\n" + textwrap.indent(inner, "    ")
    outer += "        extra = 1\n        record(extra)\n        commit(extra)\n"
    large = owners(outer, signature="codec, payload, inner, outer")
    changed = owners(inner, count=1, prefix="changed", signature="codec, payload, inner")
    batch = PythonOperationFamilies().nominate(large + changed, changed={changed[0].qualname})
    assert len(batch.nominations) == 1
    assert len(batch.nominations[0].owners) == 4
    assert all(owner.regions[0].kind == "If" for owner in batch.nominations[0].owners)
    assert batch.stats.skipped["unchanged_families"] >= 1


def test_root_pin_is_preserved_and_mixed_repository_revisions_rejected_before_caps():
    functions = owners()
    run = Run(repository="org/repo", head="one")
    batch = PythonOperationFamilies().nominate(functions, run=run, changed={functions[0].qualname})
    assert batch.run == run
    assert all(owner.function.origin == run for owner in batch.nominations[0].owners)
    assert all(owner.owner_id.startswith("org/repo/") for owner in batch.nominations[0].owners)
    changed = [f.model_copy(update={"origin": Run(repository="org/repo", head="two")}) for f in functions]
    with pytest.raises(ValueError, match="mixed source revisions"):
        PythonOperationFamilies(FamilyLimits(max_functions=1)).nominate(changed, run=run, changed=set())
    with pytest.raises(ValueError, match="mixed source revisions"):
        nominate([functions[0].model_copy(update={"origin": run}), *changed])
    peers = owners(prefix="peer")
    peers = [f.model_copy(update={"origin": Run(repository="org/peer", head="two")}) for f in peers]
    assert PythonOperationFamilies().nominate(functions + peers, run=run).nominations


def test_changed_owner_must_survive_source_dedup_and_overlap_allocation():
    native = owners(count=1)[0]
    aliases = [native.model_copy(update={"owner": f"Alias{i}"}) for i in range(2)]
    batch = PythonOperationFamilies().nominate(aliases + owners(prefix="peer", count=2), changed={aliases[1].qualname})
    assert not batch.nominations
    assert batch.stats.skipped["unchanged_after_source_dedup"] == 1

    inner = "    if inner:\n" + textwrap.indent(OPERATION, "    ")
    outer = "    if outer:\n" + textwrap.indent(inner, "    ")
    outer += "        extra = 1\n        record(extra)\n        commit(extra)\n"
    outer += "        record(extra)\n" * 10
    large = owners(outer, signature="codec, payload, inner, outer")
    small = owners(inner, prefix="small", signature="codec, payload, inner")
    batch = PythonOperationFamilies().nominate(large + small, changed={large[0].qualname})
    assert len(batch.nominations) == 1
    assert batch.stats.skipped["unchanged_after_overlap"] > 0
    assert all(any(member.owner_id == large[0].qualname for member in family.owners) for family in batch.nominations)


GUARD_EXIT = """\
    prepare(value)
    if value.missing:
        notify(value, strict=True)
        return Default.VALUE
"""
CONTINUE_GUARD = """\
    for item in items:
        if item.key in REGISTRY.seen:
            REGISTRY.skip(item)
            continue
        handle{index}(item)
"""
RETURNING_BRANCH = """\
    for v in values:
        if v.ready:
            notify(v, strict=True)
            return v.result
        else:
            return Default.VALUE
    record(values)
"""


def test_a_return_that_ends_the_function_is_one_call_but_mid_function_keeps_its_condition():
    tail = nominate(owners(GUARD_EXIT, signature="value")).nominations
    assert [family.owners[0].regions[0].replacement_statements for family in tail] == [1]
    # A helper cannot return from its caller: each site would keep `if helper(value): return ...`.
    middle = nominate(owners(GUARD_EXIT + "    record(value)\n", signature="value"))
    assert not middle.nominations
    assert middle.stats.skipped["nonpositive_benefit"] >= 1


def test_a_continue_that_leaves_the_region_keeps_its_condition():
    functions = [
        owners(CONTINUE_GUARD.format(index=i), count=1, prefix=f"job{i}", signature="items")[0] for i in range(3)
    ]
    batch = nominate(functions)
    assert not batch.nominations
    assert batch.stats.skipped["nonpositive_benefit"] >= 1


def test_a_branch_that_returns_on_every_path_is_one_call_inside_a_loop():
    family = nominate(owners(RETURNING_BRANCH, signature="values")).nominations[0]
    region = family.owners[0].regions[0]
    assert region.kind == "If" and region.replacement_statements == 1


def test_a_region_naming_only_its_own_locals_is_not_a_shared_operation():
    idiom = "    if item:\n        items.append(item)\n    finish(item, items)\n"
    batch = nominate(owners(idiom, count=6, signature="item, items"))
    assert not batch.nominations
    assert batch.stats.skipped["local_only_idiom"] >= 6
