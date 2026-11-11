"""Score the family answers against the labelled pairs, next to the single-pair judge on the same pairs.

Usage: score.py <jobs.jsonl> <family-answers.jsonl> <single-answers.jsonl>

A single-pair answer is one line: {"id", "score", "in", "out", "cw", "cr"}.
"""

import collections
import json
import random
import sys

meta = {j["id"]: j for j in map(json.loads, open(sys.argv[1], encoding="utf8"))}
single = {}
for line in open(sys.argv[3], encoding="utf8"):
    r = json.loads(line)
    if "score" in r:
        single[r["id"]] = r
fam = {}
for line in open(sys.argv[2], encoding="utf8"):
    r = json.loads(line)
    if "answer" in r:
        fam[r["id"]] = r


def pair_score(r, apart=True):
    """The labelled pair is function 1 and function slot+2: the best group that holds both."""
    target, best = r["slot"] + 2, 0.0
    for g in r["answer"]["groups"]:
        mem = {m["function"]: m for m in g["members"]}
        if 1 in mem and target in mem and (apart or not (mem[1]["keep_apart"] or mem[target]["keep_apart"])):
            best = max(best, g["score"])
    return best


def any_score(r):
    return max(
        (g["score"] for g in r["answer"]["groups"] if any(m["function"] == 1 for m in g["members"])), default=0.0
    )


ids = [i for i in fam if i in single]
dup = [i for i in ids if meta[i]["label"] == "duplicate"]
sep = [i for i in ids if meta[i]["label"] == "separate"]
print(f"{len(ids)} pairs: {len(dup)} duplicate, {len(sep)} separate")
arms = {"family": lambda i: pair_score(fam[i]), "single": lambda i: single[i]["score"]}


def auc(s, d, n):
    return sum((s(a) > s(b)) + 0.5 * (s(a) == s(b)) for a in d for b in n) / (len(d) * len(n))


rng = random.Random(1)
for name, s in arms.items():
    boots = sorted(auc(s, [rng.choice(dup) for _ in dup], [rng.choice(sep) for _ in sep]) for _ in range(300))
    print(
        f"{name}: AUC {auc(s, dup, sep):.3f} [{boots[7]:.3f}, {boots[292]:.3f}]",
        " ".join(
            f"| >={t}: recall {sum(s(i) >= t for i in dup) / len(dup):.3f} FPR {sum(s(i) >= t for i in sep) / len(sep):.3f}"
            for t in (0.3, 0.4, 0.5, 0.6, 0.7)
        ),
    )
f, s = arms["family"], arms["single"]
for t in (0.4, 0.5):
    print(
        f"at {t}: duplicates found by family only {sum(f(i) >= t > s(i) for i in dup)}, single only {sum(s(i) >= t > f(i) for i in dup)};"
        f" false reports family only {sum(f(i) >= t > s(i) for i in sep)}, single only {sum(s(i) >= t > f(i) for i in sep)}"
    )
print(
    "changed function in some group >=0.5: duplicate-labelled",
    round(sum(any_score(fam[i]) >= 0.5 for i in dup) / len(dup), 3),
    "separate-labelled",
    round(sum(any_score(fam[i]) >= 0.5 for i in sep) / len(sep), 3),
)
rows = [fam[i] for i in ids]


def usd(r):
    return (r["in"] + 1.25 * r["cw"] + 0.1 * r["cr"]) * 0.1e-6 + r["out"] * 0.5e-6


print("groups per cluster", collections.Counter(len(r["answer"]["groups"]) for r in rows))
print("group sizes", collections.Counter(len(g["members"]) for r in rows for g in r["answer"]["groups"]))
print(
    f"cost per cluster ${sum(map(usd, rows)) / len(rows):.5f}; per labelled pair single ${sum(usd({**single[i], 'cw': single[i].get('cw', 0), 'cr': single[i].get('cr', 0)}) for i in ids) / len(ids):.5f}"
)
print(
    f"secs {sum(r['secs'] for r in rows) / len(rows):.1f}; out tokens {sum(r['out'] for r in rows) / len(rows):.0f}; thought {sum(r['thought'] for r in rows) / len(rows):.0f};"
    f" fallbacks {sum(r['fallback'] for r in rows)}; cache hits {sum(r['cr'] > 0 for r in rows)}"
)
print(
    "unexplained differences per group",
    round(
        sum(len(g["unexplained"]) for r in rows for g in r["answer"]["groups"])
        / max(1, sum(len(r["answer"]["groups"]) for r in rows)),
        2,
    ),
)
cover = sum(
    set(range(1, 7))
    <= (
        {m["function"] for g in r["answer"]["groups"] for m in g["members"]}
        | {u["function"] for u in r["answer"]["ungrouped"]}
    )
    for r in rows
)
print("clusters accounting for all six functions:", cover, "/", len(rows))
