"""TypeScript and TSX implementations, parsed without executing repository code."""

import hashlib
import json
from collections.abc import Iterator

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from dry_lint.functions import words
from dry_lint.models import Function

FUNCTIONS = {"function_declaration", "function_expression", "generator_function_declaration",
             "generator_function", "arrow_function", "method_definition"}
TYPE_ONLY = {"type_annotation", "type_parameters", "type_arguments", "interface_declaration",
             "type_alias_declaration", "ambient_declaration", "implements_clause"}
CONTROLS = {"for_statement": "loop", "for_in_statement": "loop", "while_statement": "loop",
            "do_statement": "loop", "try_statement": "try", "await_expression": "await"}


def text(node: Node) -> str:
    return node.text.decode("utf-8")


def behavior(node: Node) -> Iterator[Node]:
    if node.type in TYPE_ONLY or node.type == "comment":
        return
    yield node
    for child in node.named_children:
        yield from behavior(child)


def call_name(node: Node) -> str | None:
    target = node.child_by_field_name("function") or node.child_by_field_name("constructor")
    assert target is not None
    if target.type == "member_expression":
        target = target.child_by_field_name("property")
    return text(target) if target is not None and target.type in {"identifier", "property_identifier"} else None


def fingerprint(node: Node, name: str) -> tuple[list[str], list[str]]:
    # dry-lint: distinct-from src/dry_lint/functions.py::node_tokens
    tokens = [f"fn:{word}" for word in words(name)] * 2
    calls = []
    for child in behavior(node):
        if child.type in {"call_expression", "new_expression"}:
            leaf = call_name(child)
            if leaf:
                calls.append(leaf)
                tokens.append(f"call:{leaf.lower()}")
                tokens.extend(f"w:{word}" for word in words(leaf))
        elif child.type == "member_expression":
            prop = child.child_by_field_name("property")
            if prop is not None:
                tokens.append(f"attr:{text(prop).lower()}")
        elif child.type in {"identifier", "shorthand_property_identifier", "shorthand_property_identifier_pattern"}:
            tokens.extend(f"w:{word}" for word in words(text(child)))
        elif child.type == "pair":
            key = child.child_by_field_name("key")
            if key is not None and key.type in {"property_identifier", "string"}:
                tokens.append(f"key:{text(key).strip(chr(34) + chr(39))}")
        elif child.type in {"jsx_opening_element", "jsx_self_closing_element"}:
            tag = child.child_by_field_name("name")
            if tag is not None:
                tokens.append(f"jsx:{text(tag)}")
        if child.type in CONTROLS:
            tokens.append(f"ctl:{CONTROLS[child.type]}")
    return tokens, calls


def callable_value(node: Node) -> Node | None:
    if node.type in FUNCTIONS:
        return node
    if node.type in {"parenthesized_expression", "as_expression", "satisfies_expression"}:
        return callable_value(node.named_children[0])
    if node.type == "call_expression" and call_name(node) in {"memo", "forwardRef", "debounce", "throttle"}:
        arguments = node.child_by_field_name("arguments")
        if arguments is not None:
            functions = [found for arg in arguments.named_children if (found := callable_value(arg)) is not None]
            if len(functions) == 1:
                return functions[0]
    return None


def canonical(node: Node):
    if node.type in TYPE_ONLY or node.type in {"comment", ";"}:
        return None
    if not node.children:
        return (node.type, text(node))
    return (node.type, [value for child in node.children if (value := canonical(child)) is not None])


class TypeScriptExtractor:
    name = "typescript"
    version = "1"
    files = ("*.ts", "*.tsx", "*.mts", "*.cts")

    def __init__(self, min_lines: int = 1) -> None:
        self.min_lines = min_lines
        self.parsers = {
            "ts": Parser(Language(tree_sitter_typescript.language_typescript())),
            "tsx": Parser(Language(tree_sitter_typescript.language_tsx())),
        }

    def parser(self, path: str) -> Parser:
        return self.parsers["tsx" if path.endswith(".tsx") else "ts"]

    def functions(self, path: str, source: str) -> list[Function]:
        if path.endswith((".d.ts", ".d.mts", ".d.cts")):
            return []
        root = self.parser(path).parse(source.encode("utf-8")).root_node
        found = []

        def add(node: Node, code: Node, name: str, owner: str | None) -> None:
            body = node.child_by_field_name("body")
            if node.has_error or body is None:
                return
            if body.type == "statement_block" and not any(child.type != "comment" for child in body.named_children):
                return
            if code.end_point.row - code.start_point.row + 1 < self.min_lines:
                return
            tokens, calls = fingerprint(node, name)
            snippet = text(code)
            if code.type == "variable_declarator":
                snippet = "const " + snippet + ";"
            found.append(Function(path=path, name=name, owner=owner, line=code.start_point.row + 1,
                                  end_line=code.end_point.row + 1, code=snippet, tokens=tokens, calls=calls))

        def visit(node: Node, owner: str | None = None) -> None:
            if node.type in TYPE_ONLY:
                return
            name_node = node.child_by_field_name("name")
            if node.type in FUNCTIONS:
                name = text(name_node) if name_node is not None else "default"
                if node.type == "method_definition":
                    modifiers = {child.type for child in node.children if not child.is_named}
                    if "get" in modifiers or "set" in modifiers:
                        name = ("get " if "get" in modifiers else "set ") + name
                    if "static" in modifiers:
                        owner = f"{owner}.static" if owner else "static"
                if name_node is not None or (node.parent is not None and node.parent.type == "export_statement"):
                    add(node, node, name, owner)
                return
            if node.type in {"variable_declarator", "public_field_definition", "pair"}:
                name_node = name_node or node.child_by_field_name("key")
                value = node.child_by_field_name("value")
                if name_node is not None and value is not None:
                    name = text(name_node).strip("\"'")
                    function = callable_value(value)
                    if function is not None:
                        add(function, node, name, owner)
                        return
                    if value.type in {"object", "class"}:
                        visit(value, ".".join(part for part in (owner, name) if part))
                        return
            if node.type in {"class_declaration", "abstract_class_declaration", "internal_module"}:
                if name_node is not None:
                    owner = ".".join(part for part in (owner, text(name_node)) if part)
            for child in node.named_children:
                visit(child, owner)

        visit(root)
        return found

    def structure_hash(self, function: Function) -> str:
        parser = self.parser(function.path)
        root = parser.parse(function.code.encode("utf-8")).root_node
        if root.has_error:
            root = parser.parse(("class __DryLint {\n" + function.code + "\n}").encode("utf-8")).root_node
        # Keep binding names: lexical shadowing and shorthand keys can make a rename change behavior.
        payload = json.dumps(canonical(root), ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(("typescript:1:" + payload).encode("utf-8")).hexdigest()[:16]
