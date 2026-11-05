"""Compare declaration retrieval on pinned inventories and independently reviewed pair labels.

This measures directed recall@k (new -> existing), not judgment accuracy. Labels sampled only
from a detector's own output cannot establish its recall; include a broader challenge set.
Optional --coma runs Valentine's schema-only COMA on the labelled pairs, not a repository index.
"""

import argparse
import json
import time
from pathlib import Path

from model_probe import Inventory
from pydantic import BaseModel

from dry_lint.comparers import TfidfComparer
from dry_lint.functions import words
from dry_lint.model_shapes import ModelComparer
from dry_lint.models import Function


class Label(BaseModel):
    new: str
    existing: str
    label: str
    reason: str


def fingerprint(function: Function, semantic: bool) -> Function:
    assert function.declaration is not None
    tokens = [f"field:{field}" for field in function.declaration.fields]
    if semantic:
        tokens += [f"name:{word}" for word in words(function.name)]
        tokens += [f"word:{word}" for field in function.declaration.fields for word in words(field)]
    return function.model_copy(update={"tokens": tokens})


def trial(inventory: Inventory, labels: list[Label], k: int) -> dict:
    variants = {
        "dice-3": ModelComparer(min_fields=3),
        "dice-2": ModelComparer(min_fields=2),
        "field-tfidf": TfidfComparer(min_similarity=0.7, min_similarity_small=0.7, max_df=1),
        "name-field-tfidf": TfidfComparer(min_similarity=0.7, min_similarity_small=0.7, max_df=1),
    }
    results = {}
    for name, comparer in variants.items():
        functions = [fingerprint(f, name == "name-field-tfidf") for f in inventory.models]
        by_name = {f.qualname: f for f in functions}
        scoped = [
            label
            for label in labels
            if label.new in by_name and label.existing in by_name and label.label != "borderline"
        ]
        start = time.perf_counter()
        comparer.index(functions)
        neighbours = {
            f.qualname: {other.qualname for other, _ in comparer.neighbours(f, k, lambda _: True)} for f in functions
        }
        hit = sum(label.existing in neighbours[label.new] for label in scoped if label.label == "duplicate")
        total = sum(label.label == "duplicate" for label in scoped)
        results[name] = {
            "hits": hit,
            "positives": total,
            "recall_at_k": hit / total if total else None,
            "negative_candidates": sum(
                label.existing in neighbours[label.new] for label in scoped if label.label == "separate"
            ),
            "negatives": sum(label.label == "separate" for label in scoped),
            "directed_candidates": sum(len(n) for n in neighbours.values()),
            "seconds": time.perf_counter() - start,
            "misses": [
                label.model_dump()
                for label in scoped
                if label.label == "duplicate" and label.existing not in neighbours[label.new]
            ],
        }
    return results


def coma_pairs(inventories: list[Inventory], labels: list[Label]) -> list[dict]:
    import pandas as pd
    from valentine import valentine_match
    from valentine.algorithms import Coma

    functions = {f.qualname: f for inventory in inventories for f in inventory.models}
    rows = []
    matcher = Coma(use_instances=False, use_schema=True)
    for label in labels:
        left, right = functions[label.new], functions[label.existing]
        a, b = list(left.declaration.fields), list(right.declaration.fields)
        start = time.perf_counter()
        matches = valentine_match(pd.DataFrame(columns=a), pd.DataFrame(columns=b), matcher)
        # A symmetric aggregate of best column matches: schema correspondence, not shared ownership.
        left_scores, right_scores = {}, {}
        for ((_, field_a), (_, field_b)), score in matches.items():
            left_scores[field_a] = max(left_scores.get(field_a, 0), float(score))
            right_scores[field_b] = max(right_scores.get(field_b, 0), float(score))
        rows.append(
            {
                **label.model_dump(),
                "score": (sum(left_scores.values()) + sum(right_scores.values())) / (len(a) + len(b)),
                "seconds": time.perf_counter() - start,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, action="append", required=True)
    parser.add_argument("--labels", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--neighbours", type=int, default=3)
    parser.add_argument("--coma", action="store_true")
    args = parser.parse_args()
    inventories = [Inventory.model_validate_json(path.read_text(encoding="utf8")) for path in args.inventory]
    labels = [Label.model_validate(row) for path in args.labels for row in json.loads(path.read_text(encoding="utf8"))]
    results = {inventory.repository: trial(inventory, labels, args.neighbours) for inventory in inventories}
    if args.coma:
        results["coma-labelled-pairs"] = coma_pairs(inventories, labels)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf8")
    print(
        json.dumps(
            {
                name: {variant: {k: v for k, v in row.items() if k != "misses"} for variant, row in result.items()}
                for name, result in results.items()
                if name != "coma-labelled-pairs"
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
