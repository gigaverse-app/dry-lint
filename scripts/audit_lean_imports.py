"""Join dry-lint candidates with the import closure of a freshly built Lake project."""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

#: `dry-lint scan --limit` when it is not given. The report does not say how many pairs the limit left out.
DEFAULT_SCAN_LIMIT = 50


def checkout_prefix(project):
    """Where the project sits in its Git checkout, such as `proof/`: a scan names files from the top of it."""
    found = subprocess.run(["git", "rev-parse", "--show-prefix"], cwd=project, capture_output=True, text=True)
    return found.stdout.strip() if found.returncode == 0 else ""


def import_graph(project, source_root, artifact_root):
    """Read imports from Lean itself and require an artifact for every source module."""
    graph = {}
    paths = {}
    prefix = checkout_prefix(project)
    for source in sorted(source_root.rglob("*.lean")):
        relative = source.relative_to(source_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        module = ".".join(relative.with_suffix("").parts)
        artifact = (artifact_root / relative).with_suffix(".ilean")
        with artifact.open(encoding="utf-8") as file:
            data = json.load(file)
        if data.get("version") != 6 or data.get("module") != module or "directImports" not in data:
            raise ValueError(f"{artifact}: expected Lean .ilean version 6 for {module}, with directImports")
        graph[module] = {name for name, *_ in data["directImports"]}
        paths[prefix + source.relative_to(project).as_posix()] = module
    return graph, paths


def closure(graph, roots):
    pending = list(roots)
    seen = set()
    while pending:
        module = pending.pop()
        if module not in seen and module in graph:
            seen.add(module)
            pending.extend(graph[module])
    return seen


def components(graph, modules):
    """Group modules outside the closure by imports in either direction."""
    edges = {module: graph[module] & modules for module in modules}
    for module in modules:
        for dependency in graph[module] & modules:
            edges[dependency].add(module)
    remaining = set(modules)
    while remaining:
        group = closure(edges, [min(remaining)])
        yield group
        remaining.difference_update(group)


def summarize(graph, paths, roots, scan):
    reachable = closure(graph, roots)
    matches = defaultdict(list)
    for finding in scan["findings"]:
        candidate = finding["candidate"]
        first, second = candidate["new"], candidate["existing"]
        if first.get("origin") is not None or second.get("origin") is not None:
            continue
        if paths.get(first["path"]) in reachable:
            first, second = second, first
        outside, inside = paths.get(first["path"]), paths.get(second["path"])
        if outside in graph and outside not in reachable and inside in reachable:
            matches[outside].append(
                {
                    "outside": {key: first[key] for key in ("path", "line", "name")},
                    "inside": {key: second[key] for key in ("path", "line", "name")},
                    "similarity": candidate["similarity"],
                }
            )
    groups = [
        {"modules": sorted(group), "matches": [match for module in sorted(group) for match in matches[module]]}
        for group in components(graph, graph.keys() - reachable)
    ]
    groups.sort(key=lambda group: (-len(group["matches"]), -len(group["modules"]), group["modules"]))
    return {
        "entry_modules": sorted(set(roots)),
        "project_modules": len(graph),
        "reachable_modules": len(reachable),
        "outside_import_closure": groups,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan_report", type=Path, help="Local dry-lint scan JSON from the same checkout")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root")
    parser.add_argument("--source-dir", type=Path, default=Path("src"), help="Lake source directory within the project")
    parser.add_argument("--artifacts", type=Path, default=Path(".lake/build/lib/lean"), help="Lean artifact directory")
    parser.add_argument(
        "--entry", action="append", required=True, help="Module to keep, such as Main. Repeat for each."
    )
    args = parser.parse_args(argv)
    try:
        graph, paths = import_graph(args.root, args.root / args.source_dir, args.root / args.artifacts)
        missing = set(args.entry) - graph.keys()
        if missing:
            raise ValueError("Entry modules absent from the source inventory: " + ", ".join(sorted(missing)))
        scan = json.loads(args.scan_report.read_bytes())
        if len(scan["findings"]) == DEFAULT_SCAN_LIMIT:
            print(
                f"{args.scan_report}: exactly {DEFAULT_SCAN_LIMIT} pairs, the default `scan --limit`. If the scan "
                "printed that it shows the closest pairs of more, run it again with a larger --limit: "
                "this audit sees only the pairs in the file.",
                file=sys.stderr,
            )
        report = summarize(graph, paths, args.entry, scan)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
