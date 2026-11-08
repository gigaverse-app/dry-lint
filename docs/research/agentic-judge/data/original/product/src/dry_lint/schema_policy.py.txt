"""Opt-in Python schema ownership checks, independently of similarity or paid judging."""

import ast
import fnmatch
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from dry_lint.python_schemas import SchemaModule, reference


class SchemaSink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    position: int = Field(default=0, ge=0)
    keyword: str = "schema"


class SchemaPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root_suffix: str = Field(min_length=1)
    include: list[str] = Field(default_factory=lambda: ["*"])
    methods: list[str] = Field(default_factory=list)
    functions: list[SchemaSink] = Field(default_factory=list)
    chain_bases: list[str] = Field(default_factory=list)
    response_attribute: str = "response_model"


class SchemaIssue(BaseModel):
    path: str
    line: int
    rule: str
    symbol: str
    detail: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return self.path, self.rule, self.symbol, self.detail

    def text(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.symbol}: {self.detail}"


def chain_names(module: SchemaModule, policy: SchemaPolicy) -> set[str]:
    chains = set(policy.chain_bases)
    pending = True
    while pending:
        pending = False
        for name, node in module.classes.items():
            if name not in chains and any(module.resolve(reference(base)) in chains for base in node.bases):
                chains.add(name)
                pending = True
    return chains


def roots(module: SchemaModule, policy: SchemaPolicy) -> list[tuple[ast.AST, str]]:
    """Only configured LLM sinks count; arbitrary HTTP response_model keywords do not."""
    found: list[tuple[ast.AST, str]] = []
    chains = chain_names(module, policy)
    chain_calls: set[ast.Call] = set()
    for name in chains & module.classes.keys():
        node = module.classes[name]
        for statement in node.body:
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
                if isinstance(statement, ast.AnnAssign)
                else []
            )
            if (
                any(reference(target) == policy.response_attribute for target in targets)
                and statement.value is not None
            ):
                found.append((statement.value, module.resolve(reference(statement.value))))
        chain_calls.update(
            n for n in ast.walk(node) if isinstance(n, ast.Call) and ast.unparse(n.func) == "super().__init__"
        )
    functions = {sink.name: sink for sink in policy.functions}
    for call in (n for n in ast.walk(module.tree) if isinstance(n, ast.Call)):
        target = module.resolve(reference(call.func))
        sink = functions.get(target)
        if isinstance(call.func, ast.Attribute) and call.func.attr in policy.methods:
            sink = SchemaSink(name=target)
        if call in chain_calls or target in chains:
            # Constructor position is not assumed; wrappers differ in positional parameters.
            value = next((kw.value for kw in call.keywords if kw.arg == policy.response_attribute), None)
        elif sink:
            value = next((kw.value for kw in call.keywords if kw.arg == sink.keyword), None)
            if value is None and len(call.args) > sink.position:
                value = call.args[sink.position]
        else:
            continue
        if value is not None and not (isinstance(value, ast.Constant) and value.value is None):
            found.append((value, module.resolve(reference(value))))
    return found


def audit(sources: dict[str, str], policy: SchemaPolicy) -> list[SchemaIssue]:
    modules = {
        path: SchemaModule(path, source)
        for path, source in sources.items()
        if path.endswith(".py") and any(fnmatch.fnmatchcase(path, pattern) for pattern in policy.include)
    }
    identities = {path: path.removesuffix(".py").removesuffix("/__init__").replace("/", ".") for path in modules}
    declarations: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for path, module in modules.items():
        for name in module.classes:
            parts = f"{identities[path]}.{name}".split(".")
            for start in range(len(parts) - len(name.split("."))):
                declarations[".".join(parts[start:])].add((path, name))

    def locate(path: str, name: str) -> tuple[str, str] | None:
        if name in modules[path].classes:
            return path, name
        matches = declarations.get(name, set())
        return next(iter(matches)) if len(matches) == 1 else None

    families = {
        path: set().union(*(module.family(name) for name in module.classes if name.endswith(policy.root_suffix)))
        for path, module in modules.items()
    }
    issues: list[SchemaIssue] = []

    def add(path: str, node: ast.AST, rule: str, symbol: str, detail: str) -> None:
        issues.append(SchemaIssue(path=path, line=node.lineno, rule=rule, symbol=symbol, detail=detail))

    for path, module in modules.items():
        chains = chain_names(module, policy)
        for node, name in roots(module, policy):
            if name in {"str", "int", "float", "bool"}:
                continue
            located = locate(path, name) if name else None
            if located is None:
                add(
                    path,
                    node,
                    "unresolved-root",
                    name or ast.unparse(node),
                    "Verify the generated or external structured-output root and its complete schema family.",
                )
            elif not located[1].endswith(policy.root_suffix):
                add(
                    path,
                    node,
                    "root-name",
                    name,
                    f"Every structured-output root must end in {policy.root_suffix}; split mixed application ownership before renaming.",
                )
            elif located[0] != path:
                add(
                    path,
                    node,
                    "file-privacy",
                    name,
                    "Keep the root, nested schema family, prompt and LLM call in one file.",
                )
        for name, refs in module.references.items():
            for ref in refs:
                located = locate(path, ref)
                if located is None:
                    continue
                other_path, other_name = located
                if name in families[path] and other_path != path:
                    add(
                        path,
                        module.classes[name],
                        "external-type",
                        name,
                        f"Prompt schema family references {other_path}::{other_name}; define a private prompt type and convert at the boundary.",
                    )
                elif name not in families[path] and other_name in families[other_path] and name not in chains:
                    add(
                        path,
                        module.classes[name],
                        "application-use",
                        name,
                        f"Application model embeds or inherits prompt type {other_path}::{other_name}; consume a conformed application model.",
                    )
        # Imports are an ownership escape even before the imported class is instantiated.
        for node in ast.walk(module.tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            imports = SchemaModule(path, ast.unparse(node)).bindings
            for target in imports.values():
                located = locate(path, target)
                if located and located[0] != path and located[1] in families[located[0]]:
                    add(
                        path,
                        node,
                        "file-privacy",
                        target,
                        "Prompt schema families are private to their prompt/call file; import the conformed application result instead.",
                    )
        # Module-qualified references (import package.prompt as p; p.Root.Nested) also cross the boundary.
        for node in (n for n in ast.walk(module.tree) if isinstance(n, ast.Attribute)):
            name = module.resolve(reference(node))
            located = locate(path, name)
            if located and located[0] != path and located[1] in families[located[0]]:
                add(
                    path,
                    node,
                    "file-privacy",
                    name,
                    "Use the conformed application result outside the prompt/call file.",
                )
    return list({(issue.key, issue.line): issue for issue in issues}.values())


def check(root: Path, settings, args) -> int:
    from dry_lint.detector import base_ref, changed_lines
    from dry_lint.function_index import tree_blobs
    from dry_lint.git import git

    policy = settings.models.schema_policy
    if policy is None:
        raise ValueError("schema-check requires an explicit models.schema_policy")
    revision = git(root, "write-tree") if args.staged else "HEAD"
    sources = {path: source.decode("utf-8") for path, source in tree_blobs(root, revision, settings).items()}
    issues = audit(sources, policy)
    if not args.all:
        changed = changed_lines(root, args.base, args.staged)
        base = "HEAD" if args.staged else git(root, "merge-base", base_ref(root, args.base), "HEAD")
        previous = {
            issue.key
            for issue in audit(
                {path: source.decode("utf-8") for path, source in tree_blobs(root, base, settings).items()}, policy
            )
        }
        issues = [issue for issue in issues if issue.path in changed or issue.key not in previous]
    for issue in issues:
        print(issue.text())
    print(f"dry-lint: {len(issues)} schema ownership issue(s); static checks do not prove runtime result isolation")
    return int(bool(issues))
