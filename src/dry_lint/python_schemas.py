"""Static Python schema references. No adopter imports or inferred architectural roles."""

import ast


def reference(node: ast.AST, bindings: dict[str, str] | None = None, *, follow_calls: bool = False) -> str:
    if isinstance(node, ast.Name):
        return (bindings or {}).get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return f"{reference(node.value, bindings, follow_calls=follow_calls)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        return reference(node.value, bindings, follow_calls=follow_calls)
    if follow_calls and isinstance(node, ast.Call):
        return reference(node.func, bindings, follow_calls=True)
    return ""


def type_references(node: ast.AST) -> set[str]:
    """Annotations, including quoted forward references; never string-valued Literal metadata."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return type_references(ast.parse(node.value, mode="eval").body)
        except SyntaxError:
            return set()
    if isinstance(node, (ast.Name, ast.Attribute)):
        return {reference(node)}
    if isinstance(node, ast.Subscript) and reference(node.value).split(".")[-1] in {"Literal", "Annotated"}:
        return (
            type_references(node.slice.elts[0])
            if reference(node.value).endswith("Annotated") and isinstance(node.slice, ast.Tuple)
            else set()
        )
    return set().union(*(type_references(child) for child in ast.iter_child_nodes(node)))


class SchemaModule:
    def __init__(self, path: str, source: str) -> None:
        from dry_lint.functions import python_imports

        self.tree = ast.parse(source, filename=path)
        modules, names = python_imports(self.tree, path)
        self.bindings = {name: module.replace("/", ".") for name, module in modules.items()}
        self.bindings.update({name: f"{module.replace('/', '.')}.{symbol}" for name, (module, symbol) in names.items()})
        self.classes: dict[str, ast.ClassDef] = {}

        def collect(body: list[ast.stmt], prefix: str = "") -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    name = prefix + node.name
                    self.classes[name] = node
                    collect(node.body, name + ".")

        collect(self.tree.body)
        aliases = {
            node.targets[0].id: type_references(node.value)
            for node in self.tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, (ast.Name, ast.Attribute, ast.Subscript, ast.BinOp))
        }

        def expand(refs: set[str], owner: str) -> set[str]:
            pending = list(refs)
            seen: set[str] = set()
            result: set[str] = set()
            while pending:
                ref = self.resolve(pending.pop(), owner)
                if ref in seen:
                    continue
                seen.add(ref)
                if ref in aliases:
                    pending.extend(aliases[ref])
                else:
                    result.add(ref)
            return result

        self.references: dict[str, set[str]] = {}
        for name, node in self.classes.items():
            annotations = [f.annotation for f in node.body if isinstance(f, ast.AnnAssign)]
            refs = set().union(*(type_references(n) for n in [*node.bases, *annotations]))
            self.references[name] = expand(refs, name)

    def resolve(self, name: str, owner: str = "") -> str:
        # Lexical nested names win over module names. Module imports retain qualified identities.
        scope = owner
        while scope:
            if f"{scope}.{name}" in self.classes:
                return f"{scope}.{name}"
            scope = scope.rpartition(".")[0]
        head, dot, tail = name.partition(".")
        return self.bindings.get(head, head) + (dot + tail if dot else "")

    def family(self, root: str) -> set[str]:
        found: set[str] = set()
        pending = {root}
        while pending:
            name = pending.pop()
            found.add(name)
            pending.update(self.references.get(name, set()) & self.classes.keys() - found)
        return found

    def ancestors(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {name: [] for name in self.classes}
        for root in self.classes:
            for child in self.family(root):
                result[child].append(root)
        return result
