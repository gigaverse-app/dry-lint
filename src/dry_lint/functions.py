"""
Python functions, the built-in extractor's unit: where they are, their code, and two fingerprints of it.

Also the language-neutral part: which tracked files are read, and by which extractor.
"""

import ast
import fnmatch
import hashlib
import re
from collections import deque
from collections.abc import Iterator
from pathlib import Path

from dry_lint.git import git
from dry_lint.models import Function
from dry_lint.plugins import Extractor

STOP_WORDS = {
    "self", "cls", "return", "none", "true", "false", "args", "kwargs", "value", "result", "data", "item", "items",
    "get", "list", "dict", "str", "int", "len", "isinstance", "await", "async", "error",
}  # fmt: skip


def words(identifier: str) -> list[str]:
    """Split snake_case, camelCase and acronym boundaries, dropping very short and generic words."""
    identifier = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", identifier)
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", identifier).lower().split("_")
    return [part for part in parts if len(part) > 2 and part not in STOP_WORDS]


def _parse(code: str) -> ast.Module | None:
    lines = code.splitlines()
    indent = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
    try:
        return ast.parse("\n".join(line[indent:] for line in lines))
    except SyntaxError:
        return None


FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def _call_name(node: ast.Call) -> str | None:
    target = node.func
    return target.attr if isinstance(target, ast.Attribute) else target.id if isinstance(target, ast.Name) else None


def _function_node(code: str) -> FunctionNode | None:
    tree = _parse(code)
    first = tree.body[0] if tree and tree.body else None
    return first if isinstance(first, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def _behaviour_nodes(tree: ast.AST) -> Iterator[ast.AST]:
    """Walk executable syntax without letting shared type annotations masquerade as shared behavior."""
    pending = deque([tree])
    while pending:
        node = pending.popleft()
        yield node
        for field, value in ast.iter_fields(node):
            if field in {"annotation", "returns", "type_params"}:
                continue
            if isinstance(value, ast.AST):
                pending.append(value)
            elif isinstance(value, list):
                pending.extend(child for child in value if isinstance(child, ast.AST))


def _field_keys(node: ast.AST) -> Iterator[str]:
    """Preserve schema/option identity across mapping syntaxes without tokenizing arbitrary prose."""
    if isinstance(node, ast.keyword) and node.arg is not None:
        yield node.arg
    elif isinstance(node, ast.Dict):
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                yield key.value
    elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        yield node.slice.value
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"get", "pop", "setdefault", "add_argument"}
        and node.args
    ):
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            yield first.value


def node_tokens(node: FunctionNode) -> list[str]:
    """
    What the function does, as a bag of tokens: the names it calls, the attributes it touches, the words in its
    identifiers, and its control flow. Two functions that solve the same problem share many of these even when
    their structure and names differ, which is what lets dry-lint find re-implementations, not only copies.
    """
    tokens = [f"fn:{word}" for word in words(node.name)] * 2
    for part in (node.args, *node.body):  # neither its annotations nor its decorators
        for child in _behaviour_nodes(part):
            tokens.extend(f"key:{key}" for key in _field_keys(child))
            if isinstance(child, ast.Call):
                leaf = _call_name(child)
                if leaf:
                    tokens.append(f"call:{leaf.lower()}")
                    tokens += [f"w:{word}" for word in words(leaf)]
            elif isinstance(child, ast.Attribute):
                tokens.append(f"attr:{child.attr.lower()}")
            elif isinstance(child, ast.Name):
                tokens += [f"w:{word}" for word in words(child.id)]
            elif isinstance(child, ast.arg):
                tokens += [f"w:{word}" for word in words(child.arg)]
            elif isinstance(child, (ast.For, ast.While)):
                tokens.append("ctl:loop")
            elif isinstance(child, ast.Try):
                tokens.append("ctl:try")
            elif isinstance(child, ast.Await):
                tokens.append("ctl:await")
    return tokens


def node_calls(node: FunctionNode) -> list[str]:
    """
    The names the function calls, in its signature defaults and body: real call nodes, so not its own name, its
    decorators, or mentions in comments and strings. Names only: receivers and imports are not resolved.
    """
    return [name for part in (node.args, *node.body) for child in ast.walk(part)
            if isinstance(child, ast.Call) and (name := _call_name(child))]


def behaviour_tokens(function: Function) -> list[str]:
    """`node_tokens` of a function's code; only its name's words when the code does not parse."""
    node = _function_node(function.code)
    return node_tokens(node) if node else [f"fn:{word}" for word in words(function.name)] * 2


class _Canonical(ast.NodeTransformer):
    """Drop docstrings, annotations and the function's own name; number local names in order of first use."""

    def __init__(self) -> None:
        self.names: dict[str, str] = {}

    def _local(self, name: str) -> str:
        return self.names.setdefault(name, f"v{len(self.names)}")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._function(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
        node.name = "_"
        node.returns = None
        node.decorator_list = []
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
            if isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
        self.generic_visit(node)
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.arg = self._local(node.arg)
        node.annotation = None
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        # Builtins and module-level names are part of what the code does; only rename what it binds itself.
        if isinstance(node.ctx, ast.Store) or node.id in self.names:
            node.id = self._local(node.id)
        return node


def function_calls(function: Function) -> list[str] | None:
    """`node_calls` of a function's code, or None when the code does not parse."""
    node = _function_node(function.code)
    return node_calls(node) if node else None


def structure_hash(function: Function) -> str:
    """
    A hash that changes when the logic changes, and not for comments, docstrings, formatting, decorators, renamed
    local variables or a renamed function. Verdicts are keyed on it, so cosmetic edits never cost a new judgement.
    """
    node = _function_node(function.code)
    if node is None:
        return hashlib.sha256(function.code.encode()).hexdigest()[:16]
    return hashlib.sha256(ast.dump(_Canonical().visit(node), annotate_fields=False).encode()).hexdigest()[:16]


def _is_stub(node: FunctionNode) -> bool:
    """Declaration-only bodies have no implementation to reuse; retain any executable behaviour."""
    for statement in node.body:
        if isinstance(statement, ast.Pass):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            if isinstance(statement.value.value, str) or statement.value.value is Ellipsis:
                continue
        if isinstance(statement, ast.Raise) and statement.cause is None:
            exception = statement.exc
            if isinstance(exception, ast.Call) and not exception.args and not exception.keywords:
                exception = exception.func
            if isinstance(exception, ast.Name) and exception.id == "NotImplementedError":
                continue
        return False
    return True


def function_nodes(source: str, path: str, min_lines: int = 2) -> list[tuple[Function, FunctionNode]]:
    """
    Top-level functions and methods, with their syntax trees (nested functions stay part of their parent).
    Declaration-only stubs are left out: they otherwise dominate exact-match rankings and use up judge calls.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    found: list[tuple[Function, FunctionNode]] = []

    def visit(node: ast.AST, owner: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = child.end_lineno or child.lineno
                if end - child.lineno + 1 >= min_lines and not _is_stub(child):
                    found.append((Function(path=path, name=child.name, owner=owner, line=child.lineno, end_line=end,
                                           code="\n".join(lines[child.lineno - 1 : end])), child))

    visit(tree, None)
    return found


def selected_path(path: str, include: list[str], exclude: list[str]) -> bool:
    return (any(fnmatch.fnmatch(path, pattern) for pattern in include)
            and not any(fnmatch.fnmatch(path, pattern) for pattern in exclude))


def tracked_files(root: Path, include: list[str], exclude: list[str]) -> list[str]:
    listed = git(root, "ls-files", "-z")
    return [
        path for path in listed.split("\0")
        if path and selected_path(path, include, exclude)
    ]  # fmt: skip


def extractor_for(path: str, extractors: list[Extractor]) -> Extractor | None:
    """The first extractor whose globs match the path."""
    return next((e for e in extractors if any(fnmatch.fnmatch(path, glob) for glob in e.files)), None)


def repository_functions(root: Path, include: list[str], exclude: list[str], extractors: list[Extractor]) -> list[Function]:
    """Every function in the tracked files, each file read by its extractor."""
    found: list[Function] = []
    for path in tracked_files(root, include, exclude):
        extractor = extractor_for(path, extractors)
        if extractor is None:
            continue
        try:
            found += extractor.functions(path, (root / path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return found
