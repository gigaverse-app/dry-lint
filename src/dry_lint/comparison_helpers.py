"""Bounded same-file Python call references for source comparison, without executing source."""

import ast
import symtable
from collections import Counter
from collections.abc import Iterator

from dry_lint.functions import function_nodes
from dry_lint.models import Function

MAX_HELPERS = 5


def scope_nodes(statements: list[ast.stmt]) -> Iterator[ast.AST]:
    pending: list[ast.AST] = list(reversed(statements))
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.Lambda,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
            ),
        ):
            pending.extend(reversed(list(ast.iter_child_nodes(node))))


def python_helpers(source: str, caller: Function) -> list[Function]:
    definitions = function_nodes(source, caller.path, min_lines=1)
    node = next(node for function, node in definitions if function.line == caller.line)
    try:
        tables = [symtable.symtable(source, caller.path, "exec")]
    except SyntaxError:
        return []
    for table in tables:
        tables.extend(table.get_children())
    symbols = next(
        table
        for table in tables
        if isinstance(table, symtable.Function)
        and table.get_lineno() == caller.line
        and table.get_name() == caller.name
    )
    calls = {
        child.func.id
        for child in scope_nodes(node.body)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
    }
    globals_called = {
        name
        for name in calls
        if symbols.lookup(name).is_global()
        and not symbols.lookup(name).is_assigned()
        and not symbols.lookup(name).is_imported()
    }
    bindings: Counter[str] = Counter()
    for child in scope_nodes(ast.parse(source).body):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings[child.name] += 1
        elif isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            bindings[child.id] += 1
        elif isinstance(child, ast.alias):
            if child.name == "*":
                return []
            bindings[child.asname or child.name.split(".")[0]] += 1
        elif isinstance(child, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and child.name:
            bindings[child.name] += 1
        elif isinstance(child, ast.MatchMapping) and child.rest:
            bindings[child.rest] += 1
    return [
        function
        for function, _ in definitions
        if function.owner is None
        and function.name in globals_called
        and bindings[function.name] == 1
        and function.line != caller.line
        and function.end_line - function.line < 600
    ][:MAX_HELPERS]
