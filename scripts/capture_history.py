"""Capture historical PR trees without checking out or executing their code. Outputs contain private source.

Input: JSON list of {repository, root, number, base, commits}; commits are the ordered GitHub PR commit list.
Use immutable SHAs fetched into the local clone. Each output JSON is a ReplayInput for one PR.
"""

import argparse
import fnmatch
import json
import platform
import subprocess
from pathlib import Path

from probe_coverage import candidate_sources
from pydantic import BaseModel
from replay_coverage import ReplayInput

from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector, changed_lines, touched
from dry_lint.extractors import PythonExtractor
from dry_lint.git import git
from dry_lint.models import Run
from dry_lint.settings import Settings


class History(BaseModel):
    repository: str
    root: Path
    number: int
    base: str
    commits: list[str]


def tree_sources(root: Path, revision: str, settings: Settings) -> dict[str, str]:
    """Read Python blobs directly from this immutable tree; no current-tree or future-code fallback."""
    sha = git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    paths = [
        p
        for p in git(root, "ls-tree", "-r", "--name-only", "-z", sha).split("\0")
        if p.endswith(".py")
        and any(fnmatch.fnmatch(p, g) for g in settings.include)
        and not any(fnmatch.fnmatch(p, g) for g in settings.exclude)
    ]
    if any("\n" in p for p in paths):
        raise ValueError("newline-containing paths cannot be sent to cat-file --batch")
    if not paths:
        return {}
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input="".join(f"{sha}:{p}\n" for p in paths).encode(),
        capture_output=True,
        check=True,
    )
    data, offset, sources = result.stdout, 0, {}
    for path in paths:
        end = data.index(b"\n", offset)
        _, kind, length = data[offset:end].rsplit(b" ", 2)
        if kind != b"blob":
            raise ValueError(f"Expected a source blob at {sha}:{path}")
        size = int(length)
        sources[path] = data[end + 1 : end + 1 + size].decode("utf-8")
        offset = end + size + 2
    return sources


def capture(history: History, out: Path, depth: int = 20) -> ReplayInput:
    settings = Settings(extractors=["python"])
    extractor = PythonExtractor()
    steps, revisions = [], []
    for revision in history.commits:
        head = git(history.root, "rev-parse", "--verify", f"{revision}^{{commit}}")
        base = git(history.root, "merge-base", history.base, head)
        sources = tree_sources(history.root, head, settings)
        functions = [f for path, source in sources.items() for f in extractor.functions(path, source)]
        detector = Detector(functions, settings, TfidfComparer(), [extractor])
        changed = touched(functions, changed_lines(history.root, history.base, head=head))
        run = Run(repository=history.repository, pull_request=history.number, head=head, base=base)
        step = candidate_sources(detector, [f.qualname for f in changed], sources, run, depth)
        step.run_id = f"{history.repository}#{history.number}/{head}"
        steps.append(step)
        revisions.append(
            {
                "head": head,
                "merge_base": base,
                "functions": len(functions),
                "changed": len(changed),
                "proposed": {name: len(s.candidates) for name, s in step.sources.items()},
            }
        )
        print(history.repository, history.number, head[:8], len(changed), "changed functions", flush=True)
    payload = ReplayInput(steps=steps)
    out.mkdir(parents=True, exist_ok=True)
    (out / "replay.json").write_text(payload.model_dump_json(), encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "history": history.model_dump(mode="json"),
                "depth": depth,
                "revisions": revisions,
                "python": platform.python_version(),
                "settings": settings.model_dump(mode="json"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=20)
    args = parser.parse_args()
    for raw in json.loads(args.manifest.read_text(encoding="utf-8")):
        history = History.model_validate(raw)
        target = args.out / f"{history.repository.split('/')[-1]}-{history.number}"
        if (target / "replay.json").exists():
            previous = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            if previous["history"] != history.model_dump(mode="json") or previous["depth"] != args.depth:
                raise ValueError(f"Existing capture has different provenance: {target}")
            print("Already captured", target.name, flush=True)
            continue
        capture(history, target, args.depth)


if __name__ == "__main__":
    main()
