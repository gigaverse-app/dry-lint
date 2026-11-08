"""
Collect share-goldens records from registered public repositories into staged benchmark panels.

    GITHUB_TOKEN=... uv run python scripts/collect_goldens.py [--registry docs/goldens/adopters.toml] [--out DIR]

Each repository in the registry opted in with ``share-goldens: "true"`` and has a license that allows its code
in a public panel. For each one, this script downloads the recent ``dry-lint-goldens-*`` artifacts (pointers:
repository, pinned revision, path, name, lines, verdict and how the label was learned), fetches both functions'
code at that revision from the public repository, and writes one panel per repository in the format of
``examples/*-gold.toml``.

Staged panels hold weak labels: "kept out" is inferred from a pair no longer being reported, and a dismissal
can be wrong. They never feed the benchmark's population estimates, which use blind three-vendor labels; run
``dry-lint bench --gold`` on them as diagnostic panels, or adjudicate them first. A repository that is private,
or whose revision cannot be read, contributes nothing.
"""

import argparse
import hashlib
import io
import json
import os
import sys
import textwrap
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from dry_lint.goldens import ARTIFACT, Golden

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
ROOT = Path(__file__).resolve().parents[1]


def registry(path: Path) -> list[dict]:
    return tomllib.loads(path.read_text(encoding="utf-8")).get("adopter", [])


def artifacts(client: httpx.Client, repository: str) -> list[Golden]:
    """Every golden in the repository's unexpired share-goldens artifacts; later pull requests win per pair."""
    found: dict[str, Golden] = {}
    listed = client.get(f"/repos/{repository}/actions/artifacts", params={"per_page": 100})
    listed.raise_for_status()
    for artifact in listed.json().get("artifacts", []):
        if artifact.get("expired") or not artifact["name"].startswith(ARTIFACT):
            continue
        archive = client.get(artifact["archive_download_url"], follow_redirects=True)
        archive.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            for name in bundle.namelist():
                for line in bundle.read(name).decode("utf-8").splitlines():
                    golden = Golden.model_validate_json(line)
                    if golden.repository != repository:
                        continue  # an artifact may only describe its own repository
                    previous = found.get(golden.key)
                    if previous is None or golden.pull_request >= previous.pull_request:
                        found[golden.key] = golden
    return list(found.values())


def code(client: httpx.Client, side) -> str | None:
    response = client.get(f"{RAW}/{side.repository}/{side.revision}/{side.path}")
    if response.status_code != 200:
        return None
    lines = response.text.splitlines()
    if side.end_line > len(lines):
        return None
    return textwrap.dedent("\n".join(lines[side.line - 1 : side.end_line])) + "\n"


def string(value: str) -> str:
    """A TOML basic string: JSON's escapes are valid TOML escapes."""
    return json.dumps(value, ensure_ascii=False)


def panel(repository: str, license_id: str, goldens: list[Golden], raw: httpx.Client) -> tuple[str, int]:
    lines = [
        f"# Staged goldens from {repository}, collected {datetime.now(UTC):%Y-%m-%d} with share-goldens.",
        "# Weak labels from merged pull requests: diagnostic only, never part of population estimates.",
        f"# {license_id} source: exact excerpts from the pinned revisions below.",
        "# Run: dry-lint bench --gold <this file>",
        "",
        "[provenance]",
        f"repository = {string(repository)}",
        f"license = {string(license_id)}",
        f"label_source = {string('share-goldens: outcomes of merged pull requests (see label_source per pair)')}",
        "",
    ]
    written = 0
    for golden in sorted(goldens, key=lambda g: (g.pull_request, g.key)):
        sides = [(name, side, code(raw, side)) for name, side in (("new", golden.new), ("existing", golden.existing))]
        if any(text is None for _, _, text in sides):
            continue
        written += 1
        verdict = golden.verdict
        lines += [
            "[[pair]]",
            f"case = {string(golden.key)}",
            f"label = {string(golden.label)}",
            f"label_source = {string(golden.label_source)}",
            f"repository = {string(repository)}",
            f"pull_request = {golden.pull_request}",
            f"revision = {string(golden.new.revision)}",
            f"similarity = {golden.similarity}",
            *([f"judged = {string(f'{verdict.judge} {verdict.label} {verdict.score:.2f}')}"] if verdict else []),
            "weight = 1.0",
            "",
        ]
        for name, side, text in sides:
            source = f"https://github.com/{repository}/blob/{side.revision}/{side.path}#L{side.line}-L{side.end_line}"
            lines += [
                f"[pair.{name}]",
                f"id = {string(f'{side.path}::{side.qualified}')}",
                f"source = {string(source)}",
                f"sha256 = {string(hashlib.sha256(text.encode()).hexdigest())}",
                f"code = {string(text)}",
                "",
            ]
    return "\n".join(lines), written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, default=ROOT / "docs" / "goldens" / "adopters.toml")
    parser.add_argument("--out", type=Path, default=Path("goldens-staging"))
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        parser.error("GITHUB_TOKEN is required: GitHub serves Actions artifacts only to authenticated requests")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    with httpx.Client(base_url=API, headers=headers, timeout=60) as api, httpx.Client(timeout=60) as raw:
        for adopter in registry(args.registry):
            repository = adopter["repository"]
            details = api.get(f"/repos/{repository}")
            if details.status_code != 200 or details.json().get("private", True):
                print(f"{repository}: not a public repository; skipped", file=sys.stderr)
                continue
            goldens = artifacts(api, repository)
            text, written = panel(repository, adopter["license"], goldens, raw)
            if not written:
                print(f"{repository}: no settled pairs yet")
                continue
            args.out.mkdir(parents=True, exist_ok=True)
            target = args.out / f"{repository.replace('/', '__')}.toml"
            target.write_text(text, encoding="utf-8")
            print(f"{repository}: {written} pair(s) -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
