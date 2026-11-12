"""Manual, provider-free CLI probe. Run with the Python of an installed dry-lint[luau] wheel.

Creates fresh pinned OSS checkouts under --workspace, never executes their code, and writes summary.json.
Network access is needed only for git fetch. Deliberate mutations are separate from the unmodified inventory.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from dry_lint.luau import LuauExtractor
from dry_lint.luau_models import LuauModelExtractor

SOURCES = {
    "bump": ("kikito/bump.lua", "95d9e40b8aee295fc9d9b78ca214a829d6c21555", ["bump.lua"]),
    "rbxutil": (
        "Sleitnick/RbxUtil",
        "31f9120fca021e3dec275b42bc7047d626962082",
        ["modules/signal/init.luau", "modules/quaternion/init.luau", "modules/spring/init.luau"],
    ),
}


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE).strip()


def cli(root: Path, output: Path, mode: str, *args: str) -> dict:
    destination = output.with_suffix(".json")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "dry_lint",
            mode,
            "--root",
            str(root),
            "--judge",
            "none",
            *args,
            "--out" if mode == "detect" else "--report",
            str(destination),
        ],
        text=True,
        capture_output=True,
    )
    output.with_suffix(".log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"{mode} exited {result.returncode}: {result.stderr}")
    return json.loads(destination.read_text(encoding="utf-8"))


def pair_names(artifact: dict, lane: str) -> list[list[str]]:
    return [
        [p[side]["path"] + "::" + p[side]["name"] for side in ("new", "existing")]
        for p in artifact[lane]
        if not p["filtered"]
    ]


def probe(workspace: Path) -> dict:
    workspace.mkdir(parents=True, exist_ok=False)
    extractor, models = LuauExtractor(), LuauModelExtractor()
    result = {"python": sys.version, "adapters": {"luau": extractor.version, "luau-models": models.version}}
    for label, (repository, revision, paths) in SOURCES.items():
        root = workspace / label
        root.mkdir()
        git(root, "init", "--quiet")
        git(root, "fetch", "--depth=1", "https://github.com/" + repository + ".git", revision)
        git(root, "checkout", "--detach", "FETCH_HEAD")
        git(root, "config", "user.name", "dry-lint OSS probe")
        git(root, "config", "user.email", "probe@example.invalid")
        sources = {path: (root / path).read_text(encoding="utf-8") for path in paths}
        (root / ".dry-lint.toml").write_text(
            'extractors = ["luau"]\ninclude = ' + json.dumps([*paths, "probe/*"]) + '\npreset = "none"\n',
            encoding="utf-8",
        )
        git(root, "add", ".dry-lint.toml")
        git(root, "commit", "-qm", "chore: configure isolated probe")
        base = git(root, "rev-parse", "HEAD")
        original = cli(root, workspace / f"{label}-original", "detect", "--all")
        inventory = [f for path, source in sources.items() for f in models.functions(path, source)]
        row = {
            "repository": repository,
            "revision": revision,
            "files": len(paths),
            "source_lines": sum(len(s.splitlines()) for s in sources.values()),
            "functions": original["functions"],
            "models": original["models"],
            "model_fields": {f.qualname: sorted(f.declaration.fields) for f in inventory},
            "source_sha256": {p: hashlib.sha256(s.encode()).hexdigest() for p, s in sources.items()},
        }
        (root / "probe").mkdir()
        if label == "bump":
            source = sources["bump.lua"]
            functions = {f.name: f for f in extractor.functions("bump.lua", source)}
            copy_path = root / "probe/copied.lua"
            copy_path.write_text(
                "\n\n".join(functions[name].code for name in ("rect_getDiff", "rect_isIntersecting")) + "\n",
                encoding="utf-8",
            )
            added = (
                "local responseAliases = {touch = touch, cross = cross, slide = slide, bounce = bounce}\n"
                "local Distinct = {temperature = 293, active = true}\n"
            )
            assert source.count("return bump") == 1
            (root / "bump.lua").write_text(source.replace("return bump", added + "return bump"), encoding="utf-8")
            owners = source.replace("function World:", "function A.World:")
            spaced = owners.replace("A.World", "A . World")
            row["owner_layout_functions"] = [len(extractor.functions("bump.lua", s)) for s in (owners, spaced)]
            dynamic = "local handlers = {[key] = function(value)\nreturn value * 3\nend}\n"
            row["invented_computed_methods"] = len(extractor.functions("computed.lua", dynamic))
            before, after = "x2 - x1 - w1", "x2 - x1 - w1 + 1"
        else:
            quaternion = next(f for f in inventory if f.name == "Quaternion")
            copy_path = root / "probe/copied.luau"
            code = quaternion.code[quaternion.code.index("export type Quaternion") :]
            copy_path.write_text(
                code.replace("export type Quaternion =", "export type QuaternionCopy =", 1)
                + "\nlocal Distinct = {temperature = 293, active = true}\n",
                encoding="utf-8",
            )
            before, after = "X: number", "X: string"
        git(root, "add", "--all")
        git(root, "commit", "-qm", "test: inject labeled copies and unrelated controls")
        injected = cli(root, workspace / f"{label}-injected", "detect", "--base", base)
        cli(root, workspace / f"{label}-report", "check", "--base", base)
        row["copied_functions"] = pair_names(injected, "candidates")
        row["copied_models"] = pair_names(injected, "model_candidates")
        text = copy_path.read_text(encoding="utf-8")
        assert before in text
        copy_path.write_text(text.replace(before, after, 1), encoding="utf-8")
        git(root, "add", "--all")
        git(root, "commit", "-qm", "test: drift the copied contract")
        drift = cli(root, workspace / f"{label}-drift", "detect", "--base", base)
        lane = "candidates" if label == "bump" else "model_candidates"
        original_pairs = {p["new"]["name"]: p for p in injected[lane]}
        row["drift_retrieved"] = pair_names(drift, lane)
        row["drift_changed_hashes"] = sum(
            p["new"]["hash"] != original_pairs[p["new"]["name"]]["new"]["hash"]
            for p in drift[lane]
            if p["new"]["name"] in original_pairs
        )
        result[label] = row
    (workspace / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", required=True, type=Path, help="New directory for disposable checkouts and results."
    )
    print(json.dumps(probe(parser.parse_args().workspace.resolve()), indent=2))
