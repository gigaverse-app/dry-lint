"""
The dry-lint command.

    dry-lint check                     # functions changed since origin/main, judged, reported
    dry-lint check --staged            # the staged changes (the pre-commit hook)
    dry-lint check --base $BASE_SHA --format github
    dry-lint scan --limit 50           # the whole repository's backlog of look-alikes

Exit status: 0 when nothing is reported, 1 when a judged duplicate is at or above `report_at`, 2 on errors.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import httpx

from dry_lint import __version__
from dry_lint.detector import Candidate, Detector, changed_lines, touched
from dry_lint.judges import make_judge
from dry_lint.report import Finding, as_github, as_json, as_markdown, as_text
from dry_lint.settings import Settings
from dry_lint.store import VerdictStore


def repository_root(start: Path) -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def default_store(root: Path) -> Path:
    """Inside the git directory: kept between runs, never committed."""
    out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True, check=True)
    return (root / out.stdout.strip()).resolve() / "dry-lint" / "verdicts.jsonl"


def judged(candidates: list[Candidate], settings: Settings, judge_name: str, command: str | None,
           store_path: Path) -> list[Finding]:
    """Verdicts for every candidate: from the store when they still hold, from the judge otherwise."""
    judge = make_judge(judge_name, command)
    if judge is None:
        return [Finding(candidate=c) for c in candidates]
    store = VerdictStore(store_path)
    known = {i: store.lookup(c, settings.reopen_margin) for i, c in enumerate(candidates)}
    pending = [i for i, verdict in known.items() if verdict is None]
    fresh = dict(zip(pending, judge.judge([candidates[i] for i in pending], settings))) if pending else {}
    for i, verdict in fresh.items():
        store.remember(candidates[i], verdict)
    store.save()
    return [Finding(candidate=c, verdict=known[i] or fresh[i], cached=i not in fresh) for i, c in enumerate(candidates)]


def render(findings: list[Finding], settings: Settings, skipped: list[str], form: str) -> str:
    if form == "github":
        return as_github(findings, settings)
    if form == "markdown":
        return as_markdown(findings, settings)
    if form == "json":
        return as_json(findings, settings)
    return as_text(findings, settings, skipped)


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=Path.cwd(), help="Any path inside the repository.")
    common.add_argument("--judge", choices=["auto", "jev", "command", "none"], default="auto",
                        help="auto: Jev when TYPESAFE_AI_API_KEY is set, otherwise list candidates unjudged.")
    common.add_argument("--judge-command", help="For --judge command: a command reading the prompt on stdin.")
    common.add_argument("--store", type=Path, help="Verdict store (default: inside the git directory).")
    common.add_argument("--format", choices=["text", "github", "markdown", "json"], default="text")
    common.add_argument("--output", type=Path, help="Also write the markdown report here, e.g. for a PR comment.")
    common.add_argument("--warn-only", action="store_true", help="Report, but always exit 0.")

    main = argparse.ArgumentParser(prog="dry-lint", description="Find code that re-implements what already exists.")
    main.add_argument("--version", action="version", version=f"dry-lint {__version__}")
    commands = main.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", parents=[common], help="Judge the functions a change touched.")
    where = check.add_mutually_exclusive_group()
    where.add_argument("--base", help="Compare HEAD with its merge base with this ref (default origin/main).")
    where.add_argument("--staged", action="store_true", help="Check the staged changes.")
    scan = commands.add_parser("scan", parents=[common], help="List look-alike pairs across the whole repository.")
    scan.add_argument("--limit", type=int, default=50, help="Judge and show at most this many pairs, closest first.")
    return main


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = repository_root(args.root)
        settings = Settings.load(root)
        detector = Detector.for_repository(root, settings)
        if args.command == "check":
            changed = touched(detector.functions, changed_lines(root, args.base, args.staged))
            candidates, skipped = detector.candidates(changed)
        else:
            candidates, skipped = detector.scan()[: args.limit], []
        findings = judged(candidates, settings, args.judge, args.judge_command, args.store or default_store(root))
    except (subprocess.CalledProcessError, httpx.HTTPError, ValueError, OSError) as error:
        detail = getattr(error, "stderr", None) or error
        print(f"dry-lint: {str(detail).strip()}", file=sys.stderr)
        return 2
    output = render(findings, settings, skipped, args.format)
    if output:
        print(output)
    if args.output:
        args.output.write_text(as_markdown(findings, settings) + "\n")
    failed = any(f.reported(settings) for f in findings)
    return 1 if failed and not args.warn_only else 0

