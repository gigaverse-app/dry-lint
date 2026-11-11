"""Phase 2 replay: what the shipped `balanced` check would have done with a reference duplicate when its later copy
was introduced.

For each case: `dry-lint check --preset balanced` on the introducing commit I, against its first parent, through
the product's own library path (cli.check -> Detector.for_tree / changed_lines / Detector.candidates / feedback ->
cli.judged -> Judging + CampaignStore -> Report.build), with a fresh verdict store and a fresh campaign ledger, so
nothing is cached and the $0.04 allowance is new. The tree is read from git objects; nothing is checked out.

Usage:
  replay.py CASES.jsonl OUT.jsonl [--detect-only] [--max-usd 1.0] [--only ID,ID] [--labels yes,partial]

CASES rows are miner records with `introduced_by`: either a commit sha, or {"commit": sha, "member": index,
"path_at_commit": path, "lines_at_commit": [line, ...]} (introduce.py writes this form). OUT is appended to, one
JSON line per case; case_ids already in OUT without an "error" are skipped.
"""

import argparse
import ast
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

from dry_lint.detector import Detector, changed_lines, touched
from dry_lint.discovery import CampaignStore
from dry_lint.feedback import FILENAME, Feedback
from dry_lint.functions import extractor_for
from dry_lint.judging import Judging
from dry_lint.models import Run, pair_key
from dry_lint.plugins import load
from dry_lint.presets import resolve
from dry_lint.report import Report
from dry_lint.settings import Settings
from dry_lint.store import DirectoryStore, VerdictStore

ROOT_ENV = "DRY_LINT_REPLAY_ROOT"
NAMES = ("litellm", "openhands", "saleor", "zulip", "prefect", "netbox")
REPOS: dict[str, Path] = {}  # filled by configure(): ROOT/repos/<name>, one partial clone per repository
GIT = ["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false"]
FLOOR_GB = 3.0
# First loss, best first: a case takes the best outcome over its target pairs.
RANK = ["reported", "judged_no", "not_funded", "judge_failed", "never_proposed", "not_replayable"]


def configure(root: Path) -> None:
    """Point the harness at ROOT, which holds one clone per repository in ROOT/repos/<name>."""
    REPOS.update({name: root / "repos" / name for name in NAMES})


def git(root: Path, *args: str, check: bool = True, env: dict | None = None) -> str:
    done = subprocess.run([*GIT, "-C", str(root), *args], capture_output=True, check=False, env=env)
    if check and done.returncode:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {done.stderr.decode('utf8', 'replace')[-300:]}")
    return done.stdout.decode("utf8", "replace").strip() if done.returncode == 0 else ""


def free_gb() -> float:
    return shutil.disk_usage(next(iter(REPOS.values())).parent).free / 1e9


def pack_kb(root: Path) -> int:
    stats = dict(line.split(": ", 1) for line in git(root, "count-objects", "-v").splitlines() if ": " in line)
    return int(stats.get("size", 0)) + int(stats.get("size-pack", 0))


def prefetch(root: Path, commit: str, base: str, settings: Settings) -> int:
    """Batch-fetch, in one request, every blob the check reads that the partial clone lacks; returns how many.

    The want-list uses the product's own predicate (tree_blobs: config files and extractor-claimed paths at I) plus
    both sides of every file the diff touches (`git diff -U0 base...I` reads them all), so nothing is lazily
    fetched one object at a time.
    """
    extractors = [load("extractors", choice) for choice in settings.extractors]
    want = set()
    for entry in git(root, "ls-tree", "-rz", "--full-tree", commit).split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        if meta.startswith("100") and (path in (".dry-lint.toml", "pyproject.toml") or extractor_for(path, extractors)):
            want.add(meta.split()[2])
    for line in git(root, "diff-tree", "-r", "--no-renames", "--no-commit-id", base, commit).splitlines():
        old, new = line.split()[2:4]
        want |= {sha for sha in (old, new) if sha.strip("0")}
    env = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
    check = subprocess.run(
        [*GIT, "-C", str(root), "cat-file", "--batch-check"],
        input="".join(f"{sha}\n" for sha in sorted(want)).encode(),
        capture_output=True,
        env=env,
    ).stdout.decode()
    missing = [line.split()[0] for line in check.splitlines() if line.endswith(" missing")]
    if missing:
        done = subprocess.run(
            [
                *GIT,
                "-C",
                str(root),
                "-c",
                "fetch.negotiationAlgorithm=noop",
                "fetch",
                "-q",
                "origin",
                "--no-tags",
                "--no-write-fetch-head",
                "--recurse-submodules=no",
                "--stdin",
            ],
            input=("\n".join(missing) + "\n").encode(),
            capture_output=True,
        )
        if done.returncode:
            raise RuntimeError("prefetch failed: " + done.stderr.decode("utf8", "replace")[-300:])
    return len(missing)


def repository_settings(root: Path, commit: str) -> tuple[Settings, str]:
    """Settings.load at the commit (.dry-lint.toml, else [tool.dry-lint] in pyproject.toml), then `--preset balanced`."""
    note = "defaults"
    settings = Settings()
    try:
        for name in (".dry-lint.toml", "pyproject.toml"):
            raw = git(root, "show", f"{commit}:{name}", check=False)
            if raw:
                data = tomllib.loads(raw)
                settings = Settings.model_validate(
                    data if name == ".dry-lint.toml" else data.get("tool", {}).get("dry-lint", {})
                )
                note = name if name == ".dry-lint.toml" or data.get("tool", {}).get("dry-lint") else "defaults"
                break
    except Exception as error:  # an unreadable adopter config would fail `check`; record it and use defaults
        note = f"config error ({type(error).__name__}), defaults"
        settings = Settings()
    # settings_for(): `--preset balanced` then resolve(); the same as auto with an Anthropic key.
    return resolve(settings.model_copy(update={"preset": "balanced"})), note


def def_line(source: str, qualname: str) -> int | None:
    """The `def` line of a miner qualname (Class.method, outer.inner) in a module, or None."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    node, parts = tree, qualname.split(".")
    for part in parts:
        node = next(
            (
                child
                for child in ast.iter_child_nodes(node)
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == part
            ),
            None,
        )
        if node is None:
            return None
    return node.lineno


def containing(functions, path: str, lines: list[int]):
    """The extracted function in `path` that holds most of `lines` (nested functions belong to their parent)."""
    best, most = None, 0
    for function in functions:
        if function.path == path:
            count = sum(function.line <= line <= function.end_line for line in lines)
            if count > most or count == most and best is not None and function.lines < best.lines:
                best, most = function, count
    return best


def locate(root: Path, commit: str, functions, member: dict) -> tuple[object | None, str]:
    """The member as dry-lint extracts it at `commit`: by path and qualname, else by a unique name elsewhere."""
    source = git(root, "show", f"{commit}:{member['path']}", check=False)
    if source:
        line = def_line(source, member["qualname"])
        if line is not None:
            found = containing(functions, member["path"], [line])
            if found is not None:
                return found, "path+qualname" + (
                    " (nested: its parent function)"
                    if "." in member["qualname"] and found.name != member["qualname"].split(".")[-1]
                    else ""
                )
    # Renamed or moved since I: the closest code among the same file's functions and same-named ones elsewhere.
    leaf = member["qualname"].split(".")[-1].lstrip("_")
    pool = [f for f in functions if f.path == member["path"] or f.name.lstrip("_") == leaf]
    scored = sorted(
        ((difflib.SequenceMatcher(None, f.code, member["code"]).ratio(), f) for f in pool),
        key=lambda pair: -pair[0],
    )
    if scored and scored[0][0] >= 0.6:
        return scored[0][1], f"closest code at intro (ratio {scored[0][0]:.2f}; renamed or moved)"
    return None, f"not found at intro (best code ratio {scored[0][0]:.2f})" if scored else "not found at intro"


def intro_fields(case: dict) -> dict:
    value = case["introduced_by"]
    return {"commit": value} if isinstance(value, str) else value


def replay_case(case: dict, detect_only: bool) -> dict:
    started = time.time()
    root = REPOS[case["repo"]]
    intro = intro_fields(case)
    commit = git(root, "rev-parse", f"{intro['commit']}^{{commit}}")
    parents = git(root, "rev-list", "--parents", "-n", "1", commit).split()[1:]
    base = parents[0]
    kb_before = pack_kb(root)
    settings, config = repository_settings(root, commit)
    fetched = prefetch(root, commit, base, settings)

    # cli.check: detector_for (discovery on: Detector.for_tree), review_scope (changed_owners), reviewed (feedback).
    detector = Detector.for_tree(root, commit, settings)
    changed = touched(detector.functions, changed_lines(root, base, head=commit))
    raw = git(root, "show", f"{commit}:{FILENAME}", check=False)
    feedback = Feedback.model_validate_json(raw) if raw else Feedback()
    candidates = feedback.apply(detector.candidates(changed))

    # cli.judged: the campaign identity of a local branch check, but a fresh ledger and store per case.
    run = Run(
        head=commit,
        base=base,
        session=f"phase2-{case['case_id']}",
        revision=git(root, "rev-parse", f"{commit}^{{tree}}"),
    )
    folder = Path(tempfile.mkdtemp(prefix="phase2-"))
    try:
        store = VerdictStore(DirectoryStore(folder / "verdicts"))
        judging = Judging(settings, None, None, store) if detect_only else Judging.configured(settings, store)
        if not detect_only:
            judging.campaign = CampaignStore(
                folder / "discovery.sqlite3", run.model_copy(update={"repository": f"replay/{case['repo']}"})
            )
        findings = judging.findings(candidates, source=run)
        report = Report.build(
            findings,
            settings,
            filtered=[c for c in candidates if c.filtered],
            run=run,
            changed=len(changed),
            judge=judging.name,
            functions=len(detector.functions),
            judging=judging.summary(),
        )
        state = judging.campaign.snapshot() if judging.campaign else None
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    # Members as dry-lint extracts them at I. The later one through its blamed lines when given.
    members = []
    for index, member in enumerate(case["members"]):
        if index == intro.get("member") and intro.get("lines_at_commit"):
            found = containing(detector.functions, intro["path_at_commit"], intro["lines_at_commit"])
            how = "blamed lines" if found else "blamed lines not in an extracted function"
        else:
            found, how = locate(root, commit, detector.functions, member)
        similarity = round(difflib.SequenceMatcher(None, found.code, member["code"]).ratio(), 3) if found else None
        members.append(
            {
                "member": f"{member['path']}::{member['qualname']}",
                "at_intro": found.qualname if found else None,
                "how": how,
                "changed": bool(found and found.qualname in {f.qualname for f in changed}),
                "code_similarity_to_parent": similarity,
                "_f": found,
            }
        )
    if intro.get("member") is not None:
        later_index, later_how = intro["member"], "given"
    else:
        # A bare sha: the later copy is the located member that I changed (blame put its lines in I's diff).
        touched_members = [i for i, m in enumerate(members) if m["changed"]]
        later_index = touched_members[0] if touched_members else 0
        later_how = (
            "the only member changed at I"
            if len(touched_members) == 1
            else f"ambiguous: {len(touched_members)} members changed at I, took the first"
            if touched_members
            else "no member changed at I, took member 0"
        )
    later = members[later_index]
    by_key = {c.key: c for c in candidates}
    found_by_key = {f.candidate.key: f for f in report.findings}

    pairs = []
    for index, other in enumerate(members):
        if index == later_index:
            continue
        row = {
            "later": later["member"],
            "other": other["member"],
            "proposed": False,
            "lane": None,
            "route": None,
            "similarity": None,
            "filtered": None,
            "judged": False,
            "score": None,
            "label": None,
            "funded": None,
            "reported": False,
            "same_file": None,
        }
        a, b = later["_f"], other["_f"]
        if a is None or b is None:
            row["outcome"], row["why"] = "not_replayable", "member not located at the introducing commit"
        elif a.qualname == b.qualname:
            row["outcome"], row["why"] = "not_replayable", "both members are one extracted function (nested)"
        else:
            row["same_file"] = a.path == b.path
            candidate = by_key.get(pair_key(a.qualname, b.qualname))
            if candidate is None:
                row["outcome"] = "never_proposed"
                row["why"] = "no route" if (later["changed"] or other["changed"]) else "neither member changed"
            else:
                row.update(
                    lane=candidate.lane,
                    route=candidate.comparer,
                    similarity=candidate.similarity,
                    filtered=candidate.filtered,
                )
                finding = found_by_key.get(candidate.key)
                if candidate.filtered:
                    row["outcome"], row["why"] = "never_proposed", f"settled by a rule: {candidate.filtered}"
                elif candidate.lane == "relative":
                    row["outcome"], row["why"] = (
                        "never_proposed",
                        "relative lane: campaign checks never judge relatives",
                    )
                elif detect_only:
                    row["proposed"], row["outcome"] = True, "proposed"
                else:
                    row["proposed"] = True
                    verdict = finding.verdict if finding else None
                    if verdict is not None:
                        row.update(
                            judged=True,
                            funded=True,
                            score=verdict.score,
                            label=verdict.label,
                            reported=finding.reported,
                            cached=finding.cached,
                        )
                        row["outcome"] = "reported" if finding.reported else "judged_no"
                        if finding.reported != (verdict.score >= settings.report_at):
                            row["why"] = f"score and report disagree (label {verdict.label})"
                    elif finding is not None and finding.budget_deferred:
                        row.update(funded=False, outcome="not_funded")
                    else:
                        row.update(funded=True, outcome="judge_failed", why="call failed or was not admitted")
        pairs.append(row)
    outcomes = [p["outcome"] for p in pairs]
    order = RANK if not detect_only else ["proposed", "never_proposed", "not_replayable"]
    outcome = min(outcomes, key=order.index) if outcomes else "not_replayable"
    for m in members:
        m.pop("_f")
    lanes = {}
    for c in candidates:
        if c.filtered is None:
            lanes[f"{c.lane}:{c.comparer.split(':')[0]}"] = lanes.get(f"{c.lane}:{c.comparer.split(':')[0]}", 0) + 1
    answered = [a for a in state.attempts if a.status == "answered"] if state else []
    by_lane = {}
    for attempt in state.attempts if state else []:
        by_lane[attempt.lane] = by_lane.get(attempt.lane, 0) + 1
    policy = settings.discovery
    caps = []
    if state:
        if len(state.attempts) >= policy.calls_per_revision:
            caps.append("calls_per_revision")
        if by_lane.get("exploration", 0) >= policy.exploration_calls_per_revision:
            caps.append("exploration_calls_per_revision")
        if any(f.budget_deferred for f in report.findings) and not caps:
            caps.append("dollars (budget or exploration credit)")
    return {
        "later_how": later_how,
        "attempts_by_lane": by_lane,
        "caps_hit": caps,
        "case_id": case["case_id"],
        "repo": case["repo"],
        "kind": case["kind"],
        "label": case.get("label"),
        "introducing_commit": commit,
        "base": base,
        "consolidation": case["commit"],
        "later_member": later["member"],
        "other_members": [m["member"] for i, m in enumerate(members) if i != later_index],
        "members": members,
        "pairs": pairs,
        "outcome": outcome,
        "changed": len(changed),
        "functions": len(detector.functions),
        "candidates_total": len(candidates),
        "candidates_open": sum(c.filtered is None for c in candidates),
        "lanes": lanes,
        "judged_total": len(answered),
        "attempts_total": len(state.attempts) if state else 0,
        "reported_total": sum(f.reported for f in report.findings),
        "budget_deferred_total": sum(f.budget_deferred for f in report.findings),
        "spend_usd": round(state.usd, 6) if state else 0.0,
        "judge": judging.name,
        "config": config,
        "blobs_fetched": fetched,
        "seconds": round(time.time() - started, 1),
        "disk_delta_mb": round((pack_kb(root) - kb_before) / 1024, 1),
        "detect_only": detect_only,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--detect-only", action="store_true", help="No judge: candidates only, no spend.")
    parser.add_argument(
        "--max-usd", type=float, default=1.0, help="Stop before a case once the output's spend reaches this."
    )
    parser.add_argument("--only", default="", help="Comma-separated case ids.")
    parser.add_argument("--labels", default="yes,partial", help="Replay only cases with these labels ('' for all).")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get(ROOT_ENV, ".")),
        help=f"Folder holding repos/<name> clones (default: ${ROOT_ENV}, else the current directory).",
    )
    args = parser.parse_args()
    configure(args.root)

    import dry_lint

    settings, _ = repository_settings(REPOS["openhands"], "HEAD")
    print(
        "dry_lint from",
        Path(dry_lint.__file__).parent,
        "| preset",
        settings.preset,
        "| judge",
        settings.judge.use,
        settings.judge.options(),
        "| report_at",
        settings.report_at,
        "| budget",
        settings.budget.usd,
        "| exploration",
        [c.use for c in settings.discovery.comparers],
        flush=True,
    )
    assert settings.preset == "balanced" and settings.judge.use == "langchain" and settings.report_at == 0.4
    if not args.detect_only and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set; export it in the environment, or use --detect-only")

    rows = [json.loads(line) for line in open(args.out, encoding="utf8")] if args.out.exists() else []
    done = {r["case_id"] for r in rows if "error" not in r}
    spent = sum(r.get("spend_usd", 0) for r in rows)
    only = set(filter(None, args.only.split(",")))
    labels = set(filter(None, args.labels.split(",")))
    with open(args.out, "a", encoding="utf8") as sink:
        for line in open(args.cases, encoding="utf8"):
            case = json.loads(line)
            if case["case_id"] in done or (only and case["case_id"] not in only):
                continue
            if labels and case.get("label") not in labels or not case.get("introduced_by"):
                continue
            if spent >= args.max_usd:
                print(f"stopping: ${spent:.4f} spent, cap ${args.max_usd}", flush=True)
                break
            if free_gb() < FLOOR_GB + 0.3:
                print(f"stopping: {free_gb():.2f} GB free", flush=True)
                break
            free_before = free_gb()
            try:
                row = replay_case(case, args.detect_only)
            except Exception as error:
                row = {
                    "case_id": case["case_id"],
                    "repo": case["repo"],
                    "error": f"{type(error).__name__}: {str(error)[:300]}",
                }
            row["free_gb_before"], row["free_gb_after"] = round(free_before, 2), round(free_gb(), 2)
            spent += row.get("spend_usd", 0)
            sink.write(json.dumps(row) + "\n")
            sink.flush()
            print(
                case["case_id"],
                row.get("outcome", row.get("error")),
                [p.get("outcome") for p in row.get("pairs", [])],
                "changed",
                row.get("changed"),
                "cands",
                row.get("candidates_total"),
                "judged",
                row.get("judged_total"),
                "$",
                row.get("spend_usd"),
                row.get("seconds"),
                "s",
                "disk",
                row.get("disk_delta_mb"),
                "MB",
                flush=True,
            )


if __name__ == "__main__":
    main()
