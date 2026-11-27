"""Find families of explicit Lean record constructions with recurring field assignments."""

import re
from collections import defaultdict
from itertools import combinations

from dry_lint.lean import _DECLARED, _NAME_PART, _signature, read_source
from dry_lint.lean_upstream import lean_sources

_FIELD = re.compile(rf"(?P<indent> +)(?P<name>{_NAME_PART})\s*:=[ \t]*")
_LINE = re.compile(r"[^\n]+")


def constructor_fields(lean, start, end):
    """Read direct, argument-free fields. Skip mixed or ambiguous layouts as a whole."""
    fields = {}
    starts = []
    indent = None
    for line in _LINE.finditer(lean.structure, start, end):
        content = line.group()
        if not content.strip():
            continue
        depth = len(content) - len(content.lstrip(" "))
        if indent is not None and depth > indent:
            continue
        field = _FIELD.match(content)
        if not field or (indent is not None and depth != indent) or field["name"] in fields:
            return {}
        indent = depth
        fields[field["name"]] = ()
        starts.append((field["name"], line.start(), line.start() + field.end()))
    stops = [row for _, row, _ in starts[1:]] + [end]
    for (name, _, value), stop in zip(starts, stops, strict=False):
        fields[name] = tuple(lean.tokens(value, stop))
    return fields


def constructors(path, source):
    lean = read_source(source)
    for command in lean.commands:
        if command.kind not in {"def", "abbrev", "instance"}:
            continue
        name = _DECLARED.match(lean.structure, command.keyword_end, command.end)
        signature = _signature(lean.structure, name.end(), command.end) if name else None
        if not signature or not lean.structure.startswith("where", signature[1]):
            continue
        fields = constructor_fields(lean, signature[1] + len("where"), command.end)
        if len(fields) >= 3 and all(fields.values()):
            yield {"path": path, "line": lean.line(name.start(1)), "name": name[1]}, fields


def find_constructor_families(source_root, min_sites=3):
    if min_sites < 2:
        raise ValueError("--min-sites must be at least 2")
    # A field name alone says little. Require the same field inventory and two matching assignments.
    shapes = defaultdict(list)
    for file in lean_sources(source_root):
        for site, fields in constructors(file.relative_to(source_root).as_posix(), file.read_text(encoding="utf-8")):
            shapes[tuple(sorted(fields))].append((site, fields))

    groups = []
    for shape, records in shapes.items():
        if len(records) < min_sites:
            continue
        supports = defaultdict(set)
        for index, (_, fields) in enumerate(records):
            for assignment in fields.items():
                supports[assignment].add(index)
        # Only intersect assignments that actually co-occur. Unrelated values of a common field
        # can otherwise make a large repository pay for a quadratic number of impossible pairs.
        pairs = set()
        for _, fields in records:
            frequent = [item for item in sorted(fields.items()) if len(supports[item]) >= min_sites]
            pairs.update(combinations(frequent, 2))
        memberships = {frozenset(supports[a] & supports[b]) for a, b in pairs}
        for members in sorted(tuple(sorted(indices)) for indices in memberships if len(indices) >= min_sites):
            shared = [name for name in shape if len({records[i][1][name] for i in members}) == 1]
            groups.append(
                {
                    "repeated_assignments": (len(members) - 1) * len(shared),
                    "fields": shape,
                    "shared_fields": shared,
                    "members": [records[i][0] for i in members],
                }
            )
    return sorted(groups, key=lambda g: (-g["repeated_assignments"], g["members"][0]["path"], g["members"][0]["line"]))
