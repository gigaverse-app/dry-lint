"""Provider-free equivalence of exact source AST slices, not full app execution."""

from __future__ import annotations

import ast
import collections
import copy
import itertools
import json
import math
import platform
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from decimal import Decimal
from fractions import Fraction
from functools import cache
from types import SimpleNamespace

from study import (
    COMMON,
    HELPER,
    PREFIX,
    ROOT,
    build,
    dump,
    guards,
    replacement,
    sha,
    tree_dump,
)

INV = json.loads((ROOT / "inventory.json").read_text())
ROWS = INV["eligible"]
SOURCES = {p: (ROOT / "source" / p).read_text() for p in {r["path"] for r in ROWS} | {COMMON}}
TREES = {p: ast.parse(s) for p, s in SOURCES.items()}
GROUPS = collections.defaultdict(list)
for row in ROWS:
    GROUPS[row["source_id"]].append(row)

# Direct helper inputs include Python-only stress cases beyond validated requests.
CASES = [
    ("none", None),
    ("positive_float", 1.25),
    ("positive_int", 2),
    ("zero_int", 0),
    ("zero_float", 0.0),
    ("negative_float", -1.25),
    ("negative_int", -2),
    ("nan", float("nan")),
    ("positive_infinity", float("inf")),
    ("negative_infinity", -float("inf")),
    ("negative_zero", -0.0),
    ("true", True),
    ("false", False),
    ("smallest_positive", math.ulp(0.0)),
    ("smallest_negative", -math.ulp(0.0)),
    ("largest_finite", sys.float_info.max),
    ("numeric_string", "1.25"),
    ("negative_string", "-1.25"),
    ("empty_string", ""),
    ("nan_string", "nan"),
    ("bad_string", "bad"),
    ("bytes_number", b"1.25"),
    ("list", []),
    ("dict", {}),
    ("complex", 1 + 2j),
    ("plain_object", object()),
    ("decimal_positive", Decimal("1.25")),
    ("decimal_nan", Decimal("NaN")),
    ("decimal_snan", Decimal("sNaN")),
    ("fraction", Fraction(1, 3)),
    ("overflow_int", 10**400),
]


class CapturedHTTP(Exception):
    """Boundary recorder, not an implementation of FastAPI HTTP behavior."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        super().__init__()


def execute(statements, namespace):
    module = ast.Module(body=copy.deepcopy(statements), type_ignores=[])
    code = compile(ast.fix_missing_locations(module), "<exact-source-slice>", "exec")
    exec(code, namespace)


@cache
def environment(proposed=False):
    ns = {"math": math, "HTTPException": CapturedHTTP}
    execute(ast.parse(HELPER).body, ns)
    tree = ast.parse(
        (ROOT / ("proposed" if proposed else "source") / (PREFIX + "key_management_endpoints.py")).read_text()
    )
    helpers = [
        copy.deepcopy(n)
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in {"_validate_max_budget", "_validate_soft_budget_value"}
    ]
    execute(helpers, ns)
    return ns


def outcome(statements, values, proposed=False):
    ns = environment(proposed).copy()
    ns.update(values)
    try:
        execute(statements, ns)
        return {"kind": "ok"}
    except CapturedHTTP as exc:
        return {"kind": "HTTPException-constructor", "kwargs": exc.kwargs}
    except Exception as exc:
        return {"kind": type(exc).__name__, "args": list(exc.args)}


def node_for(row):
    return next(n for n in ast.walk(TREES[row["path"]]) if isinstance(n, ast.If) and n.lineno == row["line"])


def call_for(row):
    return ast.parse(textwrap.dedent(replacement(row))).body[0]


def values_for(rows, values):
    ns = {"data": SimpleNamespace(), "budget_obj": SimpleNamespace()}
    for r, value in zip(rows, values, strict=True):
        if "." in r["expression"]:
            name, field = r["expression"].split(".")
            setattr(ns[name], field, value)
        else:
            ns[r["expression"]] = value
    return ns


def first_failure(fields, values):
    # Independent explicit contract expectation for the primitive matrix.
    for field, value in zip(fields, values, strict=True):
        if value is None:
            continue
        try:
            finite = math.isfinite(value)
        except Exception as exc:
            return {"kind": type(exc).__name__, "args": list(exc.args)}
        if not finite or value < 0:
            return {
                "kind": "HTTPException-constructor",
                "kwargs": {
                    "status_code": 400,
                    "detail": {"error": f"{field} must be a non-negative finite number. Received: {value}"},
                },
            }
    return {"kind": "ok"}


class EquivalenceTests(unittest.TestCase):
    def test_pinned_snapshots_and_rebuild(self):
        provenance = json.loads((ROOT / "provenance.json").read_text())
        for file in provenance["files"]:
            self.assertEqual(sha((ROOT / "source" / file["path"]).read_bytes()), file["sha256"])
        old_patch = (ROOT / "extraction.patch").read_bytes()
        old_metrics = (ROOT / "metrics.json").read_bytes()
        build()
        self.assertEqual(old_patch, (ROOT / "extraction.patch").read_bytes())
        self.assertEqual(old_metrics, (ROOT / "metrics.json").read_bytes())
        for path in SOURCES:
            eligible, _ = guards(SOURCES[path], path)
            self.assertEqual(eligible, [r for r in ROWS if r["path"] == path])

    def test_patch_applies_to_exact_snapshots(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            target = shutil.copytree(ROOT / "source", str(tmp) + "/source")
            subprocess.run(
                ["patch", "--batch", "-p1", "-i", str(ROOT / "extraction.patch")],
                cwd=target,
                check=True,
                capture_output=True,
            )
            metrics = json.loads((ROOT / "metrics.json").read_text())
            for row in metrics["per_file"]:
                from pathlib import Path

                self.assertEqual(sha((Path(target) / row["path"]).read_bytes()), row["after_sha256"])

    def test_whole_file_ast_changes_only_exact_guards_and_import_names(self):
        # Restore replacements in the proposed AST. Everything else, including
        # ownership checks, 422 paths, durations, and soft/max relations, must match.
        for path, original in TREES.items():
            proposed = ast.parse((ROOT / "proposed" / path).read_text())
            rows = iter([r for r in ROWS if r["path"] == path])
            restored = []

            # Traversal finishes within this iteration; these closures never escape it.
            class Restore(ast.NodeTransformer):
                def visit_Expr(self, node):
                    if (
                        isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Name)
                        and node.value.func.id == "validate_nonnegative_budget"
                    ):
                        row = next(rows)  # noqa: B023
                        self_outer.assertEqual(tree_dump(node), tree_dump(call_for(row)))  # noqa: B023
                        restored.append(row)  # noqa: B023
                        return copy.deepcopy(node_for(row))
                    return node

                def visit_FunctionDef(self, node):
                    if path == COMMON and node.name == "validate_nonnegative_budget":  # noqa: B023
                        self_outer.assertEqual(tree_dump(node), tree_dump(ast.parse(HELPER).body[0]))  # noqa: B023
                        return None
                    return self.generic_visit(node)

                def visit_ImportFrom(self, node):
                    node.names = [a for a in node.names if a.name != "validate_nonnegative_budget"]
                    return node

            self_outer = self
            recovered = Restore().visit(proposed)
            expected_original = copy.deepcopy(original)
            if path == PREFIX + "budget_management_endpoints.py":
                expected_original.body = [
                    n
                    for n in expected_original.body
                    if not (isinstance(n, ast.Import) and [a.name for a in n.names] == ["math"])
                ]
            self.assertEqual(tree_dump(recovered), tree_dump(expected_original), path)
            self.assertEqual(len(restored), sum(r["path"] == path for r in ROWS))

    def test_each_original_guard_against_shared_validator(self):
        results = []
        for row in ROWS:
            for label, value in CASES:
                with self.subTest(source=row["source_id"], field=row["field"], value=label):
                    ns = values_for([row], [value])
                    old = outcome([node_for(row)], ns)
                    new = outcome([call_for(row)], ns, True)
                    self.assertEqual(old, new)
                    self.assertEqual(old, first_failure([row["field"]], [value]))
                    if isinstance(value, float) and value == 0:
                        # Neither implementation converts or rewrites signed zero.
                        current = eval(row["expression"], ns)
                        self.assertEqual(current.hex(), value.hex())
                    results.append(
                        dict(
                            source_id=row["source_id"],
                            field=row["field"],
                            input=label,
                            outcome=old,
                        )
                    )
        dump("guard-matrix.json", results)

    def test_multiple_invalid_field_precedence(self):
        results = []
        domain = CASES[:13]  # None, finite, negative, NaN, infinities, signed zero, bools.
        # Include nonnumeric input in first/late positions: it must not leapfrog
        # an earlier HTTP400 through eager batch evaluation.
        domain = [*domain, ("bad_string", "bad")]
        for source_id, group in GROUPS.items():
            old_nodes = [node_for(r) for r in group]
            new_nodes = [call_for(r) for r in group]
            fields = [r["field"] for r in group]
            # Key endpoints already share soft validation. Exercise that unchanged
            # exact call in the same block, without counting it as a new owner.
            expanded = list(group)
            if group[0]["function"] in {"generate_key_fn", "update_key_fn"}:
                old_fn = next(
                    n
                    for n in ast.walk(TREES[group[0]["path"]])
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == group[0]["function"]
                )
                call = next(
                    n
                    for n in ast.walk(old_fn)
                    if isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Call)
                    and ast.unparse(n.value.func) == "_validate_soft_budget_value"
                )
                old_nodes.append(call)
                new_nodes.append(call)
                expanded.append(dict(expression="data.soft_budget", field="soft_budget"))
                fields.append("soft_budget")
            checked, http = 0, 0
            for combo in itertools.product(domain, repeat=len(expanded)):
                labels, values = zip(*combo, strict=True)
                ns = values_for(expanded, values)
                old = outcome(old_nodes, ns)
                new = outcome(new_nodes, ns, True)
                self.assertEqual(old, new, (source_id, labels))
                self.assertEqual(old, first_failure(fields, values), (source_id, labels))
                checked += 1
                http += old["kind"] == "HTTPException-constructor"
            results.append(
                dict(
                    source_id=source_id,
                    field_order=fields,
                    combinations=checked,
                    http400_outcomes=http,
                )
            )
        dump(
            "precedence-results.json",
            dict(
                domain=[k for k, _ in domain],
                groups=results,
                combinations=sum(r["combinations"] for r in results),
            ),
        )

    def test_existing_team_soft_max_policy(self):
        tree = TREES[PREFIX + "team_endpoints.py"]
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "new_team")
        # Copy the complete nested optional/comparison statement, not a rewritten rule.
        relational = next(
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.If)
            and ast.unparse(n.test) == "data.soft_budget is not None"
            and "data.soft_budget >= data.max_budget" in ast.unparse(n)
        )
        group = GROUPS[PREFIX + "team_endpoints.py::new_team"]
        tested = 0
        for maximum, member, soft in itertools.product([None, 0.0, 1.0, 2.0, -1.0, float("nan")], repeat=3):
            ns = values_for(group, [maximum, member, soft])
            old = outcome([*[node_for(r) for r in group], relational], ns)
            new = outcome([*[call_for(r) for r in group], relational], ns, True)
            self.assertEqual(old, new)
            expected = first_failure([r["field"] for r in group], [maximum, member, soft])
            if expected["kind"] == "ok" and soft is not None and maximum is not None and soft >= maximum:
                expected = {
                    "kind": "HTTPException-constructor",
                    "kwargs": {
                        "status_code": 400,
                        "detail": {"error": f"soft_budget ({soft}) must be strictly lower than max_budget ({maximum})"},
                    },
                }
            self.assertEqual(old, expected)
            tested += 1
        dump(
            "relational-results.json",
            dict(
                cases=tested,
                scope="new_team exact relational AST; intervening duration/model policies not executed; whole-file AST check proves retained placement",
            ),
        )

    def test_pydantic_budget_field_slices(self):
        # This deliberately does NOT fabricate complete request models. It executes
        # exact budget field declarations, inheritance/config and budget validators.
        import pydantic
        from pydantic import (
            BaseModel,
            ConfigDict,
            Field,
            ValidationError,
            field_validator,
        )

        definitions = [
            ("litellm/types/llms/base.py", "LiteLLMPydanticObjectBase"),
            ("litellm/models/team.py", "TeamBase"),
            ("litellm/models/budget.py", "LiteLLM_BudgetTable"),
            (
                "litellm/types/proxy/management_endpoints/request_base.py",
                "GenerateRequestBase",
            ),
            (
                "litellm/types/proxy/management_endpoints/key_requests.py",
                "KeyRequestBase",
            ),
            (
                "litellm/types/proxy/management_endpoints/key_requests.py",
                "GenerateKeyRequest",
            ),
            (
                "litellm/types/proxy/management_endpoints/key_requests.py",
                "UpdateKeyRequest",
            ),
            *[
                ("litellm/proxy/_types.py", c)
                for c in [
                    "BudgetNewRequest",
                    "NewTeamRequest",
                    "UpdateTeamRequest",
                    "NewOrganizationRequest",
                    "LiteLLM_OrganizationTableUpdate",
                ]
            ],
        ]
        ns = dict(
            BaseModel=BaseModel,
            ConfigDict=ConfigDict,
            Field=Field,
            field_validator=field_validator,
        )
        evidence, results = [], []
        for path, name in definitions:
            tree = ast.parse((ROOT / "source" / path).read_text())
            source_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
            cls = copy.deepcopy(source_class)
            cls.body = [
                n
                for n in cls.body
                if (
                    isinstance(n, ast.AnnAssign)
                    and ast.unparse(n.target) in {"max_budget", "soft_budget", "team_member_budget"}
                    or isinstance(n, ast.Assign)
                    and any(ast.unparse(t) == "model_config" for t in n.targets)
                    or isinstance(n, ast.FunctionDef)
                    and n.name == "check_max_budget"
                )
            ]
            if name == "LiteLLMPydanticObjectBase":
                cls.bases = [ast.Name(id="BaseModel", ctx=ast.Load())]
            if not cls.body:
                cls.body = [ast.Pass()]
            execute([cls], ns)
            evidence.append(
                dict(
                    path=path,
                    name=name,
                    original_bases=[ast.unparse(b) for b in source_class.bases],
                    line=source_class.lineno,
                    slice=ast.unparse(cls),
                )
            )
        owner_models = {
            "new_team": "NewTeamRequest",
            "update_team": "UpdateTeamRequest",
            "new_budget": "BudgetNewRequest",
            "update_budget": "BudgetNewRequest",
            "new_organization": "NewOrganizationRequest",
            "update_organization": "LiteLLM_OrganizationTableUpdate",
            "generate_key_fn": "GenerateKeyRequest",
            "update_key_fn": "UpdateKeyRequest",
        }
        for _source_id, group in GROUPS.items():
            model_name = owner_models.get(group[0]["function"])
            if model_name is None:
                continue
            model = ns[model_name]
            model_rows = list(group)
            if group[0]["function"] in {"generate_key_fn", "update_key_fn"}:
                model_rows += GROUPS[PREFIX + "key_management_endpoints.py::_validate_soft_budget_value"]
            for row in model_rows:
                for label, raw in CASES:
                    try:
                        obj = model(**{row["field"]: raw})
                    except ValidationError as exc:
                        results.append(
                            dict(
                                model=model_name,
                                field=row["field"],
                                input=label,
                                admission="rejected_by_field_slice",
                                errors=[e["type"] for e in exc.errors()],
                            )
                        )
                        continue
                    parsed = getattr(obj, row["field"])
                    env = values_for([row], [parsed])
                    old = outcome([node_for(row)], env)
                    new = outcome([call_for(row)], env, True)
                    self.assertEqual(old, new)
                    results.append(
                        dict(
                            model=model_name,
                            field=row["field"],
                            input=label,
                            admission="accepted_by_field_slice",
                            parsed_type=type(parsed).__name__,
                            parsed=repr(parsed),
                            outcome=old,
                        )
                    )
        dump(
            "model-domain-results.json",
            dict(
                pydantic=pydantic.__version__,
                evidence=evidence,
                results=results,
                limitation="Budget-field projections only, not whole request models. Other fields/model validators, app state, HTTP parsing and middleware were not executed. Base schema deferral hooks omitted; no budget coercion hooks invented.",
            ),
        )

    def test_scope_counterexamples_and_mutation_sensitivity(self):
        # Sanity: removing finite check, changing optional/zero rule, status,
        # message, or validation order must be observable with this domain.
        helper = ast.parse(HELPER).body[0]
        mutants = {
            "drop_finite": HELPER.replace("(not math.isfinite(value) or value < 0)", "value < 0"),
            "reject_zero": HELPER.replace("value < 0", "value <= 0"),
            "wrong_status": HELPER.replace("status_code=400", "status_code=422"),
            "wrong_message": HELPER.replace("non-negative finite", "positive finite"),
            "drop_none_gate": HELPER.replace("value is not None and ", ""),
        }
        detected = []
        for name, source in mutants.items():
            differences = []
            for label, value in CASES:
                ns = {"math": math, "HTTPException": CapturedHTTP, "value": value}
                call = ast.parse('validate_nonnegative_budget(value, "max_budget")').body[0]
                baseline = outcome([helper, call], ns)
                changed = outcome([*ast.parse(source).body, call], ns)
                if baseline != changed:
                    differences.append(label)
            self.assertTrue(differences, name)
            detected.append(dict(mutation=name, discriminating_inputs=differences))
        group = GROUPS[PREFIX + "team_endpoints.py::new_team"]
        ns = values_for(group, [-1.0, -2.0, -3.0])
        self.assertNotEqual(
            outcome([node_for(r) for r in group], ns),
            outcome([call_for(r) for r in reversed(group)], ns, True),
        )

        # A stateful property violates the stable-field assumption. Record the
        # actual counterexample instead of claiming all Python objects equivalent.
        class ChangingBudget:
            def __init__(self):
                self.values = iter([1.0, 1.0, -1.0, -1.0])

            @property
            def max_budget(self):
                return next(self.values)

        row = group[0]
        old = outcome([node_for(row)], {"data": ChangingBudget()})
        new = outcome([call_for(row)], {"data": ChangingBudget()}, True)
        self.assertNotEqual(old, new)
        dump(
            "sensitivity.json",
            dict(
                mutants=detected,
                reversed_order_detected=True,
                stable_field_counterexample=dict(original=old, proposed=new),
                python=platform.python_version(),
            ),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
