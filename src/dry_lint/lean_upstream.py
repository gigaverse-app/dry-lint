"""Find local Lean declarations explicitly cited in a dependency's documentation."""

import json
import os
import re
from collections import defaultdict
from pathlib import Path

from dry_lint.lean import LeanExtractor

# Only match a complete, backtick-quoted qualified identifier.
_CITATION = re.compile(rb"`([^\s`]+\.[^\s`]+)`")
_DECL = re.compile(r"\b(?:theorem|lemma|def|abbrev|opaque)\s+$")


def lean_sources(root):
    if not root.is_dir():
        raise ValueError(f"Missing source directory: {root}")
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.endswith(".lean"):
                yield Path(directory, name)


def dependency_citations(root):
    parser = LeanExtractor().parser
    citations = defaultdict(list)
    for path in lean_sources(root):
        source = path.read_bytes()
        if not _CITATION.search(source):
            continue
        # Docstrings inside namespaces and command wrappers can be nested nodes.
        pending = [parser.parse(source).root_node]
        while pending:
            node = pending.pop()
            if node.type in {"doc_comment", "module_doc_comment"}:
                for offset, line in enumerate(node.text.splitlines(), node.start_point.row + 1):
                    for name in sorted(set(_CITATION.findall(line))):
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
    prefix = line[: 2 * start_col].decode("utf-16-le")
    spelling = line[2 * start_col : 2 * end_col].decode("utf-16-le").removeprefix("_root_.")
    if _DECL.search(prefix) and spelling and (name == spelling or name.endswith("." + spelling)):
        return row + 1, end - row + 1
    return None


def find_upstream_citations(source_root, artifact_root, dependency_root, min_lines=1):
    if min_lines < 1:
        raise ValueError("min-lines must be positive")
    citations = dependency_citations(dependency_root)
    matches = []
    built = missing = 0
    for path in lean_sources(source_root):
        relative = path.relative_to(source_root)
        artifact = (artifact_root / relative).with_suffix(".ilean")
        if not artifact.is_file():
            missing += 1
            continue
        data = json.loads(artifact.read_bytes())
        if data.get("version") != 6:
            raise ValueError(f"{artifact}: expected .ilean version 6")
        built += 1
        cited = citations.keys() & data["decls"].keys()
        if not cited:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for name in cited:
            site = local_site(name, data["decls"][name], lines)
            if site and site[1] >= min_lines:
                matches.append(
                    {
                        "name": name,
                        "path": relative.as_posix(),
                        "line": site[0],
                        "lines": site[1],
                        "citations": [{"path": p, "line": n} for p, n in sorted(citations[name])],
                    }
                )
    if not built:
        raise ValueError("No matching .ilean artifacts. Build the project and check the source and artifact roots.")
    matches.sort(key=lambda row: (-row["lines"], row["path"], row["line"], row["name"]))
    return {"built_modules": built, "unbuilt_modules": missing, "declarations": matches}
