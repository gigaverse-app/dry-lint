"""Phase 2: first-loss shares of the shipped balanced preset on the history reference."""

import collections
import glob
import json
import math
import sys
from pathlib import Path

D = Path(sys.argv[1])
cases = {}
for f in glob.glob(str(D / "in-*.jsonl")):
    if "-s" in Path(f).stem.split("in-")[1] or "-t" in Path(f).stem.split("in-")[1]:
        continue
    for line in open(f, encoding="utf8"):
        c = json.loads(line)
        cases[c["case_id"]] = c
rows = {}
for f in sorted(glob.glob(str(D / "out-*.jsonl"))):
    for line in open(f, encoding="utf8"):
        r = json.loads(line)
        if r.get("outcome"):
            rows.setdefault(r["case_id"], r)
ORDER = ["reported", "judged_no", "not_funded", "never_proposed"]


def wilson(k, n):
    if not n:
        return (0, 0)
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (100 * (c - h), 100 * (c + h))


def table(title, groups):
    print(f"\n## {title}")
    print("| group | n | " + " | ".join(ORDER) + " |")
    for name, rs in groups:
        rs = [r for r in rs if r["outcome"] in ORDER]
        n = len(rs)
        cells = []
        for o in ORDER:
            k = sum(r["outcome"] == o for r in rs)
            lo, hi = wilson(k, n)
            cells.append(f"{100 * k / n:.0f}% ({lo:.0f}-{hi:.0f})" if n else "-")
        print(f"| {name} | {n} | " + " | ".join(cells) + " |")


all_rows = list(rows.values())
print("cases", len(cases), "replayed", len(rows), collections.Counter(r["outcome"] for r in all_rows))
print("spend", round(sum(r.get("spend_usd") or 0 for r in all_rows), 2))
table("All replayable", [("all", all_rows)])
table(
    "By repository",
    [(repo, [r for r in all_rows if r["repo"] == repo]) for repo in sorted({r["repo"] for r in all_rows})],
)
table("By kind", [(k, [r for r in all_rows if r["kind"] == k]) for k in ("pair-delete", "pair-shrink", "family")])
table("By label", [(k, [r for r in all_rows if cases[r["case_id"]]["label"] == k]) for k in ("yes", "partial")])
table(
    "Copies written together?",
    [
        ("later copy added to an existing one", [r for r in all_rows if not cases[r["case_id"]].get("same_commit")]),
        ("both written in the same commit", [r for r in all_rows if cases[r["case_id"]].get("same_commit")]),
    ],
)
table(
    "Drifted before consolidation?",
    [
        ("drifted", [r for r in all_rows if cases[r["case_id"]].get("drift")]),
        ("not drifted", [r for r in all_rows if not cases[r["case_id"]].get("drift")]),
    ],
)

# Details of the losses.
pairs = [p for r in all_rows for p in r.get("pairs", [])]
print("\n## Pair-level")
print("pairs", len(pairs), collections.Counter(p.get("outcome") for p in pairs))
rep = [p for r in all_rows if r["outcome"] == "reported" for p in r.get("pairs", []) if p.get("reported")]
print("route of reported pairs:", collections.Counter((p.get("lane"), p.get("route")) for p in rep))
never = [r for r in all_rows if r["outcome"] == "never_proposed"]
print(
    "never_proposed why:",
    collections.Counter((p.get("why") or "")[:60] for r in never for p in r.get("pairs", [])).most_common(10),
)
jn = [
    p.get("score")
    for r in all_rows
    if r["outcome"] == "judged_no"
    for p in r.get("pairs", [])
    if p.get("score") is not None
]
print("judged_no scores:", sorted(jn))
nf = [r for r in all_rows if r["outcome"] == "not_funded"]
print("not_funded caps:", collections.Counter(str(r.get("caps_hit")) for r in nf).most_common(5))
print(
    "not_funded candidates_total median:",
    sorted(r.get("candidates_total", 0) for r in nf)[len(nf) // 2] if nf else None,
)
nr = [r for r in all_rows if r["outcome"] == "not_replayable"]
print(
    "not_replayable why:",
    collections.Counter((p.get("why") or "")[:60] for r in nr for p in r.get("pairs", [])).most_common(6),
)
