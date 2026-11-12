"""The Luau (Roblox) extractor, parsed with tree-sitter and never executed."""

import hashlib
import json
from collections.abc import Iterator

from tree_sitter import Language, Node, Parser

from dry_lint.extractors import local_calls
from dry_lint.functions import words
from dry_lint.models import Function, LanguageAnalysis, qualified

FUNCTIONS = {"function_declaration", "function_definition"}
# Types are erased at runtime: they never count as behaviour, and never change a structure hash.
TYPE_ONLY = {
    "builtin_type",
    "empty_type",
    "field_type",
    "function_type",
    "generic_type",
    "generic_type_list",
    "intersection_type",
    "literal_type",
    "object_field_type",
    "object_type",
    "optional_type",
    "tuple_type",
    "type_definition",
    "union_type",
    "variadic_type",
}
LOOPS = {"for_statement", "while_statement", "repeat_statement"}
# Luau has no `try`: protected calls are the error handling. It has no `await` either; these calls yield the thread.
PROTECTED = {"pcall", "xpcall"}
YIELDING = {"wait", "yield", "Wait"}
CONTEXT_LIMIT = 8000
# Callable Luau metamethods (VM/src/ltm.cpp and VM/src/lbaselib.cpp upstream).
# Metadata keys such as __mode/__metatable and arbitrary __private names are not method conventions.
METAMETHODS = {
    "__index",
    "__newindex",
    "__namecall",
    "__call",
    "__iter",
    "__len",
    "__eq",
    "__add",
    "__sub",
    "__mul",
    "__div",
    "__idiv",
    "__mod",
    "__pow",
    "__unm",
    "__lt",
    "__le",
    "__concat",
    "__tostring",
}


def text(node: Node) -> str:
    return node.text.decode("utf-8")


def has_syntax_error(node: Node) -> bool:
    if not node.has_error:
        return False
    if node.is_error or node.is_missing:
        return True
    return any(has_syntax_error(child) for child in node.children)


def runtime_children(node: Node) -> list[Node]:
    """Erase annotations by grammar position: a named type can itself be an ordinary identifier node."""
    if node.type in {"parameter", "cast_expression"}:
        return node.named_children[:1]  # The binding/expression precedes its optional type.
    if node.type in FUNCTIONS:
        return [
            child
            for index, child in enumerate(node.children)
            if node.field_name_for_child(index) in {"name", "parameters", "body"}
            or not child.is_named
            and child.type != ":"
        ]
    if node.type == "variable_list":
        return [
            child
            for index, child in enumerate(node.children)
            if node.field_name_for_child(index) == "name" or child.type == ","
        ]
    return node.children


def behavior(node: Node) -> Iterator[Node]:
    """The nodes that carry behaviour: no comments, no type syntax, no parameter or return annotations."""
    if node.type in TYPE_ONLY or node.type == "comment":
        return
    yield node
    if node.type in FUNCTIONS:
        children = [child for field in ("parameters", "body") if (child := node.child_by_field_name(field))]
    else:
        children = [child for child in runtime_children(node) if child.is_named]
    for child in children:
        yield from behavior(child)


def callee(node: Node) -> tuple[str | None, str | None]:
    """Call tokens: only an identifier receiver is returned; None also covers unresolved complex receivers."""
    target = node.child_by_field_name("name")
    if target.type == "identifier":
        return None, text(target)
    prefix = target.child_by_field_name("table")
    leaf = target.child_by_field_name("field") or target.child_by_field_name("method")
    if target.type in {"dot_index_expression", "method_index_expression"} and leaf is not None:
        receiver = text(prefix) if prefix is not None and prefix.type == "identifier" else None
        return receiver, text(leaf)
    return None, None


def first_string(node: Node) -> str | None:
    """The literal first argument of a call, as `GetService("Players")` and `Instance.new("Part")` carry it."""
    arguments = node.child_by_field_name("arguments")
    first = arguments.named_children[0] if arguments is not None and arguments.named_children else None
    content = None if first is None or first.type != "string" else first.named_children
    return text(content[0]).lower() if content else None


def fingerprint(node: Node, name: str) -> tuple[list[str], list[str]]:
    """Behaviour tokens, and the direct calls (`f`, `self.m`, `Owner.m`); a call on another receiver is not one."""
    # dry-lint: distinct-from src/dry_lint/typescript.py::fingerprint
    tokens = [f"fn:{word}" for word in words(name)] * 2
    calls = []
    for child in behavior(node):
        if child.type == "function_call":
            receiver, leaf = callee(child)
            if leaf is None:
                continue
            bare = child.child_by_field_name("name").type == "identifier"
            # INVARIANT: an unresolved receiver must never become evidence of a bare local call.
            if receiver is not None or bare:
                calls.append(f"{receiver}.{leaf}" if receiver else leaf)
            tokens.append(f"call:{leaf.lower()}")
            tokens.extend(f"w:{word}" for word in words(leaf))
            if leaf == "GetService" and (service := first_string(child)):
                tokens.append(f"service:{service}")
            elif receiver == "Instance" and leaf == "new" and (kind := first_string(child)):
                tokens.append(f"instance:{kind}")
            if bare and leaf in PROTECTED:
                tokens.append("ctl:try")
            if leaf in YIELDING:
                tokens.append("ctl:await")
        elif child.type == "dot_index_expression":
            tokens.append(f"attr:{text(child.child_by_field_name('field')).lower()}")
        elif child.type == "identifier":
            tokens.extend(f"w:{word}" for word in words(text(child)))
        elif child.type == "field":
            key = child.child_by_field_name("name")
            if key is not None:
                tokens.append(f"key:{text(key).strip(chr(34) + chr(39))}")
        if child.type in LOOPS:
            tokens.append("ctl:loop")
    return tokens, calls


def canonical(node: Node):
    if node.type in TYPE_ONLY or node.type in {"comment", ";", "empty_statement"}:
        return None
    if node.type == "cast_expression":
        return canonical(runtime_children(node)[0])
    if not node.children:
        return (node.type, text(node))
    return (node.type, [value for child in runtime_children(node) if (value := canonical(child)) is not None])


def bindings(node: Node) -> set[str]:
    """Names a function binds itself: parameters, locals, loop variables and nested functions."""
    names: set[str] = set()
    for child in behavior(node):
        parent = child.parent
        if child.type == "parameter" and child.named_children:
            names.add(text(child.named_children[0]))
        elif child.type == "variable_list" and parent is not None:
            # Reassignments also invalidate receiver evidence, even when they are not new local declarations.
            names.update(text(name) for name in runtime_children(child) if name.type == "identifier")
        elif child.type == "for_numeric_clause":
            names.add(text(child.child_by_field_name("name")))
        elif child.type == "function_declaration" and child != node:
            name = child.child_by_field_name("name")
            if name.type == "identifier":
                names.add(text(name))
    return names


def forwarding_method(node: Node, owner: str | None) -> str | None:
    """A `function Owner:name(...)` whose whole body is `self:other(...)` over unchanged parameters, nothing else."""
    declared = node.child_by_field_name("name")
    body = node.child_by_field_name("body")
    parameters = node.child_by_field_name("parameters")
    if owner is None or declared is None or declared.type != "method_index_expression" or body is None:
        return None
    if parameters is None or any(
        param.type != "parameter" or not param.named_children or param.named_children[0].type != "identifier"
        for param in parameters.named_children
    ):
        return None  # varargs and other forms can add behaviour the parameter list does not show
    statements = [child for child in body.named_children if child.type != "comment"]
    if len(statements) != 1:
        return None
    statement = statements[0]
    if statement.type == "return_statement":
        values = [child for expression in statement.named_children for child in expression.named_children]
        statement = values[0] if len(values) == 1 else statement
    if statement.type != "function_call":
        return None
    target = statement.child_by_field_name("name")
    arguments = statement.child_by_field_name("arguments")
    if target is None or arguments is None or target.type != "method_index_expression":
        return None
    receiver, method = target.child_by_field_name("table"), target.child_by_field_name("method")
    if receiver is None or text(receiver) != "self" or method is None:
        return None
    names = {text(param.named_children[0]) for param in parameters.named_children}
    # A computed argument can contain the very repeated operation we are trying to detect.
    if any(argument.type != "identifier" or text(argument) not in names for argument in arguments.named_children):
        return None
    return text(method)


def dotted(node: Node) -> tuple[str | None, str | None]:
    """`(owner, name)` of an assignment target: `Module.new` is (Module, new); `f` is (None, f); others are unnamed."""
    if node.type == "identifier":
        return None, text(node)
    if node.type in {"dot_index_expression", "method_index_expression"}:
        table = node.child_by_field_name("table")
        leaf = node.child_by_field_name("field") or node.child_by_field_name("method")
        if table is not None and leaf is not None:
            parent, name = dotted(table)
            if name is not None:
                return qualified(parent, name), text(leaf)
    return None, None


def literal_key(node: Node) -> str | None:
    """Resolve plain quoted keys only; escaped/interpolated/computed keys remain unknown."""
    if node.type in {"object_field_type", "literal_type"}:
        return literal_key(node.named_children[0])
    if node.type == "string" and text(node.children[0]) in {'"', "'"} and "\\" not in text(node):
        return "".join(text(child) for child in node.named_children)
    return None


def table_key(field: Node) -> str | None:
    key = field.child_by_field_name("name")
    if key is None:
        return None
    if key.type == "identifier" and field.children[0].type != "[":
        return text(key)
    # INVARIANT: [key] evaluates a variable; its spelling never establishes a named callable or data field.
    return literal_key(key)


class Requirements:
    """Top-level `local X = require(...)` and `game:GetService(...)` lines: what a judge needs to know X is."""

    def __init__(self, root: Node) -> None:
        self.lines: dict[str, str] = {}
        for statement in root.named_children:
            if statement.type != "variable_declaration":
                continue
            assignment = next((c for c in statement.named_children if c.type == "assignment_statement"), None)
            if assignment is None:
                continue
            names = [c for c in assignment.named_children if c.type == "variable_list"]
            values = [c for c in assignment.named_children if c.type == "expression_list"]
            value = values[0].named_children[0]
            leaf = callee(value)[1] if value.type == "function_call" else None
            if leaf in {"require", "GetService"}:
                for name in runtime_children(names[0]):
                    if name.type == "identifier":
                        self.lines[text(name)] = text(statement)

    def for_function(self, node: Node) -> str:
        used = {text(child) for child in behavior(node) if child.type == "identifier"}
        context = "\n".join(dict.fromkeys(line for name, line in self.lines.items() if name in used))
        return context[:CONTEXT_LIMIT]


class LuauExtractor:
    """Functions and methods of at least `min_lines` lines; nested functions stay part of their parent."""

    name = "luau"
    version = "3"
    files = ("*.luau", "*.lua")

    def __init__(self, min_lines: int = 2) -> None:
        self.min_lines = min_lines
        try:
            import tree_sitter_luau
        except ImportError as error:  # pragma: no cover - exercised only without the extra installed
            raise ImportError("The luau extractor needs tree-sitter-luau: pip install 'dry-lint[luau]'") from error
        self.parser = Parser(Language(tree_sitter_luau.language()))

    def validate_source(self, path: str, source: str) -> None:
        if has_syntax_error(self.parser.parse(source.encode("utf-8")).root_node):
            raise ValueError(f"Cannot completely scan {path}: Luau parse error")

    def functions(self, path: str, source: str) -> list[Function]:
        root = self.parser.parse(source.encode("utf-8")).root_node
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        requirements = Requirements(root)
        found: list[tuple[Function, Node]] = []

        def add(node: Node, code: Node, name: str | None, owner: str | None) -> None:
            body = node.child_by_field_name("body")
            if name is None or has_syntax_error(node) or body is None:
                return
            if code.end_point.row - code.start_point.row + 1 < self.min_lines:
                return
            tokens, calls = fingerprint(node, name)
            found.append(
                (
                    Function(
                        path=path,
                        name=name,
                        owner=owner,
                        line=code.start_point.row + 1,
                        end_line=code.end_point.row + 1,
                        code=text(code),
                        tokens=tokens,
                        calls=calls,
                        context=requirements.for_function(node),
                        context_digest=digest,
                    ),
                    node,
                )
            )

        def assign(names: list[Node], values: list[Node], statement: Node) -> None:
            for target, value in zip(names, values, strict=False):
                owner, name = dotted(target)
                if name is None:
                    continue
                if value.type == "function_definition":
                    # `local f = function ... end` is one statement; its source is the function's code.
                    add(value, statement if len(values) == 1 else value, name, owner)
                elif value.type == "table_constructor":
                    members(value, ".".join(part for part in (owner, name) if part))

        def members(table: Node, owner: str | None) -> None:
            for field in table.named_children:
                key, value = field.child_by_field_name("name"), field.child_by_field_name("value")
                if field.type != "field" or key is None or value is None:
                    continue
                name = table_key(field)
                if name is None:
                    continue
                if value.type == "function_definition":
                    add(value, field, name, owner)
                elif value.type == "table_constructor":
                    members(value, ".".join(part for part in (owner, name) if part))

        def visit(node: Node) -> None:
            if node.type == "function_declaration":
                target = node.child_by_field_name("name")
                owner, name = dotted(target)
                add(node, node, name, owner)
                return  # a nested function is part of its parent
            if node.type == "function_definition":
                return  # an anonymous function is part of whatever receives it
            if node.type == "assignment_statement":
                parent = node.parent
                statement = parent if parent is not None and parent.type == "variable_declaration" else node
                targets, values = (
                    [n for c in node.named_children if c.type == kind for n in runtime_children(c) if n.is_named]
                    for kind in ("variable_list", "expression_list")
                )
                assign(targets, values, statement)
                return
            for child in node.named_children:
                visit(child)

        visit(root)
        defined = {qualified(function.owner, function.name) for function, _ in found}
        functions = []
        for function, node in found:
            bound = bindings(node)
            target = forwarding_method(node, function.owner) if "self" not in bound else None
            declared = node.child_by_field_name("name")
            method = declared is not None and declared.type == "method_index_expression"
            # Only colon declarations bind self; any local/parameter/reassignment makes a receiver uncertain.
            receivers = tuple(
                receiver
                for receiver in ("self" if method else None, function.owner)
                if receiver is not None and receiver.split(".")[0] not in bound
            )
            function.analysis = LanguageAnalysis(
                language=self.name,
                version=self.version,
                convention="luau-metamethod" if function.owner and function.name in METAMETHODS else None,
                forward_target=f"{path}::{qualified(function.owner, target)}" if target else None,
                local_calls=local_calls(path, function, defined, receivers, bound),
            )
            functions.append(function)
        return functions

    def structure_hash(self, function: Function) -> str:
        root = self.parser.parse(function.code.encode("utf-8")).root_node
        if has_syntax_error(root):
            root = self.parser.parse(("local __DryLint = {\n" + function.code + "\n}").encode("utf-8")).root_node
        # Keep binding names: lexical shadowing can make a rename change behaviour, so a rename is judged again.
        payload = json.dumps(canonical(root), ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256((f"luau:{self.version}:" + payload).encode("utf-8")).hexdigest()[:16]
