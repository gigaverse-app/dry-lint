"""Opt-in declaration extraction and field-overlap retrieval. Never imports adopter code.

Shape is only retrieval evidence. Validators, defaults, decorators and local uses stay in the
source supplied to the judge; independently meaningful contracts may have identical fields.
"""

import ast
import hashlib
from collections import defaultdict
from collections.abc import Callable
from typing import Literal

from tree_sitter import Node

from dry_lint.extractors import PythonExtractor
from dry_lint.functions import python_imports
from dry_lint.models import Declaration, Function
from dry_lint.python_schemas import SchemaModule, reference
from dry_lint.source_context import SourceContext, with_comments
from dry_lint.typescript import TypeScriptExtractor, text


def model_unit(
    path: str, name: str, line: int, end_line: int, code: str, declaration: Declaration, source: str, context: str
) -> Function:
    return Function(
        path=path,
        name=name,
        line=line,
        end_line=end_line,
        code=code,
        declaration=declaration,
        tokens=[f"field:{name}" for name in declaration.fields],
        calls=[],
        context=context,
        context_digest=hashlib.sha256(source.encode()).hexdigest(),
    )


def resolved_name(node: ast.expr, bindings: dict[str, str]) -> str:
    return reference(node, bindings, follow_calls=True)


class PythonModelExtractor(PythonExtractor):
    name: str = "python-models"
    version: str = "3"

    def functions(self, path: str, source: str) -> list[Function]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        modules, names = python_imports(tree, path)
        ancestors = SchemaModule(path, source).ancestors()
        bindings = {name: module.replace("/", ".") for name, module in modules.items()}
        bindings.update({name: f"{module.replace('/', '.')}.{symbol}" for name, (module, symbol) in names.items()})
        kinds: dict[str, Literal["pydantic", "dataclass"]] = {
            "pydantic.BaseModel": "pydantic",
            "pydantic.v1.BaseModel": "pydantic",
            "pydantic.generics.GenericModel": "pydantic",
            "ninja.Schema": "pydantic",
            "ninja.schema.Schema": "pydantic",
            "ninja.ModelSchema": "pydantic",
        }
        found: list[Function] = []
        inherited: dict[str, set[str]] = {}
        lines = source.splitlines()
        # Only direct fields contribute: inheritance is already reuse, not copied declarations.
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            kind: Literal["pydantic", "dataclass"] | None = next(
                (kinds[base] for b in node.bases if (base := resolved_name(b, bindings)) in kinds), None
            )
            if any(
                resolved_name(d, bindings) in {"dataclasses.dataclass", "pydantic.dataclasses.dataclass"}
                for d in node.decorator_list
            ):
                kind = "dataclass"
            if kind is None:
                continue
            kinds[node.name] = kind
            base_fields = set[str]().union(
                *(inherited.get(resolved_name(base, bindings), set()) for base in node.bases)
            )
            fields: dict[str, str] = {}
            for field in node.body:
                if not isinstance(field, ast.AnnAssign) or not isinstance(field.target, ast.Name):
                    continue
                name = field.target.id
                annotation = resolved_name(field.annotation, bindings)
                if (
                    name.startswith("_")
                    or name == "model_config"
                    or annotation in {"typing.ClassVar", "ClassVar", "dataclasses.InitVar"}
                ):
                    continue
                fields[name] = ast.unparse(field.annotation)
            inherited[node.name] = base_fields | set(fields)
            fields = {name: annotation for name, annotation in fields.items() if name not in base_fields}
            if not fields:
                continue
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            while start > 1 and lines[start - 2].lstrip().startswith("#"):
                start -= 1
            end = node.end_lineno or node.lineno
            code = "\n".join(lines[start - 1 : end])
            imports = [
                ast.get_source_segment(source, n) or ""
                for n in tree.body
                if isinstance(n, (ast.Import, ast.ImportFrom))
            ]
            # Same-file constructors/converters establish use without claiming cross-file symbol resolution.
            uses = [
                ast.get_source_segment(source, n) or ""
                for n in tree.body
                if n is not node
                and not isinstance(n, (ast.Import, ast.ImportFrom))
                and any(isinstance(child, ast.Name) and child.id == node.name for child in ast.walk(n))
            ]
            context = "\n".join([*imports, *uses])[:8000]
            found.append(
                model_unit(
                    path,
                    node.name,
                    start,
                    end,
                    code,
                    Declaration(kind=kind, fields=fields, reachable_from=ancestors[node.name]),
                    source,
                    context,
                )
            )
        return found

    def structure_hash(self, function: Function) -> str:
        # Unlike function hashing, annotations, defaults, decorators and validators ARE the contract.
        tree = ast.parse(function.code)
        return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()[:16]


def ts_shape(node: Node) -> list[Node]:
    """Only explicitly declared top-level members; references/extends/pick/infer add no copied fields."""
    if node.type in {"object_type", "interface_body", "object"}:
        return list(node.named_children)
    if node.type in {"intersection_type", "parenthesized_type"}:
        return [field for child in node.named_children for field in ts_shape(child)]
    return []


def zod_object(node: Node, namespaces: set[str]) -> Node | None:
    if node.type != "call_expression":
        return None
    target = node.child_by_field_name("function")
    if target is None or target.type != "member_expression":
        return None
    receiver, prop = target.child_by_field_name("object"), target.child_by_field_name("property")
    assert receiver is not None and prop is not None  # member_expression grammar
    if text(receiver) in namespaces and text(prop) in {"object", "strictObject", "looseObject"}:
        args = node.child_by_field_name("arguments")
        return next((a for a in args.named_children if a.type == "object"), None) if args else None
    # Preserve direct object literals wrapped with strict/refine/etc, not fields derived from another schema.
    return zod_object(receiver, namespaces)


class TypeScriptModelExtractor(TypeScriptExtractor):
    name: str = "typescript-models"
    version: str = "1"
    preserve_types: bool = True

    def functions(self, path: str, source: str) -> list[Function]:
        root = self.parser(path).parse(source.encode()).root_node
        context = SourceContext(root)
        namespaces: set[str] = set()
        for node in root.named_children:
            module = node.child_by_field_name("source")
            if (
                node.type != "import_statement"
                or module is None
                or text(module).strip("\"'") not in {"zod", "zod/v3", "zod/v4", "zod/v4-mini", "zod/mini"}
            ):
                continue
            pending = list(node.named_children)
            while pending:
                child = pending.pop()
                if child.type == "import_specifier":
                    name, alias = child.child_by_field_name("name"), child.child_by_field_name("alias")
                    if name is not None and text(name) in {"z", "default"}:
                        namespaces.add(text(alias or name))
                elif child.type == "namespace_import":
                    namespaces.add(text(child.named_children[-1]))
                elif child.type == "import_clause":
                    namespaces.update(text(c) for c in child.named_children if c.type == "identifier")
                pending.extend(child.named_children)
        found: list[Function] = []
        for statement in root.named_children:
            declaration = (
                statement.child_by_field_name("declaration") if statement.type == "export_statement" else statement
            )
            if declaration is None:
                continue
            nodes = (
                declaration.named_children
                if declaration.type in {"lexical_declaration", "variable_declaration"}
                else [declaration]
            )
            for node in nodes:
                name = node.child_by_field_name("name")
                if name is None or node.has_error:
                    continue
                shape = None
                kind = "typescript"
                if node.type == "interface_declaration":
                    shape = node.child_by_field_name("body")
                elif node.type == "type_alias_declaration":
                    shape = node.child_by_field_name("value")
                elif node.type == "variable_declarator":
                    value = node.child_by_field_name("value")
                    shape = zod_object(value, namespaces) if value is not None else None
                    kind = "zod"
                if shape is None:
                    continue
                fields: dict[str, str] = {}
                for field in ts_shape(shape):
                    if field.type not in {"property_signature", "pair", "shorthand_property_identifier"}:
                        continue
                    key = field.child_by_field_name("name") or field.child_by_field_name("key")
                    if field.type == "shorthand_property_identifier":
                        key = field
                    if key is None or key.type == "computed_property_name":
                        continue
                    annotation = field.child_by_field_name("type") or field.child_by_field_name("value")
                    fields[text(key).strip("\"'")] = text(annotation).lstrip(":").strip() if annotation else text(field)
                if not fields:
                    continue
                code = with_comments(statement)
                uses = [
                    text(other) for other in root.named_children if other != statement and text(name) in text(other)
                ]
                local_context = (context.for_function(node) + "\n" + "\n".join(uses))[:8000]
                found.append(
                    model_unit(
                        path,
                        text(name),
                        statement.start_point.row + 1,
                        statement.end_point.row + 1,
                        code,
                        Declaration(kind=kind, fields=fields),
                        source,
                        local_context,
                    )
                )
        return found


class ModelComparer:
    """Field Dice overlap with an inverted index. A score is likeness, never consolidation confidence."""

    name: str = "model-shape"
    version: str = "1"
    similarity_reusable: bool = False

    def __init__(self, min_similarity: float = 0.65, min_fields: int = 2) -> None:
        if not 0 <= min_similarity <= 1 or min_fields < 1:
            raise ValueError("model-shape needs 0 <= min_similarity <= 1 and min_fields >= 1")
        self.min_similarity: float = min_similarity
        self.min_fields: int = min_fields
        self.functions: list[Function] = []
        self.postings: dict[str, set[int]] = defaultdict(set)

    def index(self, functions: list[Function]) -> None:
        self.functions = functions
        self.postings = defaultdict(set)
        for i, function in enumerate(functions):
            if function.declaration:
                for field in function.declaration.fields:
                    self.postings[field].add(i)

    def similarity(self, a: Function, b: Function) -> float:
        if not a.declaration or not b.declaration:
            return 0
        left, right = set(a.declaration.fields), set(b.declaration.fields)
        common = left & right
        if len(common) < self.min_fields:
            return 0
        return 2 * len(common) / (len(left) + len(right))

    def neighbours(
        self, function: Function, k: int, allowed: Callable[[Function], bool]
    ) -> list[tuple[Function, float]]:
        if not function.declaration:
            return []
        positions = set[int]().union(*(self.postings.get(field, set()) for field in function.declaration.fields))
        found = [
            (self.functions[i], self.similarity(function, self.functions[i]))
            for i in positions
            if self.functions[i].qualname != function.qualname and allowed(self.functions[i])
        ]
        return sorted(
            (pair for pair in found if pair[1] >= self.min_similarity and pair[1] > 0),
            key=lambda pair: (-pair[1], pair[0].qualname),
        )[:k]

    def shared(self, a: Function, b: Function, limit: int = 12) -> list[str]:
        if not a.declaration or not b.declaration:
            return []
        return sorted(set(a.declaration.fields) & set(b.declaration.fields))[:limit]
