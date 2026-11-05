"""Model declarations are candidates, never an automatic instruction to merge contracts."""

import pytest

from dry_lint.detector import Detector
from dry_lint.model_shapes import ModelComparer, PythonModelExtractor, TypeScriptModelExtractor
from dry_lint.models import CandidatesFile
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


def test_near_copy_recalls_added_field_but_rejects_generic_two_field_overlap():
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
