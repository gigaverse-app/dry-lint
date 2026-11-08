"""One pinned family: discover exact guards, snapshot source, build a local patch.

No imports of LiteLLM, network calls, providers, or writes outside this directory.
"""

from __future__ import annotations

import argparse
import ast
import collections
import difflib
import fnmatch
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REV = "fc1e47e580d9e3d2e8b46ad05a293a58ed0b8f1f"
GIT = "/home/researcher/dry-lint-round/research-corpus/litellm"
QUEUE = "/home/researcher/dry-lint-round/jobs/grounded-operation-judge/.lab-results/grounded-operation"
PREFIX = "litellm/proxy/management_endpoints/"
COMMON = PREFIX + "common_utils.py"
HELPER = '''def validate_nonnegative_budget(value: float | None, field_name: str) -> None:
    """Allow unset budgets; otherwise require a finite, nonnegative value."""
    if value is not None and (not math.isfinite(value) or value < 0):
        raise HTTPException(
            status_code=400,
            detail={"error": f"{field_name} must be a non-negative finite number. Received: {value}"},
        )
'''
MODEL_FILES = [
    "litellm/proxy/_types.py",
    "litellm/models/team.py",
    "litellm/models/budget.py",
    "litellm/types/llms/base.py",
    "litellm/types/llms/base_model.py",
    "litellm/types/proxy/management_endpoints/key_requests.py",
    "litellm/types/proxy/management_endpoints/request_base.py",
]


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def dump(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def git(*args, root=GIT):
    return subprocess.check_output(["git", "-C", root, *args])


def tree_dump(n):
    return ast.dump(n, include_attributes=False)


def statement_count(node, executable_only=False):
    return sum(
        isinstance(n, ast.stmt)
        and not (
            executable_only
            and (
                isinstance(
                    n,
                    (
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                        ast.ClassDef,
                        ast.Import,
                        ast.ImportFrom,
                    ),
                )
                or isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str)
            )
        )
        for n in ast.walk(node)
    )


def guards(source, path):
    """Match entire If AST, including status, detail shape, order, optional gate.

    Candidate enumeration is broader (every finite-number message) and records
    rejected candidates separately; no heuristic size/similarity threshold.
    """
    tree = ast.parse(source, filename=path)
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    found, rejected = [], []
    for n in ast.walk(tree):
        if not isinstance(n, ast.If) or len(n.body) != 1 or not isinstance(n.body[0], ast.Raise):
            continue
        r = n.body[0].exc
        if not isinstance(r, ast.Call) or ast.unparse(r.func) != "HTTPException":
            continue
        if "must be a non-negative finite number." not in ast.unparse(r):
            continue
        owner = n
        while owner in parents and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = parents[owner]
        assert isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef))
        base = dict(
            path=path,
            function=owner.name,
            source_id=f"{path}::{owner.name}",
            line=n.lineno,
            end_line=n.end_lineno,
            function_line=owner.lineno,
            function_end_line=owner.end_lineno,
        )
        # Every exact eligible guard uses a Name or Attribute with a budget field.
        detail = next((k.value for k in r.keywords if k.arg == "detail"), None)
        status = next(
            (k.value.value for k in r.keywords if k.arg == "status_code" and isinstance(k.value, ast.Constant)),
            None,
        )
        exprs = [x.value for x in ast.walk(detail) if isinstance(x, ast.FormattedValue)]
        expr = exprs[-1] if exprs else None
        field = expr.attr if isinstance(expr, ast.Attribute) else expr.id if isinstance(expr, ast.Name) else ""
        if field not in {"max_budget", "soft_budget", "team_member_budget"}:
            rejected.append(dict(base, status=status, reason="different field/message contract"))
            continue
        value = ast.unparse(expr)
        expected = ast.parse(f'''if {value} is not None and (not math.isfinite({value}) or {value} < 0):
    raise HTTPException(status_code=400, detail={{"error": f"{field} must be a non-negative finite number. Received: {{{value}}}"}})
''').body[0]
        if tree_dump(n) != tree_dump(expected):
            rejected.append(
                dict(
                    base,
                    status=status,
                    reason="HTTP status differs" if status != 400 else "optional gate or message differs",
                )
            )
            continue
        lines = source.splitlines(keepends=True)
        body = "".join(lines[owner.lineno - 1 : owner.end_lineno]).rstrip("\n")
        found.append(
            dict(
                base,
                field=field,
                expression=value,
                status=400,
                original="".join(lines[n.lineno - 1 : n.end_lineno]),
                body_sha256=sha(body),
                executable_statements=statement_count(n, True),
            )
        )
    return sorted(found, key=lambda r: r["line"]), sorted(rejected, key=lambda r: r["line"])


def replacement(row):
    indent = row["original"][: len(row["original"]) - len(row["original"].lstrip())]
    return f'{indent}validate_nonnegative_budget({row["expression"]}, "{row["field"]}")\n'


def write_owners(inventory):
    owners = []
    for source_id in dict.fromkeys(r["source_id"] for r in inventory["eligible"]):
        rows = [r for r in inventory["eligible"] if r["source_id"] == source_id]
        row = rows[0]
        tree = ast.parse((ROOT / "source" / row["path"]).read_text())
        fn = next(
            n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == row["function"]
        )
        callers = []
        for parent in tree.body:
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(parent):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == fn.name:
                        callers.append(
                            {
                                "source_id": row["path"] + "::" + parent.name,
                                "line": node.lineno,
                                "call": ast.unparse(node),
                            }
                        )
        owners.append(
            {
                "source_id": source_id,
                "line": fn.lineno,
                "kind": "route implementation" if fn.decorator_list else "existing private validation implementation",
                "fields": [r["field"] for r in rows],
                "guard_lines": [r["line"] for r in rows],
                "decorators": [ast.unparse(d) for d in fn.decorator_list],
                "same_module_direct_callers": callers,
            }
        )
    dump(
        "owners.json",
        {
            "owners": owners,
            "counts": {
                "implementation_functions": len(owners),
                "route_implementations": sum(bool(r["decorators"]) for r in owners),
                "existing_private_helpers": sum(not r["decorators"] for r in owners),
                "fields": len({r["field"] for r in inventory["eligible"]}),
                "source_modules": len({r["path"] for r in inventory["eligible"]}),
                "families": 1,
            },
            "definition": "Owner means distinct function body implementing policy, not organizational authorship. Route aliases/decorators and existing helper call sites are not additional implementations. Same-module direct calls only; dynamic import/call liveness is not proved.",
        },
    )


def build():
    inventory = json.loads((ROOT / "inventory.json").read_text())
    write_owners(inventory)
    grouped = collections.defaultdict(list)
    for row in inventory["eligible"]:
        grouped[row["path"]].append(row)
    before = {p: (ROOT / "source" / p).read_text() for p in [*grouped, COMMON]}
    after = {}
    for path, rows in grouped.items():
        lines = before[path].splitlines(keepends=True)
        for row in reversed(rows):
            lines[row["line"] - 1 : row["end_line"]] = [replacement(row)]
        source = "".join(lines)
        # Extend an existing common-utils import, preserving dependency ordering.
        t = ast.parse(source)
        imports = [
            n
            for n in t.body
            if isinstance(n, ast.ImportFrom) and n.module == "litellm.proxy.management_endpoints.common_utils"
        ]
        assert len(imports) == 1
        imp = imports[0]
        lines = source.splitlines(keepends=True)
        assert "(" in lines[imp.lineno - 1]
        insertion = next(
            (a.lineno - 1 for a in imp.names if a.name > "validate_nonnegative_budget"),
            imp.end_lineno - 1,
        )
        lines.insert(insertion, "    validate_nonnegative_budget,\n")
        if path == PREFIX + "budget_management_endpoints.py":
            assert sum(line == "import math\n" for line in lines) == 1
            lines.remove("import math\n")
        after[path] = "".join(lines)
    source = before[COMMON]
    # Place before cycle-sensitive litellm imports, beside finite-spend validation.
    anchor = "# Defined above the `litellm.proxy.*` imports"
    assert source.count(anchor) == 1
    after[COMMON] = source.replace(anchor, HELPER + "\n\n" + anchor, 1)
    patch, per_file = [], []
    for path in sorted(before):
        dest = ROOT / "proposed" / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(after[path])
        diff = list(
            difflib.unified_diff(
                before[path].splitlines(keepends=True),
                after[path].splitlines(keepends=True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
        patch.extend(diff)
        removed = [s[1:] for s in diff if s.startswith("-") and not s.startswith("---")]
        added = [s[1:] for s in diff if s.startswith("+") and not s.startswith("+++")]
        per_file.append(
            dict(
                path=path,
                before_sha256=sha(before[path]),
                after_sha256=sha(after[path]),
                lines_removed=len(removed),
                lines_added=len(added),
                nonblank_noncomment_lines_removed=sum(
                    bool(s.strip()) and not s.lstrip().startswith("#") for s in removed
                ),
                nonblank_noncomment_lines_added=sum(bool(s.strip()) and not s.lstrip().startswith("#") for s in added),
                ast_statements_before=statement_count(ast.parse(before[path])),
                ast_statements_after=statement_count(ast.parse(after[path])),
                executable_statements_before=statement_count(ast.parse(before[path]), True),
                executable_statements_after=statement_count(ast.parse(after[path]), True),
            )
        )
    (ROOT / "extraction.patch").write_text("".join(patch))
    helper_ast = ast.parse(HELPER)
    old_exec = sum(r["executable_statements"] for r in inventory["eligible"])
    new_exec = len(inventory["eligible"]) + statement_count(helper_ast, True)
    metrics = dict(
        revision=REV,
        occurrences=len(inventory["eligible"]),
        functions=len({r["source_id"] for r in inventory["eligible"]}),
        files=len(grouped),
        patch_files=len(per_file),
        fields=dict(collections.Counter(r["field"] for r in inventory["eligible"])),
        original_guard_executable_statements=old_exec,
        proposed_calls_and_helper_executable_statements=new_exec,
        executable_statements_saved=old_exec - new_exec,
        helper_physical_lines=len(HELPER.splitlines()),
        helper_blank_separators=2,
        helper_function_definitions_added=1,
        import_names_added=len(grouped),
        import_statements_added=0,
        unused_import_statements_removed=1,
        specialized_adapters_retained=2,
        original_guard_physical_lines=sum(r["end_line"] - r["line"] + 1 for r in inventory["eligible"]),
        physical_lines_removed=sum(p["lines_removed"] for p in per_file),
        physical_lines_added=sum(p["lines_added"] for p in per_file),
        net_physical_lines_saved=sum(p["lines_removed"] - p["lines_added"] for p in per_file),
        all_ast_statements_saved=sum(p["ast_statements_before"] - p["ast_statements_after"] for p in per_file),
        per_file=per_file,
        counting_rule="Executable AST statements count If, Raise, Expr(call), etc.; exclude definitions, imports and literal string docstrings. All-AST also counts those. Lines are unified-diff +/- lines, including blank helper separators. Import names added to four existing statements. One now-unused math import removed from budget endpoints; no unrelated cleanup credited.",
    )
    dump("metrics.json", metrics)
    return metrics


def capture(git_root, queue_root):
    # Pin comes from requests, not HEAD; only source identities retained.
    selected, scope = [], None
    queue_receipts = []
    for name in ["queue.jsonl", "extension-queue.jsonl"]:
        raw = (Path(queue_root) / name).read_bytes()
        queue_receipts.append(dict(path=str(Path(queue_root) / name), sha256=sha(raw)))
        for line in raw.splitlines():
            row = json.loads(line)
            if row["id"] not in {"GCL-X02", "GCL-X03", "GCL-X04", "GCL-X05"}:
                continue
            assert row["identity"]["revision"] == REV == row["packet"]["revision"]
            if scope is not None:
                assert scope == row["identity"]["scope"]
            scope = row["identity"]["scope"]
            selected.append(
                dict(
                    id=row["id"],
                    revision=REV,
                    source_proofs=row["packet"]["source_proofs"],
                )
            )
    assert len(selected) == 4 and scope
    paths = git("ls-tree", "-r", "--name-only", REV, root=git_root).decode().splitlines()
    paths = [
        p
        for p in paths
        if p.endswith(".py")
        and any(fnmatch.fnmatch(p, g) for g in scope["include"])
        and not any(fnmatch.fnmatch(p, g) for g in scope["exclude"])
    ]
    proc = subprocess.run(
        ["git", "-C", git_root, "cat-file", "--batch"],
        input="".join(REV + ":" + p + "\n" for p in paths).encode(),
        stdout=subprocess.PIPE,
        check=True,
    )
    offset = 0
    sources, scan, eligible, rejected = {}, [], [], []
    for path in paths:
        end = proc.stdout.index(b"\n", offset)
        blob, kind, size = proc.stdout[offset:end].decode().split()
        assert kind == "blob"
        offset = end + 1
        raw = proc.stdout[offset : offset + int(size)]
        offset += int(size) + 1
        sources[path] = raw
        source = raw.decode()
        hits, misses = guards(source, path)  # Parse every scoped file; fail on parse error.
        eligible.extend(hits)
        rejected.extend(misses)
        scan.append(
            dict(
                path=path,
                git_blob_sha1=blob,
                sha256=sha(raw),
                parsed=True,
                eligible=len(hits),
                near_misses=len(misses),
            )
        )
    assert offset == len(proc.stdout)
    # Verify frozen whole-file and exact function-span identities using Git bytes.
    for case in selected:
        for p in case["source_proofs"]:
            raw = sources[p["path"]]
            assert sha(raw) == p["file_sha256"]
            body = "\n".join(raw.decode().splitlines()[p["line"] - 1 : p["end_line"]])
            assert sha(body) == p["body_sha256"]
            blob = git("rev-parse", REV + ":" + p["path"], root=git_root).decode().strip()
            assert blob == p["git_blob_sha1"]
    keep = {r["path"] for r in eligible} | {r["path"] for r in rejected} | set(MODEL_FILES) | {COMMON, "LICENSE"}
    files = []
    for path in sorted(keep):
        raw = sources.get(path)
        if raw is None:
            raw = git("show", REV + ":" + path, root=git_root)
        dest = ROOT / "source" / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        files.append(
            dict(
                path=path,
                sha256=sha(raw),
                git_blob_sha1=git("rev-parse", REV + ":" + path, root=git_root).decode().strip(),
            )
        )
    dump(
        "provenance.json",
        dict(
            repository="BerriAI/litellm",
            revision=REV,
            git_root_read_only=git_root,
            commit_object_sha256=sha(git("cat-file", "commit", REV, root=git_root)),
            source_method="git cat-file --batch at explicit revision; never checkout content",
            frozen_requests=selected,
            queues=queue_receipts,
            files=files,
            labels="Prior tiny source-review and disputed claim-utility labels are retained externally; this study does not relabel either. No model outcomes used.",
        ),
    )
    dump(
        "coverage-scan.json",
        dict(
            scope=scope,
            revision=REV,
            parsed_python_files=len(scan),
            parse_failures=0,
            files=scan,
        ),
    )
    dump(
        "inventory.json",
        dict(revision=REV, eligible=eligible, excluded_near_misses=rejected),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--capture",
        action="store_true",
        help="Read exact Git and queues; snapshot under this script directory",
    )
    parser.add_argument("--git-root", default=GIT)
    parser.add_argument("--queue-root", default=QUEUE)
    args = parser.parse_args()
    if args.capture:
        capture(args.git_root, args.queue_root)
    print(json.dumps(build(), indent=2))
