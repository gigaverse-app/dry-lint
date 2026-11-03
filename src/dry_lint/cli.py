"""
The dry-lint command.

    dry-lint check                     # functions changed since the default branch: detect, judge, report
    dry-lint check --staged            # the staged changes (the pre-commit hook)
    dry-lint scan --limit 50           # the whole repository's backlog of look-alikes

In CI the two halves run as separate jobs, with files between them (docs/design.md):

    dry-lint detect --base $BASE_SHA --out candidates.json                 # runs the PR's code, needs no secrets
    dry-lint judge --candidates candidates.json --report report.json      # holds the keys, never runs PR code
    dry-lint report --from report.json --format markdown                  # or text, github, json, sarif, check-run

And to look closer:

    dry-lint explain src/a.py::shorten src/b.py::clip                      # why a pair is, or is not, reported
    dry-lint bench --gold gold.jsonl [--comparer]                          # measure the judge, or the comparer

Exit status: 0 when nothing blocks, 1 when a judged duplicate reaches `fail_at` (unless --warn-only), 2 on errors.
Duplicates between `report_at` and `fail_at` are reported as warnings and exit 0.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import httpx

from dry_lint import __version__
from dry_lint.bench import bench_comparer, bench_judge, load_gold
from dry_lint.detector import Detector, base_ref, changed_lines, touched
from dry_lint.git import git
from dry_lint.github import github_event
from dry_lint.judges import make_judge
from dry_lint.judging import Judging, open_store
from dry_lint.models import Candidate, CandidatesFile, Run
from dry_lint.plugins import load
from dry_lint.report import FORMATS, Report, as_json, render
from dry_lint.settings import PluginChoice, Settings


def repository_root(start: Path) -> Path:
    return Path(git(start, "rev-parse", "--show-toplevel"))


def run_info(root: Path, base: str | None) -> Run:
    """The repository, pull request and head commit, from the GitHub Actions environment when there is one."""
    pull = github_event().get("pull_request") or {}
    head = (pull.get("head") or {}).get("sha") or git(root, "rev-parse", "HEAD")
    return Run(repository=os.environ.get("GITHUB_REPOSITORY", ""), pull_request=pull.get("number"), head=head,
               base=base_ref(root, base))


def settings_for(root: Path, args: argparse.Namespace) -> Settings:
    """The repository's settings, with the judge the command line names, if any."""
    settings = Settings.load(root)
    if args.detector:
        settings.comparer = PluginChoice(use=args.detector)
    if args.fail_at is not None:
        settings = settings.model_copy(update={"fail_at": args.fail_at})
    if args.judge or args.judge_command:
        use = args.judge or settings.judge.use
        options = settings.judge.options() if use == settings.judge.use else {}
        if args.judge_command:
            options["command"] = args.judge_command
        settings = settings.model_copy(update={"judge": PluginChoice(use=use, **options)})
    return settings


def judged(candidates: list[Candidate], settings: Settings, root: Path, args: argparse.Namespace, run: Run,
           changed: int, refresh: bool = False, functions: int = 0, scope: str = "change") -> Report:
    judging = Judging.configured(settings, open_store(settings, root, args.store))
    findings = judging.findings(candidates, source=run, refresh=refresh)
    return Report.build(findings, settings, filtered=[c for c in candidates if c.filtered], run=run, changed=changed,
                        judge=judging.name, functions=functions, scope=scope)


def finish(report: Report, settings: Settings, args: argparse.Namespace) -> int:
    output = render(report, args.format, settings, args.warn_only)
    if output:
        print(output)
    if args.output:
        args.output.write_text(render(report, "markdown", settings, args.warn_only) + "\n")
    if args.report:
        args.report.write_text(as_json(report) + "\n")
    return 1 if any(f.blocking for f in report.findings) and not args.warn_only else 0


def check(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    detector, primary = detector_for(root, settings, args)
    changed = touched([f for f in detector.functions if not f.origin or f.origin.repository == primary],
                      changed_lines(root, args.base, args.staged))
    run = run_info(root, args.base)
    if primary:
        run.repository = primary
    report = judged(detector.candidates(changed), settings, root, args, run, len(changed),
                    functions=len(detector.functions))
    return finish(report, settings, args)


def detector_for(root: Path, settings: Settings, args: argparse.Namespace) -> tuple[Detector, str]:
    if args.repo:
        roots: dict[str, Path] = {}
        for spec in args.repo:
            name, separator, path = spec.partition("=")
            if not separator or not path:
                raise ValueError("--repo expects OWNER/NAME=PATH")
            if name in roots:
                raise ValueError(f"Duplicate repository: {name}")
            roots[name] = Path(path)
        if args.command == "scan" and args.format not in ("text", "json", "markdown"):
            raise ValueError("A workspace scan supports text, json and markdown; annotations belong to one repository")
        primary = next((name for name, path in roots.items() if repository_root(path).resolve() == root.resolve()), "")
        if args.command in {"check", "detect"} and not primary:
            raise ValueError("--repo must include the primary --root repository")
        return Detector.for_workspace(roots, settings), primary
    return Detector.for_repository(root, settings), ""


def scan(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    detector, _ = detector_for(root, settings, args)
    candidates = detector.scan()[: args.limit]
    report = judged(candidates, settings, root, args, run_info(root, None), 0, refresh=args.refresh,
                    functions=len(detector.functions), scope="repository")
    return finish(report, settings, args)


def detect(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    detector, primary = detector_for(root, settings, args)
    if args.all:
        changed, candidates = detector.functions, detector.scan()
    else:
        changed = touched([f for f in detector.functions if not f.origin or f.origin.repository == primary],
                          changed_lines(root, args.base, args.staged))
        candidates = detector.candidates(changed)
    run = run_info(root, args.base)
    if primary:
        run.repository = primary
    found = CandidatesFile(run=run, changed=len(changed), functions=len(detector.functions),
                           candidates=candidates)
    text = found.model_dump_json(indent=1)
    if args.out:
        args.out.write_text(text + "\n")
        proposed = sum(c.filtered is None for c in candidates)
        print(f"dry-lint: {len(changed)} changed function(s), {proposed} candidate pair(s) to judge, "
              f"{len(candidates) - proposed} settled by a rule; wrote {args.out}")
    else:
        print(text)
    return 0


def judge(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    found = CandidatesFile.model_validate_json(args.candidates.read_text())
    return finish(judged(found.candidates, settings, root, args, found.run, found.changed, functions=found.functions),
                  settings, args)


def report(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    return finish(Report.model_validate_json(args.source.read_text()), settings, args)


def explain(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    detector = Detector.for_repository(root, settings)
    a, b = detector.find(args.first), detector.find(args.second)
    pair = detector.pair(a, b, detector.comparer.similarity(a, b))
    lines = [f"{a.qualname} ~ {b.qualname}", f"  similarity {pair.similarity:.2f} ({pair.comparer})"]
    shared = getattr(detector.comparer, "shared", None)
    if shared:
        lines.append(f"  shared: {', '.join(shared(a, b)) or 'nothing'}")
    near = [other.qualname for other, _ in detector.neighbours(a)]
    rank = f"#{near.index(b.qualname) + 1} of" if b.qualname in near else "not among"
    lines.append(f"  proposed: {rank} the {len(near)} look-alike(s) of {a.name} above the floor")
    lines.append(f"  rule: {pair.filtered or 'none applies'}")
    store = open_store(settings, root, args.store)
    record = store.record(pair.key)
    if record is None:
        lines.append("  stored verdict: none")
    else:
        lookup = store.lookup(pair, record.verdict.judge, settings.reopen_margin)
        v = record.verdict
        lines.append(f"  stored verdict: {v.label} {v.score:.2f} by {v.judge} {v.judge_version}, {record.judged_at}")
        lines.append(f"  reused: {'yes' if lookup.verdict else 'no'}, {lookup.why}")
    print("\n".join(lines))
    return 0


def bench(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    gold = load_gold(args.gold)
    if args.comparer:
        result = bench_comparer(gold, Detector.for_repository(root, settings))
        print(result.model_dump_json(indent=2) if args.format == "json" else result.as_text())
        return 0
    chosen = make_judge(settings.judge)
    if chosen is None:
        raise ValueError("bench needs a judge: set TYPESAFE_AI_API_KEY, or pass --judge")
    result = bench_judge(gold, chosen, settings, load("extractors", settings.extractors[0]))
    print(result.model_dump_json(indent=2) if args.format == "json" else result.as_text(settings))
    return 0


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=Path.cwd(), help="Any path inside the repository.")
    common.add_argument("--repo", action="append", default=[], metavar="OWNER/NAME=PATH",
                        help="Repeat for every checkout; compare across repositories. Include --root for checks.")
    common.add_argument("--detector", help="Comparer plugin, overriding the settings: tfidf, dryer, or installed.")
    common.add_argument("--judge", help="Judge plugin, overriding the settings: auto, jev, command, none, or installed.")
    common.add_argument("--judge-command", help="For the command judge: a command reading the candidate on stdin.")
    common.add_argument("--store", type=Path, help="A folder for the verdict store, overriding the settings.")
    common.add_argument("--format", choices=FORMATS, default="text")
    common.add_argument("--output", type=Path, help="Also write the markdown report here, e.g. for a PR comment.")
    common.add_argument("--report", type=Path, help="Also write report.json here.")
    common.add_argument("--fail-at", type=float, help="Judge score at or above which a duplicate fails the run, "
                                                      "overriding fail_at in the settings.")
    common.add_argument("--warn-only", action="store_true", help="Report, but always exit 0.")

    main = argparse.ArgumentParser(prog="dry-lint", description="Find code that re-implements what already exists.")
    main.add_argument("--version", action="version", version=f"dry-lint {__version__}")
    commands = main.add_subparsers(dest="command", required=True)

    def where(command: argparse.ArgumentParser, everything: bool = False) -> None:
        group = command.add_mutually_exclusive_group()
        group.add_argument("--base", help="Compare HEAD with its merge base with this ref (default: origin/HEAD).")
        group.add_argument("--staged", action="store_true", help="Check the staged changes.")
        if everything:
            group.add_argument("--all", action="store_true", help="Propose the whole repository's backlog instead.")

    where(commands.add_parser("check", parents=[common], help="Detect, judge and report the functions a change touched."))
    sweep = commands.add_parser("scan", parents=[common], help="Judge look-alike pairs across the whole repository.")
    sweep.add_argument("--limit", type=int, default=50, help="Judge and show at most this many pairs, closest first.")
    sweep.add_argument("--refresh", action="store_true", help="Re-judge verdicts from older versions of the judge.")
    proposing = commands.add_parser("detect", parents=[common], help="Write candidates.json; no judge, no store.")
    where(proposing, everything=True)
    proposing.add_argument("--out", type=Path, help="Write candidates.json here (default: print it).")
    judging = commands.add_parser("judge", parents=[common], help="Judge a candidates.json and report.")
    judging.add_argument("--candidates", type=Path, required=True)
    rendering = commands.add_parser("report", parents=[common], help="Render a report.json.")
    rendering.add_argument("--from", dest="source", type=Path, required=True)
    explaining = commands.add_parser("explain", parents=[common], help="Why a pair is, or is not, reported.")
    explaining.add_argument("first", help="A qualified name, or a suffix only one function has.")
    explaining.add_argument("second")
    measuring = commands.add_parser("bench", parents=[common], help="Measure the judge, or the comparer, on a gold set.")
    measuring.add_argument("--gold", type=Path, required=True, help="gold.jsonl (docs/benchmark.md).")
    measuring.add_argument("--comparer", action="store_true", help="Measure the comparer's recall instead.")
    return main


COMMANDS = {"check": check, "scan": scan, "detect": detect, "judge": judge, "report": report, "explain": explain,
            "bench": bench}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = repository_root(args.root)
        return COMMANDS[args.command](root, settings_for(root, args), args)
    except (subprocess.CalledProcessError, httpx.HTTPError, ValueError, OSError) as error:
        detail = getattr(error, "stderr", None) or error
        print(f"dry-lint: {str(detail).strip()}", file=sys.stderr)
        return 2
