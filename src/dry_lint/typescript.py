"""TypeScript and TSX implementations, parsed without executing repository code."""

import hashlib
import json
import posixpath
import re
from collections.abc import Iterator

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from dry_lint.extractors import local_calls
from dry_lint.functions import words
from dry_lint.models import Function, LanguageAnalysis, module_of, qualified
from dry_lint.source_context import SourceContext

FUNCTIONS = {
    "function_declaration",
    "function_expression",
    "generator_function_declaration",
    "generator_function",
    "arrow_function",
    "method_definition",
}
TYPE_ONLY = {
    "type_annotation",
    "type_parameters",
    "type_arguments",
    "interface_declaration",
    "type_alias_declaration",
    "ambient_declaration",
    "implements_clause",
}
CONTROLS = {
    "for_statement": "loop",
    "for_in_statement": "loop",
    "while_statement": "loop",
    "do_statement": "loop",
    "try_statement": "try",
    "await_expression": "await",
}


def text(node: Node) -> str:
    return node.text.decode("utf-8")


def jsx_text_error(node: Node) -> bool:
    """tree-sitter-typescript misreads bare ampersands in valid JSX text as incomplete entities."""
    return (
        node.is_error
        and node.parent is not None
        and node.parent.type == "jsx_element"
        and re.fullmatch(r"&[^<>{}]*", text(node)) is not None
    )


def has_syntax_error(node: Node) -> bool:
    if not node.has_error or jsx_text_error(node):
        return False
    if node.is_error:
        return True
    return node.is_missing or any(has_syntax_error(child) for child in node.children)


def behavior(node: Node) -> Iterator[Node]:
    if node.type in TYPE_ONLY or node.type == "comment" or jsx_text_error(node):
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


def direct_call(node: Node) -> str | None:
    """`name` for a bare call, `this.name` for one on the object itself; None for any other receiver."""
    target = node.child_by_field_name("function") or node.child_by_field_name("constructor")
    assert target is not None
    if target.type == "identifier":
        return text(target)
    receiver, prop = target.child_by_field_name("object"), target.child_by_field_name("property")
    if target.type == "member_expression" and receiver is not None and receiver.type == "this" and prop is not None:
        return f"this.{text(prop)}"
    return None


def fingerprint(node: Node, name: str) -> tuple[list[str], list[str]]:
    """Behaviour tokens, and the direct calls (see `direct_call`): a call on another receiver proves no delegation."""
    # dry-lint: distinct-from src/dry_lint/functions.py::node_tokens
    tokens = [f"fn:{word}" for word in words(name)] * 2
    calls = []
    for child in behavior(node):
        if child.type in {"call_expression", "new_expression"}:
            if direct := direct_call(child):
                calls.append(direct)
            leaf = call_name(child)
            if leaf:
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


def canonical(node: Node, *, preserve_types: bool = False):
    if (not preserve_types and node.type in TYPE_ONLY) or node.type in {"comment", ";"}:
        return None
    if not node.children:
        return (node.type, text(node))
    return (
        node.type,
        [value for child in node.children if (value := canonical(child, preserve_types=preserve_types)) is not None],
    )


class Bases:
    """
    A class's `extends` base as a `module::Class` reference, resolved from the file alone: a class declared in it, or
    a name or namespace a relative import binds. A package import, a mixin call or any other expression is left out.
    """

    def __init__(self, root: Node, path: str) -> None:
        self.module = module_of(path)
        self.classes: set[str] = set()
        self.names: dict[str, str] = {}  # import {B as C} from './a' -> C: a::B; import * as m from './a' -> m: a
        folder = posixpath.dirname(path)
        pending = [root]
        while pending:
            node = pending.pop()
            pending.extend(node.named_children)
            name = node.child_by_field_name("name")
            if node.type in {"class_declaration", "abstract_class_declaration"} and name is not None:
                self.classes.add(text(name))
        for statement in root.named_children:
            source, clause = (
                statement.child_by_field_name("source"),
                next((child for child in statement.named_children if child.type == "import_clause"), None),
            )
            specifier = text(source).strip("'\"") if statement.type == "import_statement" and source else ""
            module = re.sub(r"\.[cm]?[jt]sx?$", "", posixpath.normpath(posixpath.join(folder, specifier)))
            module = module.removesuffix("/index")
            if not specifier.startswith(".") or module.startswith("..") or clause is None:
                continue
            for child in clause.named_children:
                if child.type == "identifier":  # import Base from './a': the default export, by its local name
                    self.names[text(child)] = f"{module}::{text(child)}"
                elif child.type == "namespace_import":
                    self.names[text(child.named_children[0])] = module
                else:
                    for imported in child.named_children:
                        name, alias = imported.child_by_field_name("name"), imported.child_by_field_name("alias")
                        self.names[text(alias or name)] = f"{module}::{text(name)}"

    def of(self, node: Node) -> list[str]:
        heritage = next((child for child in node.named_children if child.type == "class_heritage"), None)
        clause = heritage and next((child for child in heritage.named_children if child.type == "extends_clause"), None)
        value = clause and clause.child_by_field_name("value")
        if value is None:
            return []
        if value.type == "identifier":
            name = text(value)
            reference = f"{self.module}::{name}" if name in self.classes else self.names.get(name, "")
            return [reference] if "::" in reference else []
        receiver, prop = value.child_by_field_name("object"), value.child_by_field_name("property")
        if value.type == "member_expression" and receiver is not None and receiver.type == "identifier":
            module = self.names.get(text(receiver), "")
            return [f"{module}::{text(prop)}"] if module and "::" not in module else []
        return []


def forwarding_method(node: Node, code: Node, body: Node) -> str | None:
    """Recognize class methods/arrow fields containing only this.method(parameters), without evaluating code."""
    previous = code.prev_named_sibling
    while previous is not None and previous.type == "comment":
        previous = previous.prev_named_sibling
    if (
        code.parent is None
        or code.parent.type != "class_body"
        or any(child.type == "decorator" for child in code.named_children)
        or previous is not None
        and previous.type == "decorator"
    ):
        return None
    if node.type not in {"method_definition", "arrow_function"}:
        return None  # object methods and function-valued fields have different receiver binding
    name = node.child_by_field_name("name")
    if name is not None and text(name) == "constructor":
        return None  # parameter properties and construction can add behavior outside the body
    if code.type == "public_field_definition" and code.child_by_field_name("value") != node:
        return None  # debounce/memo/etc. wrap the arrow with additional executable behavior
    if body.type == "statement_block":
        statements = [child for child in body.named_children if child.type != "comment"]
        if len(statements) != 1 or statements[0].type not in {"return_statement", "expression_statement"}:
            return None
        expressions = [child for child in statements[0].named_children if child.type != "comment"]
        if len(expressions) != 1:
            return None
        body = expressions[0]
    if body.type == "await_expression":
        body = body.named_children[0]
    if body.type != "call_expression":
        return None
    target, arguments = body.child_by_field_name("function"), body.child_by_field_name("arguments")
    if target is None or target.type != "member_expression" or arguments is None:
        return None
    if any(child.type in {"?.", "optional_chain"} for parent in (body, target) for child in parent.children):
        return None
    receiver, prop = target.child_by_field_name("object"), target.child_by_field_name("property")
    if receiver is None or receiver.type != "this" or prop is None or prop.type != "property_identifier":
        return None
    # A computed argument can contain the very repeated operation we are trying to detect.
    parameters = node.child_by_field_name("parameters")
    if parameters is not None and any(
        param.child_by_field_name("value") is not None for param in parameters.named_children
    ):
        return None
    names: set[str] = (
        {
            text(pattern)
            for param in parameters.named_children
            if (pattern := param.child_by_field_name("pattern")) is not None and pattern.type == "identifier"
        }
        if parameters is not None
        else set()
    )
    if any(
        arg.type != "identifier" or text(arg) not in names for arg in arguments.named_children if arg.type != "comment"
    ):
        return None
    return text(prop)


class TypeScriptExtractor:
    name = "typescript"
    version = "3"
    files = ("*.ts", "*.tsx", "*.mts", "*.cts")

    def __init__(self, min_lines: int = 1) -> None:
        self.min_lines = min_lines
        self.parsers = {
            "ts": Parser(Language(tree_sitter_typescript.language_typescript())),
            "tsx": Parser(Language(tree_sitter_typescript.language_tsx())),
        }

    def parser(self, path: str) -> Parser:
        return self.parsers["tsx" if path.endswith(".tsx") else "ts"]

    def validate_source(self, path: str, source: str) -> None:
        if has_syntax_error(self.parser(path).parse(source.encode("utf-8")).root_node):
            raise ValueError(f"Cannot completely scan {path}: TypeScript parse error")

    def functions(self, path: str, source: str) -> list[Function]:
        if path.endswith((".d.ts", ".d.mts", ".d.cts")):
            return []
        root = self.parser(path).parse(source.encode("utf-8")).root_node
        context = SourceContext(root)
        context_digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        bases = Bases(root, path)
        found = []
        classes: set[str] = set()

        def add(node: Node, code: Node, name: str, owner: str | None, inherits: tuple[str, ...]) -> None:
            body = node.child_by_field_name("body")
            if has_syntax_error(node) or body is None:
                return
            if body.type == "statement_block" and not any(child.type != "comment" for child in body.named_children):
                return
            if code.end_point.row - code.start_point.row + 1 < self.min_lines:
                return
            tokens, calls = fingerprint(node, name)
            snippet = text(code)
            if code.type == "variable_declarator":
                snippet = "const " + snippet + ";"
            target = forwarding_method(node, code, body)
            found.append(
                Function(
                    path=path,
                    name=name,
                    owner=owner,
                    line=code.start_point.row + 1,
                    end_line=code.end_point.row + 1,
                    code=snippet,
                    tokens=tokens,
                    calls=calls,
                    context=context.for_function(code),
                    context_digest=context_digest,
                    bases=list(inherits),
                    analysis=LanguageAnalysis(
                        language=self.name,
                        version=self.version,
                        forward_target=f"{path}::{qualified(owner, target)}" if target else None,
                        declared_override=any(
                            child.type == "override_modifier" or child.type == "override" for child in code.children
                        ),
                    ),
                )
            )

        def visit(node: Node, owner: str | None = None, inherits: tuple[str, ...] = ()) -> None:
            if node.type in TYPE_ONLY:
                return
            name_node = node.child_by_field_name("name")
            if node.type in {"class_declaration", "abstract_class_declaration", "class"}:
                inherits = tuple(bases.of(node))
            elif node.type in {"internal_module", "object"}:
                inherits = ()
            if node.type in {"method_definition", "public_field_definition"} and any(
                child.type == "static" for child in node.children
            ):
                owner = f"{owner}.static" if owner else "static"
                inherits = tuple(f"{reference}.static" for reference in inherits)
            if node.type in FUNCTIONS:
                name = text(name_node) if name_node is not None else "default"
                if node.type == "method_definition":
                    modifiers = {child.type for child in node.children if not child.is_named}
                    if "get" in modifiers or "set" in modifiers:
                        name = ("get " if "get" in modifiers else "set ") + name
                if name_node is not None or (node.parent is not None and node.parent.type == "export_statement"):
                    add(node, node, name, owner, inherits)
                return
            if node.type in {"variable_declarator", "public_field_definition", "pair"}:
                name_node = name_node or node.child_by_field_name("key")
                value = node.child_by_field_name("value")
                if name_node is not None and value is not None:
                    name = text(name_node).strip("\"'")
                    function = callable_value(value)
                    if function is not None:
                        add(function, node, name, owner, inherits)
                        return
                    if value.type in {"object", "class"}:
                        visit(value, ".".join(part for part in (owner, name) if part), inherits)
                        return
            if node.type in {"class_declaration", "abstract_class_declaration", "internal_module"}:
                if name_node is not None:
                    owner = ".".join(part for part in (owner, text(name_node)) if part)
                    if node.type != "internal_module":
                        classes.add(owner)
            for child in node.named_children:
                visit(child, owner, inherits)

        visit(root)
        # Only class methods bind `this` to their owner; object-literal fields and bare calls stay unresolved.
        defined = {qualified(function.owner, function.name) for function in found}
        for function in found:
            if function.owner in classes and function.analysis is not None:
                function.analysis.local_calls = local_calls(path, function, defined, ("this",))
        return found

    preserve_types = False  # Declaration extractors retain type syntax in the shared hashing path.

    def structure_hash(self, function: Function) -> str:
        parser = self.parser(function.path)
        root = parser.parse(function.code.encode("utf-8")).root_node
        if has_syntax_error(root):
            root = parser.parse(("class __DryLint {\n" + function.code + "\n}").encode("utf-8")).root_node
        # Keep binding names: lexical shadowing and shorthand keys can make a rename change behavior.
        payload = json.dumps(
            canonical(root, preserve_types=self.preserve_types), ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(("typescript:1:" + payload).encode("utf-8")).hexdigest()[:16]
