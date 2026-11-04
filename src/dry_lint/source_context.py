"""Bounded, static TypeScript dependency context for semantic judges."""

from tree_sitter import Node


def identifiers(node: Node) -> set[str]:
    found = set()
    pending = [node]
    while pending:
        child = pending.pop()
        if child.type in {"identifier", "type_identifier", "shorthand_property_identifier"}:
            found.add(child.text.decode("utf-8"))
        pending.extend(child.named_children)
    return found


def with_comments(node: Node) -> str:
    start = node
    while start.prev_named_sibling is not None and start.prev_named_sibling.type == "comment":
        start = start.prev_named_sibling
    parent = node.parent
    assert parent is not None
    return parent.text[start.start_byte - parent.start_byte : node.end_byte - parent.start_byte].decode("utf-8")


class SourceContext:
    def __init__(self, root: Node):
        self.imports = [node for node in root.named_children if node.type == "import_statement"]
        self.definitions: dict[str, Node] = {}
        for statement in root.named_children:
            node = statement
            if node.type == "export_statement":
                declaration = node.child_by_field_name("declaration")
                if declaration is None:
                    continue
                node = declaration
            declarations = (
                node.named_children if node.type in {"lexical_declaration", "variable_declaration"} else [node]
            )
            for declaration in declarations:
                name = declaration.child_by_field_name("name")
                if name is not None:
                    self.definitions[name.text.decode("utf-8")] = statement

    def for_function(self, node: Node, limit: int = 8000) -> str:
        needed = identifiers(node)
        picked: dict[int, Node] = {}
        for _ in range(3):
            for name in sorted(needed):
                declaration = self.definitions.get(name)
                if declaration is None or declaration.start_byte <= node.start_byte < declaration.end_byte:
                    continue
                picked[declaration.start_byte] = declaration
            needed |= set().union(*(identifiers(declaration) for declaration in picked.values()))
        for statement in self.imports:
            if needed & identifiers(statement):
                picked[statement.start_byte] = statement
        context = "\n".join(with_comments(statement) for _, statement in sorted(picked.items()))
        own = node
        while own.parent is not None and own.parent.type in {
            "export_statement",
            "lexical_declaration",
            "variable_declaration",
        }:
            own = own.parent
        comments = with_comments(own).removesuffix(own.text.decode("utf-8")).strip()
        if comments:
            context = comments + "\n" + context
        return context if len(context) <= limit else context[:limit] + "\n[context truncated]"
