"""Extract pinned model inventories and candidate pairs without executing repository code.

Run: uv run python scripts/model_probe.py --repository NAME=PATH --out DIRECTORY
Outputs are execution artifacts; keep DIRECTORY outside the code checkout.
"""

import argparse
import time
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from dry_lint.detector import Detector
from dry_lint.git import git
from dry_lint.models import CandidatesFile, Function, Run
from dry_lint.settings import Settings


class Inventory(BaseModel):
    repository: str
    revision: str
    seconds: float
    counts: dict[str, int]
    models: list[Function]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", action="append", required=True, help="NAME=PATH; reads committed HEAD")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-similarity", type=float, default=0.7)
    parser.add_argument("--min-fields", type=int, default=3)
    parser.add_argument("--neighbours", type=int, default=3)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        extractors=["python-models", "typescript-models"],
        comparer={"use": "model-shape", "min_similarity": args.min_similarity, "min_fields": args.min_fields},
        neighbours=args.neighbours,
        exclude=[*Settings().exclude, "*.test.*", "*.spec.*", "*__tests__*", "*.generated.*", "*node_modules/*"],
    )
    for spec in args.repository:
        name, separator, location = spec.partition("=")
        if not separator or not name or "/" in name or "\\" in name:
            parser.error("--repository needs a simple NAME=PATH")
        root = Path(location).resolve()
        revision = git(root, "rev-parse", "HEAD")
        start = time.perf_counter()
        detector = Detector.for_tree(root, revision, settings)
        pairs = detector.candidates(detector.functions)
        inventory = Inventory(
            repository=name,
            revision=revision,
            seconds=time.perf_counter() - start,
            counts=dict(Counter(f.declaration.kind for f in detector.functions if f.declaration)),
            models=detector.functions,
        )
        (args.out / f"{name}.inventory.json").write_text(inventory.model_dump_json(indent=2), encoding="utf-8")
        result = CandidatesFile(
            run=Run(repository=f"gigaverse-app/{name}", head=revision),
            changed=len(detector.functions),
            functions=len(detector.functions),
            candidates=pairs,
        )
        (args.out / f"{name}.candidates.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(name, revision, inventory.counts, f"{len(pairs)} pairs; {inventory.seconds:.2f}s", flush=True)


if __name__ == "__main__":
    main()
