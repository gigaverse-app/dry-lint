"""Offline static-signal experiment. Never imports or executes the repository being inspected.

Not registered as a production plugin. The trial runner adds these tokens to a copy of each function.
Unknown bindings are omitted; this is deliberately not a complete Python name or data-flow resolver.
"""

import ast
import inspect
from collections import Counter, deque
from collections.abc import Iterator
from pathlib import PurePosixPath

from dry_lint.functions import FunctionNode, function_nodes


def walk(root: ast.AST) -> Iterator[ast.AST]:
    """Executable syntax in this scope, excluding nested scopes and annotations."""
    pending = deque([root])
    while pending:
        node = pending.popleft()
        yield node
        if node is not root and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        for field, value in ast.iter_fields(node):
            if field in {"annotation", "returns", "type_params", "decorator_list"}:
                continue
            if isinstance(value, ast.AST):
                pending.append(value)
            elif isinstance(value, list):
                pending.extend(child for child in value if isinstance(child, ast.AST))


def dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and (base := dotted(node.value)):
        return f"{base}.{node.attr}"
    return None


def bound_names(node: ast.AST) -> set[str]:
    """Anything that might shadow a global alias, conservatively across the whole function."""
    names = set()
    for child in walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
        elif isinstance(child, ast.arg):
            names.add(child.arg)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.split(".")[0] for alias in child.names)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child is not node:
            names.add(child.name)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            names.add(child.name)
        elif isinstance(child, (ast.Global, ast.Nonlocal)):
            names.update(child.names)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, (ast.Store, ast.Del)):
            if target := dotted(child):
                names.add(target.split(".")[0])
        elif isinstance(child, (ast.MatchAs, ast.MatchStar)) and child.name:
            names.add(child.name)
        elif isinstance(child, ast.MatchMapping) and child.rest:
            names.add(child.rest)
    return names


def module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if len(parts) > 1 and parts[0] == "src":
        parts.pop(0)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def signature(node: FunctionNode) -> inspect.Signature | None:
    # A decorator or variadic forwarding can change the callable contract; do not invent one.
    if node.decorator_list or node.args.vararg or node.args.kwarg:
        return None
    parameters = []
    positional = [*node.args.posonlyargs, *node.args.args]
    defaults = [inspect.Parameter.empty] * (len(positional) - len(node.args.defaults)) + node.args.defaults
    for arg, default in zip(positional, defaults):
        kind = inspect.Parameter.POSITIONAL_ONLY if arg in node.args.posonlyargs else inspect.Parameter.POSITIONAL_OR_KEYWORD
        parameters.append(inspect.Parameter(arg.arg, kind, default=default))
    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        parameters.append(inspect.Parameter(arg.arg, inspect.Parameter.KEYWORD_ONLY,
                                            default=default if default is not None else inspect.Parameter.empty))
    return inspect.Signature(parameters)


def field(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        return node.slice.value
    return None


def reads(node: ast.AST) -> set[str]:
    """Fields directly mentioned by an expression, not transitive local-variable provenance."""
    if isinstance(node, ast.Lambda):
        return set()
    if isinstance(node, ast.Call):
        fields = set()
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                fields.add(first.value)
        # The callee's method name is not a data field.
        return fields.union(*(reads(arg) for arg in node.args), *(reads(k.value) for k in node.keywords))
    if name := field(node):
        return {name}
    return set().union(*(reads(child) for child in ast.iter_child_nodes(node)))


class Signals:
    def __init__(self, sources: dict[str, str]) -> None:
        self.aliases: dict[str, dict[str, str]] = {}
        self.signatures: dict[str, inspect.Signature] = {}
        self.nodes: dict[str, tuple[str, FunctionNode]] = {}
        for path, source in sources.items():
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            module = module_name(path)
            aliases, definitions, counts = {}, {}, Counter()
            blocked = set()
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        local = alias.asname or alias.name.split(".")[0]
                        counts[local] += 1
                        if isinstance(node, ast.Import):
                            aliases[local] = alias.name if alias.asname else local
                        else:
                            package = module.split(".") if path.endswith("/__init__.py") else module.split(".")[:-1]
                            prefix = package[:len(package) - node.level + 1] if node.level else []
                            target = ".".join([*prefix, *([node.module] if node.module else []), alias.name])
                            if node.level <= len(package):
                                aliases[local] = target
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    counts[node.name] += 1
                    aliases[node.name] = f"{module}.{node.name}"
                    if found := signature(node):
                        definitions[node.name] = found
                elif isinstance(node, ast.ClassDef):
                    counts[node.name] += 1
                else:
                    blocked.update(bound_names(node))
            # A star import or any rebind invalidates resolution rather than guessing which value won.
            self.aliases[path] = {} if "*" in counts or "*" in blocked else {
                name: target for name, target in aliases.items() if counts[name] == 1 and name not in blocked
            }
            for name, found in definitions.items():
                if name in self.aliases[path]:
                    self.signatures[self.aliases[path][name]] = found
            for function, node in function_nodes(source, path):
                self.nodes[function.qualname] = (path, node)

    def tokens(self, qualname: str, feature: str) -> list[str]:
        if qualname not in self.nodes:
            return []
        path, tree = self.nodes[qualname]
        shadowed = bound_names(tree)
        aliases = {name: target for name, target in self.aliases[path].items() if name not in shadowed}
        result = []
        for node in walk(tree):
            if isinstance(node, ast.Call) and (name := dotted(node.func)):
                root, dot, tail = name.partition(".")
                target = aliases.get(root)
                if target:
                    target += dot + tail
                    if feature == "api":
                        result.append(f"api:{target}")
                    elif feature == "binding" and target in self.signatures:
                        keywords = [k.arg for k in node.keywords]
                        if (any(isinstance(arg, ast.Starred) for arg in node.args) or None in keywords
                                or len(keywords) != len(set(keywords))):
                            continue
                        try:
                            bound = self.signatures[target].bind(*node.args, **{k.arg: k.value for k in node.keywords})
                        except TypeError:
                            continue
                        bound.apply_defaults()
                        for parameter, value in bound.arguments.items():
                            result.append(f"bind:{target}:{parameter}")
                            result.extend(f"bind:{target}:{parameter}<-{name}" for name in sorted(reads(value)))
            if feature == "flow":
                if isinstance(node, ast.Return) and node.value is not None:
                    result.extend(f"flow:{name}->return" for name in sorted(reads(node.value)))
                elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if sink := field(target):
                            result.extend(f"flow:{name}->{sink}" for name in sorted(reads(node.value)))
        return result
