"""Python functions as the unit dry-lint compares: where they are, their code, and two fingerprints of it."""

import ast
import copy
import fnmatch
import hashlib
import re
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

STOP_WORDS = {
    "self", "cls", "return", "none", "true", "false", "args", "kwargs", "value", "result", "data", "item", "items",
    "get", "list", "dict", "str", "int", "len", "isinstance", "await", "async", "error",
}  # fmt: skip


class Function(BaseModel):
    """One top-level function or method, by the qualified name dry-lint keys everything on."""

    path: str = Field(description="Path relative to the repository root.")
    name: str = Field(description="The function's own name.")
    owner: str | None = Field(default=None, description="Enclosing class, for methods.")
    line: int
    end_line: int
    code: str

    @property
    def qualname(self) -> str:
        return f"{self.path}::{self.owner + '.' if self.owner else ''}{self.name}"

    @property
    def lines(self) -> int:
        return self.end_line - self.line + 1


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


def _call_name(node: ast.Call) -> str | None:
    target = node.func
    return target.attr if isinstance(target, ast.Attribute) else target.id if isinstance(target, ast.Name) else None


def calls(function: Function) -> set[str]:
    """Names actually invoked, excluding declarations and mentions in comments or strings."""
    tree = _parse(function.code)
    if tree is None:
        return set()
    # Suppression needs a real call node; textual resemblance is not evidence of delegation.
    return {name for node in ast.walk(tree) if isinstance(node, ast.Call) if (name := _call_name(node))}


def behaviour_tokens(function: Function) -> list[str]:
    """
    What the function does, as a bag of tokens: the names it calls, the attributes it touches, the words in its
    identifiers, and its control flow. Two functions that solve the same problem share many of these even when
    their structure and names differ, which is what lets dry-lint find re-implementations, not only copies.
    """
    tree = _parse(function.code)
    tokens = [f"fn:{word}" for word in words(function.name)] * 2
    if tree is None:
        return tokens
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            leaf = _call_name(node)
            if leaf:
                tokens.append(f"call:{leaf.lower()}")
                tokens += [f"w:{word}" for word in words(leaf)]
        elif isinstance(node, ast.Attribute):
            tokens.append(f"attr:{node.attr.lower()}")
        elif isinstance(node, ast.Name):
            tokens += [f"w:{word}" for word in words(node.id)]
        elif isinstance(node, ast.arg):
            tokens += [f"w:{word}" for word in words(node.arg)]
        elif isinstance(node, (ast.For, ast.While)):
            tokens.append("ctl:loop")
        elif isinstance(node, ast.Try):
            tokens.append("ctl:try")
        elif isinstance(node, ast.Await):
            tokens.append("ctl:await")
    return tokens


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
    A hash that changes when the logic changes, and not for comments, docstrings, formatting, renamed local
    variables or a renamed function. Verdicts are keyed on it, so cosmetic edits never cost a new judgement.
    """
    tree = _parse(function.code)
    if tree is None:
        return hashlib.sha256(function.code.encode()).hexdigest()[:16]
    canonical = _Canonical().visit(copy.deepcopy(tree))
    return hashlib.sha256(ast.dump(canonical, annotate_fields=False).encode()).hexdigest()[:16]


def _is_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Declaration-only bodies have no implementation to reuse; retain any executable behavior."""
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


def functions_in(source: str, path: str, min_lines: int = 2) -> list[Function]:
    """Top-level functions and methods (nested functions stay part of their parent)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    found: list[Function] = []

    def visit(node: ast.AST, owner: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = child.end_lineno or child.lineno
                # Stubs otherwise dominate exact-match rankings and consume the judge's candidate budget.
                if end - child.lineno + 1 >= min_lines and not _is_stub(child):
                    found.append(
                        Function(
                            path=path,
                            name=child.name,
                            owner=owner,
                            line=child.lineno,
                            end_line=end,
                            code="\n".join(lines[child.lineno - 1 : end]),
                        )
                    )

    visit(tree, None)
    return found


def tracked_python_files(root: Path, include: list[str], exclude: list[str]) -> list[str]:
    listed = subprocess.run(["git", "ls-files", "*.py"], cwd=root, capture_output=True, text=True, check=True).stdout
    return [
        path for path in listed.split()
        if any(fnmatch.fnmatch(path, pattern) for pattern in include)
        and not any(fnmatch.fnmatch(path, pattern) for pattern in exclude)
    ]  # fmt: skip


def repository_functions(root: Path, include: list[str], exclude: list[str]) -> list[Function]:
    found: list[Function] = []
    for path in tracked_python_files(root, include, exclude):
        try:
            found += functions_in((root / path).read_text(), path)
        except (OSError, UnicodeDecodeError):
            continue
    return found
