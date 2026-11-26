"""Lean 4 declarations for static comparison, without elaborating imports or running tactics."""

from tree_sitter import Node

from dry_lint.extractor_capabilities import ExtractorCapabilities
from dry_lint.functions import exact_source_hash, text_digest
from dry_lint.models import Function

_IMPLEMENTATIONS = {"def", "abbrev", "opaque", "theorem", "instance"}


def _tokens(parts: list[Node]) -> list[str]:
    """Read a sequence of syntax trees in source order, ignoring comments and layout nodes."""
    pending = list(reversed(parts))
    tokens = []
    while pending:
        node = pending.pop()
        if node.type.endswith("comment"):
            continue
        if node.type in {"str_lit", "raw_string"}:
            # Quote delimiters and escapes are not shared behavior. Keep identical
            # literals comparable without putting their potentially long text in the index.
            tokens.append(f"str:{text_digest(node.text.decode('utf-8'))}")
            continue
        if node.child_count:
            pending.extend(reversed(node.children))
        elif node.end_byte > node.start_byte:
            tokens.append(node.text.decode("utf-8"))
    return tokens


class LeanExtractor:
    name = "lean"
    version = "2"
    # Layout and spelling can affect Lean macros, so hash the source exactly.
    structure_hash = staticmethod(exact_source_hash)
    files = ("*.lean",)
    capabilities = ExtractorCapabilities(
        language_name="Lean", comment_prefix="--", index_distributions=("tree-sitter", "tree-sitter-language-pack")
    )

    def __init__(self, min_lines: int = 2) -> None:
        try:
            from tree_sitter_language_pack import get_parser
        except ImportError as error:
            raise ImportError("The lean extractor requires pip install 'dry-lint[lean]'") from error
        self.parser = get_parser("lean")
        self.min_lines = min_lines

    def validate_source(self, path: str, source: str) -> None:
        if self.parser.parse(source.encode("utf-8")).root_node.has_error:
            raise ValueError(f"Cannot completely scan {path}: Lean grammar encountered unsupported or invalid syntax")

    def functions(self, path: str, source: str) -> list[Function]:
        found = []
        scopes: list[str] = []
        context_digest = text_digest(source)
        for command in self.parser.parse(source.encode("utf-8")).root_node.named_children:
            if command.type == "namespace":
                name = command.child_by_field_name("name")
                scopes.append(name.text.decode("utf-8") if name else "")
            elif command.type in {"section", "public_section", "mutual"}:
                scopes.append("")
            elif command.type == "end" and scopes:
                scopes.pop()
            else:
                # A command such as "open X in" can wrap the declaration it applies to.
                inner = command
                while inner.type != "declaration" and (body := inner.child_by_field_name("body")):
                    inner = body
                if inner.type == "declaration" and not command.has_error:
                    decl = next((n for n in inner.named_children if n.type in _IMPLEMENTATIONS), None)
                    if decl is not None and (function := self._function(path, command, decl, scopes)):
                        function.context_digest = context_digest
                        found.append(function)
        return found

    def _function(self, path: str, command: Node, decl: Node, scopes: list[str]) -> Function | None:
        name = decl.child_by_field_name("name")
        parts = [
            node
            for index, node in enumerate(decl.children)
            if node.is_named
            and (
                decl.field_name_for_child(index) == "body" or node.type in {"match_alt", "where_struct", "where_decls"}
            )
        ]
        code = command.text.decode("utf-8").rstrip()
        line = command.start_point.row + 1
        length = code.count("\n") + 1
        if name is None or not parts or length < self.min_lines:
            return None
        ident = name.text.decode("utf-8")
        owner = None if ident.startswith("_root_.") else ".".join(filter(None, scopes)) or None
        # Different propositions can share a one-tactic proof such as rfl.
        result_types = [node for node in decl.children_by_field_name("type") if node.is_named]
        return Function(
            path=path,
            name=ident.removeprefix("_root_."),
            owner=owner,
            line=line,
            end_line=line + length - 1,
            code=code,
            tokens=[*_tokens(parts), *(f"type:{token}" for token in _tokens(result_types))],
        )
