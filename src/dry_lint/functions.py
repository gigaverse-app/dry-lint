"""
Python functions, the built-in extractor's unit: where they are, their code, and two fingerprints of it.

Also the language-neutral part: which tracked files are read, and by which extractor.
"""

import ast
import fnmatch
import hashlib
import re
import subprocess
from pathlib import Path

from dry_lint.models import Function
from dry_lint.plugins import Extractor

STOP_WORDS = {
    "self", "cls", "return", "none", "true", "false", "args", "kwargs", "value", "result", "data", "item", "items",
    "get", "list", "dict", "str", "int", "len", "isinstance", "await", "async", "error",
}  # fmt: skip


def words(identifier: str) -> list[str]:
    """Split snake_case and camelCase into lower-case words, dropping very short and generic ones."""
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


def _function_node(code: str) -> FunctionNode | None:
    tree = _parse(code)
    first = tree.body[0] if tree and tree.body else None
    return first if isinstance(first, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def node_tokens(node: FunctionNode) -> list[str]:
    """
    What the function does, as a bag of tokens: the names it calls, the attributes it touches, the words in its
    identifiers, and its control flow. Two functions that solve the same problem share many of these even when
    their structure and names differ, which is what lets dry-lint find re-implementations, not only copies.
    """
    tokens = [f"fn:{word}" for word in words(node.name)] * 2
    for part in (node.args, *([node.returns] if node.returns else []), *node.body):  # not its decorators
        for child in ast.walk(part):
            if isinstance(child, ast.Call):
                target = child.func
                leaf = target.attr if isinstance(target, ast.Attribute) else target.id if isinstance(target, ast.Name) else None
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


def structure_hash(function: Function) -> str:
    """
    A hash that changes when the logic changes, and not for comments, docstrings, formatting, decorators, renamed
    local variables or a renamed function. Verdicts are keyed on it, so cosmetic edits never cost a new judgement.
    """
    node = _function_node(function.code)
    if node is None:
        return hashlib.sha256(function.code.encode()).hexdigest()[:16]
    return hashlib.sha256(ast.dump(_Canonical().visit(node), annotate_fields=False).encode()).hexdigest()[:16]


def function_nodes(source: str, path: str, min_lines: int = 2) -> list[tuple[Function, FunctionNode]]:
    """Top-level functions and methods, with their syntax trees (nested functions stay part of their parent)."""
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
                if end - child.lineno + 1 >= min_lines:
                    found.append((Function(path=path, name=child.name, owner=owner, line=child.lineno, end_line=end,
                                           code="\n".join(lines[child.lineno - 1 : end])), child))

    visit(tree, None)
    return found


def functions_in(source: str, path: str, min_lines: int = 2) -> list[Function]:
    return [function for function, _ in function_nodes(source, path, min_lines)]


def tracked_files(root: Path, include: list[str], exclude: list[str]) -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True).stdout
    return [
        path for path in listed.split("\0")
        if path and any(fnmatch.fnmatch(path, pattern) for pattern in include)
        and not any(fnmatch.fnmatch(path, pattern) for pattern in exclude)
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
            found += extractor.functions(path, (root / path).read_text())
        except (OSError, UnicodeDecodeError):
            continue
    return found
