"""Find local Lean declarations explicitly cited in a dependency's documentation."""

import json
import os
import re
from collections import defaultdict
from pathlib import Path

from dry_lint.lean import LeanExtractor

# Only match a complete, backtick-quoted qualified identifier.
_CITATION = re.compile(rb"`([^\s`]+\.[^\s`]+)`")
_DECL = re.compile(r"\b(?:theorem|lemma|def|abbrev|opaque|instance|structure|class|inductive)\s+$")


def lean_sources(root):
    if not root.is_dir():
        raise ValueError(f"Missing source directory: {root}")
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.endswith(".lean"):
                yield Path(directory, name)


def dependency_citations(root, names):
    parser = LeanExtractor().parser
    citations = defaultdict(list)
    for path in lean_sources(root):
        source = path.read_bytes()
        if not any(name in names for name in _CITATION.findall(source)):
            continue
        # Docstrings inside namespaces and command wrappers can be nested nodes.
        pending = [parser.parse(source).root_node]
        while pending:
            node = pending.pop()
            # After imports the grammar can label Lean module docs as ordinary block comments.
            if node.type.endswith("comment") and node.text.startswith((b"/-!", b"/--")):
                for offset, line in enumerate(node.text.splitlines(), node.start_point.row + 1):
                    for name in sorted(set(_CITATION.findall(line))):
                        if name in names:
                            citations[name.decode()].append((path.relative_to(root).as_posix(), offset))
            elif node.type not in {"raw_string", "str_lit"}:
                pending.extend(reversed(node.named_children))
    return citations


def local_site(name, coords, lines):
    _, _, end, _, row, start_col, name_end_row, end_col = coords
    if not 0 <= row <= end < len(lines) or name_end_row != row:
        return None
    # Lean's selection ranges use UTF-16 code units. Check the source name as
    # an extra guard against stale artifacts and compiler-generated auxiliaries.
    line = lines[row].encode("utf-16-le")
    prefix = line[: 2 * start_col].decode("utf-16-le", errors="replace")
    if not prefix.strip() and row:
        prefix = lines[row - 1] + "\n"  # The name starts its line: the keyword ends the line before.
    spelling = line[2 * start_col : 2 * end_col].decode("utf-16-le", errors="replace").removeprefix("_root_.")
    if _DECL.search(prefix) and spelling and (name == spelling or name.endswith("." + spelling)):
        return row + 1, end - row + 1
    return None


def removed_lines(diffs):
    """The lines each unified diff removes, without indentation, by the path it removes them from."""
    removed = defaultdict(set)
    for diff in diffs:
        path = None
        rows = diff.read_text(encoding="utf-8", errors="replace").splitlines()
        for row, following in zip(rows, [*rows[1:], ""], strict=True):
            # A removed Lean comment also starts with `--- `; a file header is followed by `+++ `.
            if row.startswith("--- ") and following.startswith("+++ "):
                path = row[4:].split("\t")[0].removeprefix("a/")
            elif row.startswith("-") and path and row[1:].strip():
                removed[path].add(row[1:].strip())
    return removed


def _claimed(path, body, removed):
    """Whether a diff removes a quarter or more of the declaration's lines, and at least one."""
    body = [line.strip() for line in body if line.strip()]
    gone = set().union(*(lines for name, lines in removed.items() if name == path or name.endswith("/" + path)))
    return 4 * sum(line in gone for line in body) >= max(len(body), 1) and any(line in gone for line in body)


def find_upstream_citations(source_root, artifact_root, dependency_root, min_lines=1, claimed_diffs=()):
    if min_lines < 1:
        raise ValueError("min-lines must be positive")
    removed = removed_lines(claimed_diffs)
    sites = {}
    built = missing = claimed = 0
    for path in lean_sources(source_root):
        relative = path.relative_to(source_root)
        artifact = (artifact_root / relative).with_suffix(".ilean")
        if not artifact.is_file():
            missing += 1
            continue
        data = json.loads(artifact.read_bytes())
        if data.get("version") != 6 or not isinstance(data.get("decls"), dict):
            raise ValueError(f"{artifact}: expected .ilean version 6 with decls")
        built += 1
        lines = path.read_text(encoding="utf-8").splitlines()
        for name, coords in data["decls"].items():
            if coords[2] - coords[4] + 1 < min_lines:
                continue
            site = local_site(name, coords, lines)
            if site:
                sites[name] = (relative.as_posix(), *site, lines[site[0] - 1 : site[0] - 1 + site[1]])
    if not built:
        raise ValueError("No matching .ilean artifacts. Build the project and check the source and artifact roots.")
    citations = dependency_citations(dependency_root, {name.encode() for name in sites})
    matches = []
    for name, locations in citations.items():
        path, line, length, body = sites[name]
        if removed and _claimed(path, body, removed):
            claimed += 1
            continue
        matches.append(
            {
                "name": name,
                "path": path,
                "line": line,
                "lines": length,
                "citations": [{"path": p, "line": n} for p, n in sorted(locations)],
            }
        )
    matches.sort(key=lambda row: (-row["lines"], row["path"], row["line"], row["name"]))
    files = defaultdict(lambda: {"lines": 0, "declarations": 0, "cited_in": set()})
    for row in matches:
        entry = files[row["path"]]
        entry["lines"] += row["lines"]
        entry["declarations"] += 1
        entry["cited_in"].update(citation["path"] for citation in row["citations"])
    ranked = [{"path": path, **entry, "cited_in": sorted(entry["cited_in"])} for path, entry in files.items()]
    ranked.sort(key=lambda row: (-row["lines"], row["path"]))
    return {
        "built_modules": built,
        "unbuilt_modules": missing,
        "claimed_declarations": claimed,
        "files": ranked,
        "declarations": matches,
    }
