"""Model declarations are candidates, never an automatic instruction to merge contracts."""

import pytest

from dry_lint.cli import main
from dry_lint.detector import Detector
from dry_lint.function_index import FunctionIndex, build_index
from dry_lint.judges.command import CommandJudge, prompt
from dry_lint.model_shapes import ModelComparer, PythonModelExtractor, TypeScriptModelExtractor
from dry_lint.models import Candidate, CandidatesFile, Function
from dry_lint.settings import Settings

from conftest import Repo

PYTHON = """
from pydantic import BaseModel as Model, Field
from dataclasses import dataclass as record
from typing import ClassVar

class Invoice(Model):
    invoice_id: str
    amount: int = Field(ge=0)
    currency: str = "USD"
    cache: ClassVar[dict] = {}

@record(frozen=True)
class InvoiceCopy:
    invoice_id: str
    amount: int
    currency: str = "USD"

class PaidInvoice(Invoice):
    paid_at: str
"""


def test_models_flow_through_detector_with_same_file_candidates(tmp_path):
    repo = Repo(tmp_path / "models")
    repo.write("models.py", PYTHON)
    repo.commit()
    settings = Settings(extractors=["python-models"], comparer="model-shape")
    detector = Detector.for_repository(repo.root, settings)
    pairs = detector.candidates(detector.functions)
    assert [(p.new.name, p.existing.name) for p in pairs] == [("Invoice", "InvoiceCopy")]
    assert pairs[0].similarity == 1
    encoded = CandidatesFile(candidates=pairs).model_dump_json()
    restored = CandidatesFile.model_validate_json(encoded)
    assert restored.candidates[0].new.declaration.fields == {"invoice_id": "str", "amount": "int", "currency": "str"}


def test_python_fields_are_declared_not_inherited_and_non_models_are_ignored():
    models = PythonModelExtractor().functions("models.py", PYTHON + "\nclass Helper:\n    invoice_id: str\n")
    assert [m.name for m in models] == ["Invoice", "InvoiceCopy", "PaidInvoice"]
    assert models[2].declaration.fields == {"paid_at": "str"}
    assert models[1].code.startswith("@record(frozen=True)")


@pytest.mark.parametrize(
    "before,after",
    [("ge=0", "ge=1"), ('"USD"', '"EUR"'), ("amount: int", "amount: float"), ("frozen=True", "frozen=False")],
)
def test_model_hash_preserves_validation_and_type_contract(before, after):
    extractor = PythonModelExtractor()
    original = extractor.functions("models.py", PYTHON)
    changed = extractor.functions("models.py", PYTHON.replace(before, after))
    assert any(
        extractor.structure_hash(a) != extractor.structure_hash(b) for a, b in zip(original, changed, strict=True)
    )


def test_typescript_and_zod_fields_without_reimplementing_derived_shapes():
    source = """
import { z as schema } from "zod";
export const Invoice = schema.object({invoiceId: schema.string(), amount: schema.number().min(0), currency: schema.string()});
export const Derived = Invoice.pick({invoiceId: true, amount: true});
export interface InvoiceCopy { invoiceId: string; amount: number; currency: string; }
export type Inferred = schema.infer<typeof Invoice>;
export type PaidInvoice = InvoiceCopy & { paidAt: string };
"""
    models = TypeScriptModelExtractor().functions("invoice.ts", source)
    assert [m.name for m in models] == ["Invoice", "InvoiceCopy", "PaidInvoice"]
    assert set(models[0].declaration.fields) == {"invoiceId", "amount", "currency"}
    assert set(models[2].declaration.fields) == {"paidAt"}
    comparer = ModelComparer()
    comparer.index(models)
    assert comparer.similarity(models[0], models[1]) == 1


def test_near_copy_recalls_added_field_without_returning_itself():
    extractor = PythonModelExtractor()
    models = extractor.functions("models.py", PYTHON)
    near = extractor.functions("near.py", PYTHON.replace("    cache: ClassVar[dict] = {}", "    invoice_date: str"))[0]
    comparer = ModelComparer()
    comparer.index([*models, near])
    assert comparer.similarity(models[0], near) >= 0.7
    tiny = extractor.functions(
        "tiny.py", "from pydantic import BaseModel\nclass Tiny(BaseModel):\n    id: str\n    name: str\n"
    )[0]
    comparer.index([tiny])
    assert comparer.neighbours(tiny, 3, lambda _: True) == []


def test_two_field_contracts_and_one_field_drift_are_candidates():
    extractor = TypeScriptModelExtractor()
    models = extractor.functions(
        "types.ts",
        """
type FrameSize = { width: number; height: number };
type ImageSize = { width: number; height: number };
type Thumbnail = { width: number; height: number; source: string };
type Unrelated = { id: string; source: string };
""",
    )
    comparer = ModelComparer()
    comparer.index(models)
    assert {f.name for f, _ in comparer.neighbours(models[0], 3, lambda _: True)} == {"ImageSize", "Thumbnail"}
    assert comparer.similarity(models[0], models[3]) == 0
    assert comparer.shared(models[0], models[1]) == ["height", "width"]


def test_inherited_defaults_do_not_crowd_out_independent_copies():
    source = (
        PYTHON
        + """
class DefaultInvoice(Invoice):
    invoice_id: str = "example"
    amount: int = 0
    currency: str = "EUR"
class AnotherDefault(DefaultInvoice):
    currency: str = "GBP"
"""
    )
    assert [f.name for f in PythonModelExtractor().functions("models.py", source)] == [
        "Invoice",
        "InvoiceCopy",
        "PaidInvoice",
    ]


def test_python_aliases_private_fields_generic_bases_and_dataclass_initvars():
    source = """
import pydantic as p
import dataclasses
from typing import ClassVar as CV
@dataclasses.dataclass
class Options:
    count: int
    DEFAULT = 1
    def value(self):
        return self.count
    _internal: int
    cache: CV[int]
    temporary: dataclasses.InitVar[int]
class Packet(p.BaseModel, list[int]):
    payload: list[int]
    model_config: dict = {}
class Child(Packet):
    sequence: int
class Arbitrary(factory()):
    payload: int
class Unresolved((lambda: Packet)()):
    payload: int
"""
    models = PythonModelExtractor().functions("models.py", source)
    assert [(m.name, set(m.declaration.fields)) for m in models] == [
        ("Options", {"count"}),
        ("Packet", {"payload"}),
        ("Child", {"sequence"}),
    ]


@pytest.mark.parametrize(
    "extractor,path,source",
    [
        (PythonModelExtractor(), "broken.py", "class Bad(:"),
        (TypeScriptModelExtractor(), "broken.ts", "interface Broken { a: ;"),
    ],
)
def test_invalid_source_is_rejected_in_strict_mode(extractor, path, source):
    assert extractor.functions(path, source) == []
    with pytest.raises(ValueError, match="Cannot completely scan"):
        extractor.validate_source(path, source)


@pytest.mark.parametrize(
    "import_line",
    ['import * as schema from "zod";', 'import schema from "zod";', 'import { z as schema } from "zod/v4";'],
)
def test_zod_import_forms_wrappers_and_literal_members(import_line):
    source = (
        import_line
        + """
const shared = schema.string();
const Account = schema.strictObject({"user-id": shared, shared, nested: schema.object({id: schema.string()}), [dynamic]: shared}).strict();
const Derived = Account.omit({shared: true});
const NotZod = other.object({id: shared});
const BareCall = object({id: shared});
const Value = schema.object();
export {};
type Empty = string;
type Record = ({key: string; method(): void});
"""
    )
    models = TypeScriptModelExtractor().functions("models.tsx", source)
    assert [m.name for m in models] == ["Account", "Record"]
    assert set(models[0].declaration.fields) == {"user-id", "shared", "nested"}
    assert models[1].declaration.fields == {"key": "string"}


@pytest.mark.parametrize(
    "before,after",
    [("number", "string"), ("min(0)", "min(1)"), ("optional()", "nullable()"), ("strict()", "passthrough()")],
)
def test_typescript_hash_includes_contract_changes(before, after):
    extractor = TypeScriptModelExtractor()
    source = 'import {z} from "zod"; const M = z.object({value: z.number().min(0).optional()}).strict();'
    original = extractor.functions("model.ts", source)[0]
    changed = extractor.functions("model.ts", source.replace(before, after))[0]
    assert extractor.structure_hash(original) != extractor.structure_hash(changed)
    cosmetic = extractor.functions("model.ts", source.replace("value:", "/* field */ value :"))[0]
    assert extractor.structure_hash(original) == extractor.structure_hash(cosmetic)


def test_changed_local_usage_reopens_same_model_pair():
    extractor = PythonModelExtractor()
    first = extractor.functions("models.py", PYTHON)
    second = extractor.functions("models.py", PYTHON + "\ndef consume(value: Invoice):\n    return value.amount\n")
    before = Candidate(new=first[0], existing=first[1], similarity=1)
    after = Candidate(new=second[0], existing=second[1], similarity=1)
    assert extractor.structure_hash(first[0]) == extractor.structure_hash(second[0])
    assert before.context_hash != after.context_hash
    assert "def consume" in second[0].context


def test_inline_decisions_and_changed_models_work_through_cli(tmp_path):
    repo = Repo(tmp_path / "model-cli")
    repo.write(".dry-lint.toml", 'extractors = ["python-models"]\ncomparer = "model-shape"\npreset = "none"\n')
    repo.write("models.py", PYTHON)
    repo.commit("base")
    repo.git("checkout", "-qb", "feature")
    repo.write(
        "models.py",
        PYTHON.replace("@record(frozen=True)", "# dry-lint: distinct-from models.py::Invoice\n@record(frozen=True)"),
    )
    repo.commit("decision")
    out = tmp_path / "candidates.json"
    assert main(["detect", "--root", str(repo.root), "--base", "main", "--out", str(out)]) == 0
    result = CandidatesFile.model_validate_json(out.read_text())
    assert result.changed == 1
    assert len(result.candidates) == 1 and result.candidates[0].filtered == "inline distinct-from"


def test_index_roundtrip_preserves_model_retrieval_metadata():
    settings = Settings(extractors=["python-models"], comparer="model-shape")
    index = build_index({"models.py": PYTHON.encode()}, "org/models", "a" * 40, settings)
    restored = FunctionIndex.decode(index.encode(), "org/models", "a" * 40, index.contract)
    models = restored.extracted()
    assert models[0].declaration == index.functions[0].declaration
    comparer = ModelComparer()
    comparer.index(models)
    assert comparer.neighbours(models[0], 3, lambda _: True)[0][0].name == "InvoiceCopy"


def test_model_prompt_preserves_context_and_has_distinct_cache_policy():
    models = PythonModelExtractor().functions("models.py", PYTHON)
    pair = Candidate(new=models[0], existing=models[1], similarity=1)
    judge = CommandJudge(command="example", prompt_policy="model-contracts")
    assert models[0].context in judge.stdin(pair)
    assert "independent test oracles" in judge.stdin(pair)
    assert judge.version != CommandJudge(command="example").version
    assert judge.strict_version
    assert "NEW CONTEXT" not in prompt(pair)
    with pytest.raises(ValueError, match="Unknown prompt policy"):
        CommandJudge(command="example", prompt_policy="unknown")


def test_non_model_units_and_invalid_options():
    function = Function(path="a.py", name="run", line=1, end_line=1, code="pass")
    comparer = ModelComparer()
    comparer.index([function])
    assert comparer.neighbours(function, 3, lambda _: True) == []
    assert comparer.shared(function, function) == []
    assert comparer.similarity(function, function) == 0
    with pytest.raises(ValueError, match="model-shape needs"):
        ModelComparer(min_fields=0)
