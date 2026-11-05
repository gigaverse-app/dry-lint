"""The built-in extractor: Python, by its syntax tree."""

import ast

from dry_lint.functions import function_nodes, node_calls, node_tokens, structure_hash
from dry_lint.models import Function, LanguageAnalysis, qualified


def forwarding_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Only a single receiver call with unchanged parameter arguments establishes a forwarding body."""
    if node.decorator_list or node.args.defaults or any(value is not None for value in node.args.kw_defaults):
        # Decorators and parameter initializers can add behavior outside the apparent forwarding body.
        return None
    body = [
        statement
        for statement in node.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]
    if len(body) != 1 or not isinstance(body[0], (ast.Return, ast.Expr)):
        return None
    call = body[0].value
    if isinstance(call, ast.Await):
        call = call.value
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
        return None
    parameters = [*node.args.posonlyargs, *node.args.args]
    if not parameters or not isinstance(call.func.value, ast.Name) or call.func.value.id != parameters[0].arg:
        return None
    names = {arg.arg for arg in [*parameters, *node.args.kwonlyargs]}
    if any(
        not isinstance(arg, ast.Name) or arg.id not in names
        for arg in [*call.args, *(keyword.value for keyword in call.keywords)]
    ):
        return None
    if any(keyword.arg is None for keyword in call.keywords):
        return None
    return call.func.attr


class PythonExtractor:
    """Top-level functions and methods of at least `min_lines` lines; nested functions stay part of their parent."""

    name = "python"
    version = "3"
    files = ("*.py",)

    def __init__(self, min_lines: int = 2) -> None:
        self.min_lines = min_lines

    def functions(self, path: str, source: str) -> list[Function]:
        found = []
        for function, node in function_nodes(source, path, self.min_lines):
            target = forwarding_method(node) if function.owner else None
            function.tokens = node_tokens(node)
            function.calls = node_calls(node)
            function.analysis = LanguageAnalysis(
                language=self.name,
                version=self.version,
                convention="python-special-method"
                if function.owner and function.name.startswith("__") and function.name.endswith("__")
                else None,
                forward_target=f"{path}::{qualified(function.owner, target)}" if target else None,
                declared_override=any(
                    isinstance(decorator, ast.Name) and decorator.id == "override" for decorator in node.decorator_list
                ),
            )
            found.append(function)
        return found

    def validate_source(self, path: str, source: str) -> None:
        try:
            ast.parse(source, filename=path)
        except SyntaxError as error:
            raise ValueError(f"Cannot completely scan {path}: {error.msg}") from error

    def structure_hash(self, function: Function) -> str:
        return structure_hash(function)
