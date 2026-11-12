"""The built-in extractor: Python, by its syntax tree."""

import ast

from dry_lint.extractor_capabilities import ExtractorCapabilities
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


def _local_bindings(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Names the function binds itself (parameters, assignments, imports, nested definitions)."""
    arguments = node.args
    names = {
        arg.arg
        for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg]
        if arg is not None
    }
    declared: set[str] = set()
    for child in (descendant for statement in node.body for descendant in ast.walk(statement)):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0] for alias in child.names)
        elif isinstance(child, ast.Global):
            declared.update(child.names)
    # `global` makes every assignment in the body rebind the module name, so it is not a local binding.
    return names - declared


def local_calls(
    path: str, function: Function, defined: set[str], receivers: tuple[str, ...], bare: set[str] | None = None
) -> tuple[str, ...]:
    """
    Direct calls that bind to a definition in this file: `<receiver>.m` to a method of the function's own class, and,
    when the adapter can rule out shadowing, a bare `f(...)` to a module-level function (`bare` names the body's own
    bindings). Anything else (imports, other receivers, dynamic dispatch) stays unresolved and never settles a pair.
    """
    targets = []
    for call in function.calls or []:
        receiver, _, name = call.rpartition(".")
        if receiver in receivers:
            target = qualified(function.owner, name) if function.owner else None
        else:
            target = call if bare is not None and not receiver and call not in bare else None
        if target and target in defined and target != qualified(function.owner, function.name):
            targets.append(f"{path}::{target}")
    return tuple(dict.fromkeys(targets))


class PythonExtractor:
    """Top-level functions and methods of at least `min_lines` lines; nested functions stay part of their parent."""

    name = "python"
    version = "3"
    files = ("*.py",)
    capabilities = ExtractorCapabilities(language_name="Python", model_extractor="python-models")

    def comparison_helpers(self, source: str, caller: Function) -> list[Function]:
        from dry_lint.comparison_helpers import python_helpers

        return python_helpers(source, caller)

    def __init__(self, min_lines: int = 2) -> None:
        self.min_lines = min_lines

    def functions(self, path: str, source: str) -> list[Function]:
        found = []
        nodes = function_nodes(source, path, self.min_lines)
        defined = {qualified(function.owner, function.name) for function, _ in nodes}
        for function, node in nodes:
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
                local_calls=local_calls(path, function, defined, ("self", "cls"), _local_bindings(node)),
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
