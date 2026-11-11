"""Add `introduced_by` to reference cases with a simple blame (stand-in until the miner's blame field is ready).

For every member, `git blame --line-porcelain -w -M -C -L start,end <parent> -- <path>` at the consolidation's
parent. A member's introducing commit is the commit that authored the majority of its non-blank, non-comment lines.
The later member is the one whose introducing commit is newest (committer time). Its record keeps the path and line
numbers those lines had in the introducing commit, so the replay can find the function there.

Usage: introduce.py [--root ROOT] OUT.jsonl CASE_ID [CASE_ID ...]
Reads ROOT/history/confirm-in-*.jsonl and confirm-out-*.jsonl; ROOT defaults to $DRY_LINT_REPLAY_ROOT, else the current directory.
"""

import argparse
import collections
import json
import os
import subprocess
from pathlib import Path

ROOT_ENV = "DRY_LINT_REPLAY_ROOT"
REPOS: dict[str, Path] = {}  # ROOT/repos/<name>; set in main
# No auto gc/maintenance while lazy fetches add objects: a repack of the 800 MB LiteLLM store would eat the disk.
GIT = ["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false"]


def cases(history: Path) -> dict[str, dict]:
    found = {}
    for name in ("confirm-in-1.jsonl", "confirm-in-2.jsonl"):
        for line in open(history / name, encoding="utf8"):
            row = json.loads(line)
            found[row["case_id"]] = row
    for name in ("confirm-out-1.jsonl", "confirm-out-2.jsonl"):
        for line in open(history / name, encoding="utf8"):
            row = json.loads(line)
            if row["case_id"] in found:
                found[row["case_id"]]["label"] = row["label"]
    return found


def blame(root: Path, rev: str, path: str, start: int, end: int) -> list[dict]:
    out = subprocess.run(
        [*GIT, "-C", str(root), "blame", "--line-porcelain", "-w", "-M", "-C", "-L", f"{start},{end}", rev, "--", path],
        capture_output=True,
        check=True,
    ).stdout.decode("utf8", "replace")
    lines, current = [], None
    for raw in out.splitlines():
        if current is None:
            sha, orig, final = raw.split()[:3]
            current = {"commit": sha, "orig_line": int(orig), "final_line": int(final)}
        elif raw.startswith("\t"):
            current["text"] = raw[1:]
            lines.append(current)
            current = None
        else:
            key, _, value = raw.partition(" ")
            if key in ("filename", "committer-time"):
                current[key] = value
    return lines


def introduced(root: Path, case: dict) -> dict:
    members = []
    for index, member in enumerate(case["members"]):
        lines = [
            line
            for line in blame(root, member["rev"], member["path"], member["start_line"], member["end_line"])
            if line["text"].strip() and not line["text"].strip().startswith("#")
        ]
        votes = collections.Counter(line["commit"] for line in lines)
        commit, count = votes.most_common(1)[0]
        mine = [line for line in lines if line["commit"] == commit]
        paths = collections.Counter(line["filename"] for line in mine)
        members.append(
            {
                "index": index,
                "commit": commit,
                "share": round(count / len(lines), 3),
                "time": int(mine[0]["committer-time"]),
                "path_at_commit": paths.most_common(1)[0][0],
                "lines_at_commit": sorted(
                    line["orig_line"] for line in mine if line["filename"] == paths.most_common(1)[0][0]
                ),
            }
        )
    later = max(members, key=lambda m: m["time"])
    member = case["members"][later["index"]]
    return {
        "commit": later["commit"],
        "member": later["index"],
        "path": member["path"],
        "qualname": member["qualname"],
        "path_at_commit": later["path_at_commit"],
        "lines_at_commit": later["lines_at_commit"],
        "share": later["share"],
        "method": "blame --line-porcelain -w -M -C, majority of non-blank non-comment lines at the parent",
        "members": [{k: m[k] for k in ("index", "commit", "share", "time")} for m in members],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path)
    parser.add_argument("case_ids", nargs="+")
    parser.add_argument("--root", type=Path, default=Path(os.environ.get(ROOT_ENV, ".")))
    args = parser.parse_args()
    out, wanted = args.out, args.case_ids
    REPOS.update({name: args.root / "repos" / name for name in ("litellm", "openhands")})
    known = cases(args.root / "history")
    done = set()
    if out.exists():
        done = {json.loads(line)["case_id"] for line in open(out, encoding="utf8")}
    with open(out, "a", encoding="utf8") as sink:
        for case_id in wanted:
            if case_id in done:
                continue
            case = known[case_id]
            case["introduced_by"] = introduced(REPOS[case["repo"]], case)
            sink.write(json.dumps(case) + "\n")
            sink.flush()
            intro = case["introduced_by"]
            print(
                case_id,
                case["kind"],
                "later",
                intro["qualname"],
                "by",
                intro["commit"][:10],
                "share",
                intro["share"],
                [(m["commit"][:8], m["share"]) for m in intro["members"]],
                flush=True,
            )


if __name__ == "__main__":
    main()
