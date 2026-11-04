"""The built-in extractor: Python, by its syntax tree."""

import ast

from dry_lint.functions import function_nodes, node_calls, node_tokens, structure_hash
from dry_lint.models import Function


class PythonExtractor:
    """Top-level functions and methods of at least `min_lines` lines; nested functions stay part of their parent."""

    name = "python"
    version = "2"
    files = ("*.py",)

    def __init__(self, min_lines: int = 2) -> None:
        self.min_lines = min_lines

    def functions(self, path: str, source: str) -> list[Function]:
        return [
            function.model_copy(update={"tokens": node_tokens(node), "calls": node_calls(node)})
            for function, node in function_nodes(source, path, self.min_lines)
        ]

    def validate_source(self, path: str, source: str) -> None:
        try:
            ast.parse(source, filename=path)
        except SyntaxError as error:
            raise ValueError(f"Cannot completely scan {path}: {error.msg}") from error

    def structure_hash(self, function: Function) -> str:
        return structure_hash(function)
