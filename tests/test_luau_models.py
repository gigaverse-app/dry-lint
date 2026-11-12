"""Luau records use the existing model pipeline, without executing or inferring repository code."""

import pytest

from dry_lint.cli import main
from dry_lint.detector import Detector
from dry_lint.function_index import FunctionIndex, build_index, extraction_contract
from dry_lint.luau_models import LuauModelExtractor
from dry_lint.model_review import profile
from dry_lint.models import Candidate, CandidatesFile, Verdict
from dry_lint.plugins import load
from dry_lint.report import Report
from dry_lint.settings import PluginChoice, Settings

from conftest import Repo

pytest.importorskip("tree_sitter_luau")

RECORDS = """-- A wire record; ownership still needs review.
export type Receipt<T> = {
    receiptId: string,
    amount: number,
    metadata: { currency: string },
    callback: (T) -> boolean,
    [string]: unknown,
}
type Copy = { receiptId: string, amount: number, metadata: { currency: string } }
type Paid = Receipt<string> & { paidAt: number }
local Receipt = { receiptId = "example", amount = 0, metadata = { currency = "USD" } }
"""


@pytest.fixture
def extractor() -> LuauModelExtractor:
    return load("extractors", PluginChoice(use="luau-models"))


def test_records_flow_through_same_file_retrieval_and_wire_formats(tmp_path, extractor):
    repo = Repo(tmp_path / "luau-models")
    repo.write("models.luau", RECORDS)
    repo.commit()
    settings = Settings(extractors=["luau-models"], comparer="model-shape")
    detector = Detector.for_repository(repo.root, settings, strict=True)
    assert [f.qualname for f in detector.functions] == [
        "models.luau::<type>.Receipt",
        "models.luau::<type>.Copy",
        "models.luau::<type>.Paid",
        "models.luau::<table>.Receipt",
    ]
    pairs = detector.candidates(detector.functions)
    assert len(pairs) == 3
    assert all(p.similarity == 1 and p.filtered is None for p in pairs)
    restored = CandidatesFile.model_validate_json(CandidatesFile(candidates=pairs).model_dump_json())
    assert restored.schema_version == 19
    assert restored.candidates[0].new.declaration.kind == "luau"
    assert restored.candidates[0].new.declaration.fields == {
        "receiptId": "string",
        "amount": "number",
        "metadata": "{ currency: string }",
    }
    index = build_index({"models.luau": RECORDS.encode()}, "org/roblox", "a" * 40, settings)
    assert index.schema_version == 4
    loaded = FunctionIndex.decode(index.encode(), index.repository, index.commit, extraction_contract(settings))
    assert [f.declaration for f in loaded.extracted()] == [f.declaration for f in detector.functions]
    assert detector.functions[0].code.startswith("-- A wire record")
    assert detector.functions[0].line == 1 and detector.functions[0].end_line == 8


def test_only_explicit_data_fields_contribute(extractor):
    source = """type Alias = Receipt
type Derived = typeof(factory())
type Union = {left: string} | {right: number}
type Array = {Receipt}
type Index = {[string]: number}
type Wrapped = ({id: string, payload: {nested: boolean}})
type Extended = Base & {id: string} & {payload: number}
type Quoted = {["user-id"]: string, ['payload']: number, callback: ((x: string)->boolean)?}
local Config = {
    id = "a", ["user-id"] = 3, payload = {nested = true},
    [dynamic] = true, [4] = "array", "item", __index = Base,
    run = function() return 1 end,
}
local Made = setmetatable({id = 1, payload = 2}, Class)
local Clone = table.clone(Config)
local Imported = require(script.Parent.Models)
local Empty = {}
local function factory()
    local Inner = {id = 1, payload = 2}
    return Inner
end
function Nested . Factory.make() end
"""
    found = {f.qualname: f for f in extractor.functions("models.lua", source)}
    assert set(found) == {
        "models.lua::<type>.Wrapped",
        "models.lua::<type>.Extended",
        "models.lua::<type>.Quoted",
        "models.lua::<table>.Config",
    }
    assert found["models.lua::<type>.Quoted"].declaration.fields == {"user-id": "string", "payload": "number"}
    assert found["models.lua::<type>.Wrapped"].declaration.fields == {"id": "string", "payload": "{nested: boolean}"}
    assert found["models.lua::<type>.Extended"].declaration.fields == {"id": "string", "payload": "number"}
    assert found["models.lua::<table>.Config"].declaration.fields == {
        "id": '"a"',
        "user-id": "3",
        "payload": "{nested = true}",
    }


def test_typed_multiple_assignments_and_module_records_keep_identities(extractor):
    source = """local First: Record, Second: Record = {id = 1, value = 2}, {id = 3, value = 4}
Module.Options = {id = 5, value = 6}
items[1] = {id = 7, value = 8}
"""
    found = extractor.functions("models.luau", source)
    assert [f.qualname for f in found] == [
        "models.luau::<table>.First",
        "models.luau::<table>.Second",
        "models.luau::<table>.Module.Options",
    ]
    assert [f.declaration.fields["id"] for f in found] == ["1", "3", "5"]


def test_wrapped_literals_and_intersections_keep_only_known_data(extractor):
    source = r"""type Narrowed = {id: string, value: string} & {value: "a" | "b"}
local Config = ({id = 1, value = 2, callback = false,
    callback = (function() end), ["escaped\nkey"] = 3,
    -- comment between members
    [`dynamic{suffix}`] = 4,
} :: ConfigType)
"""
    narrowed, config = extractor.functions("models.luau", source)
    assert narrowed.declaration.fields == {"id": "string", "value": '(string) & ("a" | "b")'}
    assert config.declaration.fields == {"id": "1", "value": "2"}
    edited = extractor.functions("models.luau", source.replace("ConfigType", "OtherType"))[1]
    assert extractor.structure_hash(config) != extractor.structure_hash(edited)


def test_qualified_type_declarations_do_not_invent_local_aliases(extractor):
    # The parser accepts a field_type name, but it does not establish a local model binding.
    assert extractor.functions("models.luau", "type Types.Receipt = {id: string, amount: number}") == []


@pytest.mark.parametrize("schema", [1, 2])
def test_existing_model_indexes_and_candidates_remain_readable(schema):
    settings = Settings(extractors=["python-models"])
    index = build_index(
        {"models.py": b"from dataclasses import dataclass\n@dataclass\nclass Record:\n    id: str\n    value: int\n"},
        "org/models",
        "b" * 40,
        settings,
    )
    index.schema_version = schema
    loaded = FunctionIndex.decode(index.encode(), index.repository, index.commit, index.contract)
    assert loaded.functions[0].declaration.kind == "dataclass"
    pair = Candidate(new=loaded.functions[0], existing=loaded.functions[0], similarity=1)
    legacy = CandidatesFile(candidates=[pair]).model_dump(mode="json", by_alias=True)
    legacy["schema"] = 17
    assert CandidatesFile.model_validate(legacy).candidates[0].new.declaration.kind == "dataclass"


@pytest.mark.parametrize(
    "before, after",
    [
        ("amount: number", "amount: string"),
        ("receiptId: string", "receiptId: string?"),
        ("currency: string", 'currency: "USD"'),
        ("<T>", "<T, U>"),
        ("amount = 0", "amount = 1"),
        ('"USD"', '"EUR"'),
    ],
)
def test_model_hashes_preserve_types_generics_and_defaults(extractor, before, after):
    original = extractor.functions("models.luau", RECORDS)
    changed = extractor.functions("models.luau", RECORDS.replace(before, after))
    assert any(
        extractor.structure_hash(a) != extractor.structure_hash(b) for a, b in zip(original, changed, strict=True)
    )


def test_cosmetics_keep_hashes_but_context_edits_reopen_verdicts(extractor, store):
    original = extractor.functions("models.luau", RECORDS)
    noisy = extractor.functions("models.luau", RECORDS.replace("amount:", "-- field comment\n    amount :"))
    assert [extractor.structure_hash(f) for f in original] == [extractor.structure_hash(f) for f in noisy]
    source = RECORDS + "\nlocal function consume(value: Receipt<string>)\n    return value.amount\nend\n"
    changed = extractor.functions("models.luau", source)
    assert "local function consume" in changed[0].context
    for f in [*original, *changed]:
        f.hash = extractor.structure_hash(f)
    pair = Candidate(new=original[0], existing=original[1], similarity=1)
    verdict = Verdict(label="separate", score=0.1, judge="offline", judge_version="1")
    store.remember(pair, verdict)
    assert store.lookup(pair, "offline", reopen_margin=0.05).verdict == verdict
    updated = Candidate(new=changed[0], existing=changed[1], similarity=1)
    assert pair.context_hash != updated.context_hash
    assert store.lookup(updated, "offline", reopen_margin=0.05).verdict is None


def test_context_preserves_imports_defaults_and_type_dependencies(extractor):
    source = """local Types = require(script.Parent.Types)
local DEFAULT = 3
type Payload = { id: string, value: Types.Value }
local Snapshot = { id = "a", value = DEFAULT }
"""
    payload, snapshot = extractor.functions("models.luau", source)
    assert "local Types = require(script.Parent.Types)" in payload.context
    assert "local DEFAULT = 3" in snapshot.context


def test_function_reference_tables_are_reuse_not_data_models(extractor):
    source = """local function touch() return 1 end
local cross = function() return 2 end
local alias = touch
local Responses = {touch = touch, cross = cross, alias = alias}
local Copy = {touch = touch, cross = cross}
local Data = {touch = 1, cross = unknown}
local Before = {touch = later, cross = unknown}
local function later() return 3 end
touch = 42
local Rebound = {touch = touch, cross = 9}
local cross
local Shadowed = {touch = 1, cross = cross}
"""
    found = {f.name: f for f in extractor.functions("responses.lua", source)}
    assert set(found) == {"Data", "Before", "Rebound", "Shadowed"}
    assert all(set(f.declaration.fields) == {"touch", "cross"} for f in found.values())


def test_callable_references_observe_simultaneous_bindings_and_conditional_writes(extractor):
    source = """local function handler() return 1 end
local handler, old = 7, handler
local Record = {first = handler, second = old, third = unknown}
function Module.run() return 1 end
local Exported = {run = Module . run, kind = "module"}
local function uncertain() return 1 end
if changed then uncertain = 2 end
local Maybe = {first = uncertain, second = 3}
"""
    found = {f.name: f for f in extractor.functions("responses.lua", source)}
    assert found["Record"].declaration.fields == {"first": "handler", "third": "unknown"}
    assert found["Exported"].declaration.fields == {"kind": '"module"'}
    assert found["Maybe"].declaration.fields == {"first": "uncertain", "second": "3"}


def test_calls_in_initializers_leave_mutable_function_references_unresolved(extractor):
    source = """local callback = function() return 1 end
local function mutate() callback = 7 end
local Result = {first = mutate(), second = callback}
local Later = {first = 1, second = callback}
"""
    found = {f.name: f for f in extractor.functions("callbacks.lua", source)}
    assert found["Result"].declaration.fields == {"first": "mutate()", "second": "callback"}
    assert found["Later"].declaration.fields == {"first": "1", "second": "callback"}


@pytest.mark.parametrize("source", ["export type Bad = { id: }", "local Bad = {id = , value = 2}"])
def test_broken_declarations_skip_and_strict_scans_reject(extractor, source):
    assert extractor.functions("broken.luau", source) == []
    with pytest.raises(ValueError, match="Cannot completely scan"):
        extractor.validate_source("broken.luau", source)


def test_luau_model_pass_is_opt_in_and_model_only_does_not_double_run(tmp_path):
    from dry_lint.model_review import enabled

    assert [e.use for e in profile(Settings()).extractors] == ["python-models", "typescript-models"]
    settings = Settings(extractors=["luau"])
    assert [e.use for e in profile(settings).extractors] == ["python-models", "typescript-models", "luau-models"]
    assert not enabled(Settings(extractors=["luau-models"]), None)
    repo = Repo(tmp_path / "model-pass")
    repo.write(".dry-lint/config.toml", 'extractors = ["luau"]\npreset = "none"\n')
    repo.write("old.luau", "export type Old = { id: string, amount: number }\n")
    repo.commit()
    repo.git("checkout", "-qb", "feature")
    repo.write("new.luau", "export type New = { id: string, amount: number }\n")
    repo.commit()
    candidates, report = tmp_path / "candidates.json", tmp_path / "report.json"
    args = ["--root", str(repo.root), "--base", "main", "--out", str(candidates)]
    assert main(["detect", *args]) == 0
    result = CandidatesFile.model_validate_json(candidates.read_text())
    assert len(result.model_candidates) == 1
    assert result.model_candidates[0].new.declaration.kind == "luau"
    assert main(["judge", "--root", str(repo.root), "--candidates", str(candidates), "--report", str(report)]) == 0
    restored = Report.model_validate_json(report.read_text())
    assert restored.models == 2 and len(restored.visible) == 1
    assert main(["detect", *args, "--no-models"]) == 0
    assert CandidatesFile.model_validate_json(candidates.read_text()).model_candidates is None


def test_inline_luau_decisions_flow_through_model_cli(tmp_path):
    repo = Repo(tmp_path / "model-only")
    repo.write(".dry-lint/config.toml", 'extractors = ["luau-models"]\ncomparer = "model-shape"\npreset = "none"\n')
    repo.write("models.luau", "type Original = { id: string, amount: number }\n")
    repo.commit()
    repo.git("checkout", "-qb", "feature")
    repo.write(
        "models.luau",
        """type Original = { id: string, amount: number }
-- dry-lint: distinct-from models.luau::<type>.Original
type Copy = { id: string, amount: number }
""",
    )
    repo.commit()
    output = tmp_path / "candidates.json"
    assert main(["detect", "--root", str(repo.root), "--base", "main", "--out", str(output)]) == 0
    result = CandidatesFile.model_validate_json(output.read_text())
    assert result.changed == 1
    assert len(result.candidates) == 1 and result.candidates[0].filtered == "inline distinct-from"
