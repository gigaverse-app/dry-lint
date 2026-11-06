"""Capture a pinned repository's sparse TF-IDF background for a maintained golden corpus."""

import argparse
from pathlib import Path

from dry_lint.bench_background import BenchBackground
from dry_lint.detector import Detector
from dry_lint.function_index import source_settings, tree_blobs
from dry_lint.git import git
from dry_lint.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-df", type=float, help="Override the pinned TF-IDF document-frequency cutoff")
    parser.add_argument("--diagnostic", action="store_true", help="Include tests/scripts; exclude only migrations")
    args = parser.parse_args()
    revision = git(args.root, "rev-parse", f"{args.revision}^{{commit}}")
    settings = source_settings(tree_blobs(args.root, revision, Settings()))
    if args.diagnostic:
        settings = settings.model_copy(update={"include": Settings().include, "exclude": ["*/migrations/*"]})
    detector = Detector.for_tree(args.root, revision, settings)
    max_df = args.max_df if args.max_df is not None else settings.comparer.options().get("max_df", 0.3)
    background = BenchBackground.capture(detector.functions, args.repository, revision, settings, max_df=max_df)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(background.encode())
    print(f"{len(background.documents)} functions, {len(background.document_frequency)} tokens: {args.out}")


if __name__ == "__main__":
    main()
