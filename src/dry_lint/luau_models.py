"""Explicit Luau record contracts and named Lua table literals, read through tree-sitter in Python."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from tree_sitter import Node

from dry_lint.luau import CONTEXT_LIMIT, METAMETHODS, LuauExtractor, dotted, has_syntax_error, text
from dry_lint.model_shapes import model_unit
from dry_lint.models import Declaration, Function, qualified
from dry_lint.source_context import identifiers, with_comments

METADATA = METAMETHODS | {"__mode", "__metatable", "__type"}


@dataclass(frozen=True)
class Definition:
    name: str
    namespace: Literal["type", "table"]
    statement: Node
    value: Node


def definitions(root: Node) -> Iterator[Definition]:
    """Top-level bindings only; references are context, never expanded into copied fields."""
    for statement in root.named_children:
        if has_syntax_error(statement):
            continue
        if statement.type == "type_definition":
            name = statement.child_by_field_name("name")
            if name.type == "generic_type":
                name = name.named_children[0]
            if name.type == "identifier":
                value = [child for child in statement.named_children if child.type != "comment"][-1]
                yield Definition(text(name), "type", statement, value)
        elif statement.type == "function_declaration":
            owner, name = dotted(statement.child_by_field_name("name"))
            if name:
                yield Definition(qualified(owner, name), "table", statement, statement)
        else:
            assignment = statement
            if statement.type == "variable_declaration":
                assignment = next((c for c in statement.named_children if c.type == "assignment_statement"), None)
            if assignment is None or assignment.type != "assignment_statement":
                continue
            targets = next(c for c in assignment.named_children if c.type == "variable_list")
            values = next(c for c in assignment.named_children if c.type == "expression_list")
            for target, value in zip(
                targets.children_by_field_name("name"),
                (child for child in values.named_children if child.type != "comment"),
                strict=False,
            ):
                owner, name = dotted(target)
                if name:
                    yield Definition(qualified(owner, name), "table", statement, value)


def literal_key(node: Node) -> str | None:
    """Plain quoted keys are exact; escaped, interpolated and computed keys stay unresolved."""
    if node.type in {"object_field_type", "literal_type"}:
        return literal_key(node.named_children[0])
    if node.type == "string" and text(node.children[0]) in {'"', "'"} and "\\" not in text(node):
        return "".join(text(child) for child in node.named_children)
    return None


def callable_type(node: Node) -> bool:
    if node.type in {"optional_type", "tuple_type"} and len(node.named_children) == 1:
        return callable_type(node.named_children[0])
    return node.type == "function_type"


def type_fields(node: Node) -> dict[str, str]:
    if node.type == "tuple_type" and len(node.named_children) == 1:
        return type_fields(node.named_children[0])
    if node.type == "intersection_type":
        fields: dict[str, str] = {}
        for child in node.named_children:
            for name, annotation in type_fields(child).items():
                fields[name] = f"({fields[name]}) & ({annotation})" if name in fields else annotation
        return fields
    if node.type != "object_type":
        return {}  # Unions, arrays and referenced/inferred shapes are not one explicit record.
    children = [child for child in node.children if child.type != "comment"]
    fields = {}
    # The grammar has flat key ':' type triples, not a property node. Only these triples declare fields.
    for key, colon, annotation in zip(children, children[1:], children[2:], strict=False):
        if colon.type != ":":
            continue
        name = text(key) if key.type == "identifier" else literal_key(key)
        if name is not None and name not in METADATA and not callable_type(annotation):
            fields[name] = text(annotation)
    return fields


def literal_value(node: Node) -> Node:
    while node.type in {"parenthesized_expression", "cast_expression"}:
        node = node.named_children[0]
    return node


def table_fields(node: Node) -> dict[str, str]:
    node = literal_value(node)
    if node.type != "table_constructor":
        return {}  # A factory, require or setmetatable call does not establish a record's fields.
    fields: dict[str, str] = {}
    for field in node.named_children:
        if field.type != "field":
            continue
        key, value = field.child_by_field_name("name"), field.child_by_field_name("value")
        if key is None or value is None:
            continue
        name = text(key) if key.type == "identifier" and field.children[0].type != "[" else literal_key(key)
        if name is None or name in METADATA:
            continue
        if literal_value(value).type == "function_definition":
            fields.pop(name, None)
        else:
            fields[name] = text(value)
    return fields


class LuauModelExtractor(LuauExtractor):
    name = "luau-models"
    version = "1"
    # Model contracts retain annotations, defaults, function members and generic parameters in their hashes.
    preserve_types = True

    def functions(self, path: str, source: str) -> list[Function]:
        root = self.parser.parse(source.encode("utf-8")).root_node
        declared = list(definitions(root))
        references = {node.id: identifiers(node) for node in root.named_children}
        found = []
        for definition in declared:
            fields = (type_fields if definition.namespace == "type" else table_fields)(definition.value)
            if not fields:
                continue
            statement = definition.statement
            needed = references[statement.id]
            dependencies = {d.statement.id for d in declared if d.name.split(".")[0] in needed}
            context = "\n".join(
                with_comments(other)
                for other in root.named_children
                if other != statement
                and (other.id in dependencies or definition.name.split(".")[-1] in references[other.id])
            )[:CONTEXT_LIMIT]
            code = with_comments(statement)
            function = model_unit(
                path,
                definition.name,
                statement.end_point.row + 2 - len(code.splitlines()),
                statement.end_point.row + 1,
                code,
                Declaration(kind="luau", fields=fields),
                source,
                context,
            )
            # Type/value bindings can share a spelling. Brackets cannot collide with a runtime table owner.
            function.owner = f"<{definition.namespace}>"
            found.append(function)
        return found
