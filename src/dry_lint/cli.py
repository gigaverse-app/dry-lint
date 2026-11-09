"""
The dry-lint command.

    dry-lint check                     # functions changed since the default branch: detect, judge, report
    dry-lint check --staged            # the staged changes (the pre-commit hook)
    dry-lint trailers .git/COMMIT_EDITMSG  # what that hook observed, into the commit's trailers
    dry-lint scan --limit 50           # the whole repository's backlog of look-alikes

In CI the two halves run as separate jobs, with files between them (docs/design.md):

    dry-lint detect --base $BASE_SHA --out candidates.json                 # runs the PR's code, needs no secrets
    dry-lint judge --candidates candidates.json --report report.json      # holds the keys, never runs PR code
    dry-lint report --from report.json --format markdown                  # or text, github, json, sarif, check-run

And to look closer:

    dry-lint explain src/a.py::shorten src/b.py::clip                      # why a pair is, or is not, reported
    dry-lint bench --gold gold.jsonl [--comparer]                          # measure the judge, or the comparer
    dry-lint bench --replay 50 [--preset jev+sonnet]                       # what check would have done on history

Exit status: 0 when nothing blocks, 1 when a judged duplicate reaches `fail_at` (unless --warn-only), 2 on errors.
Duplicates between `report_at` and `fail_at` are reported as warnings and exit 0.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

import httpx

from dry_lint import __version__, model_review, schema_policy
from dry_lint.baseline import Baseline, readme_key, require_complete, update_readme
from dry_lint.bench import bench_comparer, bench_judge, load_gold
from dry_lint.commits import Journal, append_trailers, staged_files, summary
from dry_lint.costs import ANSWER_TOKENS, ANSWERS, CHARS_PER_TOKEN, PRICES
from dry_lint.detector import Detector, base_ref, changed_lines, touched
from dry_lint.discovery import CampaignStore
from dry_lint.feedback import FILENAME, Decision, Feedback
from dry_lint.files import write_text
from dry_lint.functions import extractor_for, tracked_files, validate_source
from dry_lint.git import git, worktree
from dry_lint.github import github_event
from dry_lint.judges import make_escalation, make_judge
from dry_lint.judging import Judging, default_store, open_store
from dry_lint.labelling import label, labeller, sample, summarise
from dry_lint.ledger import counter_key
from dry_lint.models import Candidate, CandidatesFile, Function, Run, evidence
from dry_lint.plugins import load
from dry_lint.presets import LISTED, PRESETS, resolve
from dry_lint.replay import replay
from dry_lint.report import FAMILY_FORMAT_ERROR, FAMILY_FORMATS, FORMATS, Report, as_json, render
from dry_lint.settings import PluginChoice, Settings


def repository_root(start: Path) -> Path:
    return Path(git(start, "rev-parse", "--show-toplevel"))


def last_report(root: Path) -> Path:
    """Feedback follows this checkout's last check; worktrees share budget, not the review cursor."""
    return (root / git(root, "rev-parse", "--git-path", "dry-lint/last-report.json")).resolve()


def run_info(root: Path, base: str | None) -> Run:
    """The repository, pull request and head commit, from the GitHub Actions environment when there is one."""
    pull = github_event().get("pull_request") or {}
    head = (pull.get("head") or {}).get("sha") or git(root, "rev-parse", "HEAD")
    return Run(
        repository=os.environ.get("GITHUB_REPOSITORY", ""),
        pull_request=pull.get("number"),
        head=head,
        base=base_ref(root, base),
    )


def settings_for(root: Path, args: argparse.Namespace) -> Settings:
    """The repository's settings, with the judge the command line names, if any."""
    settings = Settings.load(
        root, staged=args.command in {"check", "detect", "model-baseline", "schema-check"} and args.staged
    )
    if args.detector:
        settings.comparer = PluginChoice(use=args.detector)
    if args.fail_at is not None:
        settings = settings.model_copy(update={"fail_at": args.fail_at})
    if args.preset:
        settings = settings.model_copy(update={"preset": args.preset})
    if args.budget_usd is not None:
        settings = settings.model_copy(update={"budget": settings.budget.model_copy(update={"usd": args.budget_usd})})
    if args.judge or args.judge_command:
        use = args.judge or settings.judge.use
        options = settings.judge.options() if use == settings.judge.use else {}
        if args.judge_command:
            options["command"] = args.judge_command
        settings = settings.model_copy(update={"judge": PluginChoice(use=use, **options)})
    return resolve(settings)


def judged(
    candidates: list[Candidate],
    settings: Settings,
    root: Path,
    args: argparse.Namespace,
    run: Run,
    changed: int,
    refresh: bool = False,
    functions: int = 0,
    scope: str = "change",
    family_discovery=None,
    idle: bool = False,
) -> Report:
    # `idle`: there is nothing to ask, so no judge starts and a missing key cannot fail the run.
    store = open_store(settings, root, args.store)
    judging = Judging(settings, None, None, store) if idle else Judging.configured(settings, store)
    judging.family_recovery = family_discovery
    if settings.discovery.enabled and scope == "change":
        if run.pull_request is None:
            run.session = args.session or run.session or git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False)
        run.revision = run.revision or run.head
        path = args.discovery_state or (args.store or default_store(root)) / "discovery.sqlite3"
        common = (root / git(root, "rev-parse", "--git-common-dir")).resolve()
        local = hashlib.sha256(str(common).encode()).hexdigest()
        campaign_run = run.model_copy(update={"repository": run.repository or local})
        judging.campaign = CampaignStore(path, campaign_run)
    findings = judging.findings(candidates, source=run, refresh=refresh)
    report = Report.build(
        findings,
        settings,
        filtered=[c for c in candidates if c.filtered],
        run=run,
        changed=changed,
        judge=judging.name,
        functions=functions,
        scope=scope,
        judging=judging.summary(),
    )
    if family_discovery is not None:
        report.families = family_discovery.findings
        report.family_exclusions = family_discovery.rejected
    return report


def prepare(report: Report, settings: Settings, args: argparse.Namespace, *, idle: bool = False) -> Report:
    # Preserve evidence on strict failures so CI can publish a failing check with the assessed head.
    if args.report:
        args.report.write_text(as_json(report) + "\n", encoding="utf-8")
    # Read-only checks report budget gaps as warnings.
    # Baseline ratchets still require complete assessment before changing accepted debt.
    # An idle staged check had no pair to assess, so it is complete without a judge.
    if (args.baseline or args.require_complete) and not idle:
        require_complete(report, check=True, allow_review_tasks=not args.baseline)
    if args.baseline:
        if args.warn_only:
            raise ValueError("Baseline enforcement cannot be combined with --warn-only")
        baseline, _ = baselines(repository_root(args.root), settings, args)
        report = baseline.apply(report)
    return report


def finish(report: Report, settings: Settings, args: argparse.Namespace, *, prepared: bool = False) -> int:
    if not prepared:
        report = prepare(report, settings, args)
    output = render(report, args.format, settings, args.warn_only)
    if output:
        print(output)
    if args.output:
        args.output.write_text(render(report, "markdown", settings, args.warn_only) + "\n")
    if args.report:
        args.report.write_text(as_json(report) + "\n")
    return 1 if any(f.blocking for f in report.findings) and not args.warn_only else 0


def baselines(root: Path, settings: Settings, args: argparse.Namespace) -> tuple[Baseline, Baseline | None]:
    """The proposed baseline, and the target branch's at `--baseline-ref` when it has one."""
    return Baseline.for_repository(root, args.baseline, settings, base=args.baseline_ref)


def removed(root: Path, detector: Detector, debt: Baseline, base: str, *, current: str = "HEAD") -> set[str]:
    """The debt's functions this change removed: present at its merge base `base`, gone now."""
    present = {f.qualname for f in detector.functions}
    missing = {name for e in debt.entries if e.state == "remaining" for name in e.hashes if name not in present}
    if not missing:
        return set()
    # Validate both trees once; a failed Git read must never masquerade as an empty/deleted file.
    tracked = {
        revision: set(git(root, "ls-tree", "-r", "--name-only", "-z", revision).split("\0"))
        for revision in {base, current}
    }
    found = set()
    for path in {name.split("::", 1)[0] for name in missing}:
        extractor = extractor_for(path, detector.extractors)
        if extractor is None:
            continue  # Without an extractor, absence is unknown rather than proof of removal.
        declarations = {}
        for revision in (base, current):
            source = git(root, "show", f"{revision}:{path}") if path in tracked[revision] else ""
            validate_source(extractor, path, source)
            declarations[revision] = {f.qualname for f in extractor.functions(path, source)}
        # A scope exclusion is not deletion. Check the actual source, including excluded files.
        found |= missing & (declarations[base] - declarations[current])
    return found


def require_family_format(settings: Settings, args: argparse.Namespace) -> None:
    """Refuse a family opt-in whose report format cannot show families, before any detection or plugin."""
    if settings.discovery.families is not None and args.format not in FAMILY_FORMATS:
        raise ValueError(FAMILY_FORMAT_ERROR)


def family_discovery(root: Path, settings: Settings, detector: Detector, changed, run: Run, *, staged: bool):
    """Nominate operation families among `changed` owners, settled by the same human and adopter decisions."""
    from dry_lint.family_discovery import FamilyDiscovery

    decisions = read_feedback(root, staged=staged, committed=not staged)
    native = {f.model_copy(update={"origin": f.origin or run}).qualname: f for f in detector.functions}

    def settled(a, b):
        # Human and adopter decisions settle a family; a call between two members does not, since a caller
        # and its callee can both repeat the operation.
        candidate = detector.pair(native[a.qualname], native[b.qualname], 0, calls=False)
        return decisions.apply([candidate])[0].filtered

    assert settings.discovery.families is not None, "family_discovery needs the explicit families opt-in"
    return FamilyDiscovery(detector.functions, changed, run, settings.discovery.families, settled=settled)


def changed_owners(
    root: Path, detector: Detector, primary: str, args: argparse.Namespace, *, whole_repository: bool = False
) -> list[Function]:
    """Select this repository's owners for function and model change review."""
    own = [f for f in detector.functions if not f.origin or f.origin.repository == primary]
    return own if whole_repository else touched(own, changed_lines(root, args.base, args.staged))


def review_scope(
    root: Path, detector: Detector, primary: str, args: argparse.Namespace, *, whole_repository: bool = False
) -> tuple[list[Function], Run]:
    """Identify the source snapshot and changed owners consistently in check and split detection."""
    # Whole-workspace function detection includes peers; changed-owner and model review stay primary-scoped.
    changed = detector.functions if whole_repository else changed_owners(root, detector, primary, args)
    run = run_info(root, args.base)
    run.revision = git(root, "write-tree") if args.staged else git(root, "rev-parse", "HEAD^{tree}")
    if primary:
        run.repository = primary
    return changed, run


def check(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    require_family_format(settings, args)
    detector, primary = detector_for(root, settings, args)
    changed, run = review_scope(root, detector, primary, args)
    debt = None
    if args.baseline:  # The target branch's debt: a pull request that also records its cleanup still earns it.
        proposed, target = baselines(root, settings, args)
        debt = target or proposed
    candidates = reviewed(
        root,
        debt.candidates(detector, changed) if debt else detector.candidates(changed),
        staged=args.staged,
        committed=settings.discovery.enabled and not args.staged,
    )
    families = None
    if settings.discovery.families is not None:
        if not settings.discovery.enabled:
            raise ValueError("Operation-family discovery requires discovery.enabled = true")
        families = family_discovery(root, settings, detector, changed, run, staged=args.staged)
    # The hook needs its judge, and so its key, only when the staged change has a pair to ask about. CI stays
    # strict: its judge starts even for a change with no pair, so a missing or misnamed secret turns it red.
    idle = args.staged and families is None and not any(c.filtered is None and c.lane != "relative" for c in candidates)
    report = judged(
        candidates,
        settings,
        root,
        args,
        run,
        len(changed),
        functions=len(detector.functions),
        family_discovery=families,
        idle=idle,
    )
    if debt:
        base = "HEAD" if args.staged else git(root, "merge-base", run.base, "HEAD")
        report.backlog = debt.cleared(report, removed(root, detector, debt, base, current=run.revision))
    report = prepare(report, settings, args, idle=idle)
    if model_review.enabled(settings, args.models, staged=args.staged):
        model_detector, model_changed, model_candidates, model_debt = model_candidates_for(root, settings, args, run)
        model_report = judge_models(
            root, settings, args, run, model_candidates, len(model_changed), len(model_detector.functions), model_debt
        )
        if model_debt:
            base = "HEAD" if args.staged else git(root, "merge-base", run.base, "HEAD")
            # The required ratchet already marks removed declarations cleaned in the proposed baseline.
            # Credit only debt outstanding at the base, while current allowances still enforce the check.
            target = model_review.baseline(root, settings, staged=args.staged, base=base, target=True)
            assert target is not None  # model_debt established a configured, validated baseline
            model_report.backlog = target.cleared(
                model_report, removed(root, model_detector, target, base, current=run.revision)
            )
        report = model_review.combine(report, model_report, model_debt)
    if (settings.discovery.enabled or args.staged) and not args.report:  # `dry-lint feedback` reviews this report
        target = last_report(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(as_json(report), encoding="utf-8")
    if args.staged:
        Journal.load(root).observe(report, staged_files(root)).save(root)
    status = finish(report, settings, args, prepared=True)
    if args.staged and args.format == "text" and (line := summary(root, run.base)):
        print(line)
    return status


def model_candidates_for(root: Path, settings: Settings, args: argparse.Namespace, run: Run):
    # Function peer indexes cannot stand in for model inventories. Checked-out peers can be extracted normally.
    model_args = argparse.Namespace(
        **{**vars(args), "repo_index": [], "require_complete": bool(args.require_complete or settings.models.baseline)}
    )
    if args.repo_index and len(args.repo) == 1:
        model_args.repo = []  # The only checked-out source is this repository; peer indexes hold functions only.
    detector, primary = detector_for(root, model_review.profile(settings), model_args)
    changed = changed_owners(root, detector, primary, args, whole_repository=args.command == "detect" and args.all)
    debt = model_review.baseline(root, settings, staged=args.staged, base=args.base or run.base)
    if debt:
        inventory = reviewed(root, debt.candidates(detector), staged=args.staged)
        updated = model_review.advance(debt, detector.functions, inventory, run.head)
        if updated.entries != debt.entries:
            suffix = " --staged" if args.staged else ""
            raise ValueError(
                f"Retire resolved model allowances with `dry-lint model-baseline --update{suffix}`, then stage the baseline"
            )
    pairs = debt.candidates(detector, changed) if debt else detector.candidates(changed)
    return detector, changed, reviewed(root, pairs, staged=args.staged), debt


def trailers(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    """The prepare-commit-msg hook: the duplicates the pre-commit hook saw settled go into the commit's trailers."""
    append_trailers(root, args.message)
    return 0


def reviewed(
    root: Path, candidates: list[Candidate], *, staged: bool = False, committed: bool = False
) -> list[Candidate]:
    return read_feedback(root, staged=staged, committed=committed).apply(candidates)


def read_feedback(root: Path, *, staged: bool = False, committed: bool = False) -> Feedback:
    if staged or committed:
        raw = git(root, "show", f"{'' if staged else 'HEAD'}:{FILENAME}", check=False)
        feedback = Feedback.model_validate_json(raw) if raw else Feedback()
    else:
        feedback = Feedback.read(root / FILENAME)
    return feedback


def detector_for(root: Path, settings: Settings, args: argparse.Namespace) -> tuple[Detector, str]:
    strict = bool(args.require_complete or args.baseline or args.command == "sweep")
    staged = args.command in {"check", "detect"} and args.staged
    if staged:
        if args.repo or args.repo_index:
            raise ValueError("Staged checks currently support a single repository")
        return Detector.for_tree(root, git(root, "write-tree"), settings, strict=strict), ""
    if args.repo or args.repo_index:
        if args.require_complete or args.baseline or args.command == "sweep":
            raise ValueError("Strict baselines currently cover one repository; run a separate check for peers")
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
        from dry_lint.function_index import FunctionIndex, extraction_contract

        indexes = []
        for spec in args.repo_index:
            identity, separator, path = spec.partition("=")
            name, at, commit = identity.partition("@")
            if not separator or not path or not at:
                raise ValueError("--repo-index expects OWNER/NAME@COMMIT=PATH")
            indexes.append(FunctionIndex.decode(Path(path).read_bytes(), name, commit, extraction_contract(settings)))
        return Detector.for_workspace(roots, settings, indexes=indexes), primary
    if settings.discovery.enabled and args.command in {"check", "detect"}:
        return Detector.for_tree(root, "HEAD", settings, strict=strict), ""
    return Detector.for_repository(root, settings, strict=strict), ""


def card_key(args: argparse.Namespace, readme: str) -> str:
    """
    The counter key for the README's sign: from --repository-id, else from the id GitHub Actions gives its own
    repository, else the key of the sign already in the block, so a sweep run locally keeps it. "" leaves it out.
    """
    if args.no_counter_card:
        return ""
    own = os.environ.get("GITHUB_REPOSITORY") == args.repository
    repository_id = args.repository_id or (os.environ.get("GITHUB_REPOSITORY_ID", "") if own else "")
    return counter_key(repository_id) if repository_id else readme_key(readme)


def sweep(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    if settings.discovery.families is not None:
        raise ValueError("Operation-family discovery requires a change campaign; use check with an immutable base")
    path = root / (args.baseline or Path(".dry-lint/baseline.json"))
    if args.init and path.exists():
        raise ValueError("Baseline already exists; rerun sweep without --init to ratchet it")
    if not args.init and not path.exists():
        raise ValueError(
            f"No baseline at {path.relative_to(root).as_posix()}. Accept the existing backlog once with "
            "`dry-lint sweep --init` (it needs a judge key; docs/sweeps.md), or pass --baseline PATH"
        )
    baseline = None if args.init else Baseline.read(path, settings)
    detector, _ = detector_for(root, settings, args)
    candidates = baseline.candidates(detector) if baseline else detector.candidates(detector.functions)
    # A whole-repository audit reads committed code; only matching committed review can settle its pairs.
    candidates = reviewed(root, candidates, committed=True)
    report = judged(
        candidates, settings, root, args, run_info(root, None), 0, functions=len(detector.functions), scope="repository"
    )
    require_complete(report)
    # Render the full backlog, while enforcing only duplicates outside the immutable accepted set.
    output_args = argparse.Namespace(**{**vars(args), "baseline": None, "warn_only": True})
    finish(report, settings, output_args)
    if baseline and any(f.blocking for f in baseline.apply(report).findings):
        print("dry-lint: new or changed duplicates found; baseline and cleanup totals were not updated")
        return 1
    updated = (
        baseline.advance(report, removed=removed(root, detector, baseline, baseline.checked_at))
        if baseline
        else Baseline.start(report, settings)
    )
    if not args.init and not args.update:
        print(
            f"dry-lint: audit found {updated.count('remaining')} remaining pairs; "
            f"{updated.count('cleaned') - baseline.count('cleaned')} newly cleaned. "
            "Use sweep --update to record the ratchet after reviewing the audit."
        )
        return 0
    readme = root / args.readme if args.readme else None
    content = None
    if readme:
        content = progress_content(root, settings, args, updated)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, updated.model_dump_json(indent=2) + "\n")
    write_text(path.parent / "progress.json", json.dumps(updated.badge(), indent=2) + "\n")
    if readme and content is not None:
        write_text(readme, content)
    print(
        f"dry-lint: {updated.count('cleaned')} pairs cleaned, {updated.count('remaining')} remaining, "
        f"{updated.count('dismissed')} dismissed; wrote {path}"
    )
    return 0


def baseline_migrate(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    """Record a reviewed policy change while preserving the target branch's exact debt allowances."""
    path = root / (args.baseline or Path(".dry-lint/baseline.json"))
    migrated, _ = Baseline.for_repository(root, path, settings, base=args.baseline_ref or "HEAD", migrate_policy=True)
    write_text(path, migrated.model_dump_json(indent=2) + "\n")
    print(
        f"dry-lint: migrated policy to {settings.preset}; preserved {len(migrated.entries)} exact allowances; no cleanup credited"
    )
    return 0


def progress_content(
    root: Path,
    settings: Settings,
    args: argparse.Namespace,
    functions: Baseline | None = None,
    models: Baseline | None = None,
) -> str:
    """Render existing reviewed inventories without running a judge or changing either baseline."""
    function_path = Path(
        (args.function_baseline if args.command == "model-baseline" else args.baseline) or ".dry-lint/baseline.json"
    )
    functions = functions or Baseline.model_validate_json((root / function_path).read_text(encoding="utf-8"))
    model_path = settings.models.baseline
    if models is None and model_path:
        models = Baseline.model_validate_json((root / model_path).read_text(encoding="utf-8"))
    text = (root / args.readme).read_text(encoding="utf-8")
    return update_readme(
        text,
        functions.markdown(
            args.repository,
            args.branch,
            function_path.parent.as_posix(),
            card_key(args, text),
            models=models,
            models_path=model_path or ".dry-lint/models.json",
            filename=function_path.name,
        ),
    )


def progress(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    if not args.readme:
        raise ValueError("progress requires --readme, for example --readme README.md")
    write_text(root / args.readme, progress_content(root, settings, args))
    print(f"dry-lint: refreshed function and model debt in {args.readme}; baselines unchanged")
    return 0


def scan(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    require_family_format(settings, args)
    detector, _ = detector_for(root, settings, args)
    found = detector.scan(settled=True)
    proposed = [c for c in found if c.filtered is None]
    # The limit applies to the pairs to judge; pairs a rule settled are only counted ("N skipped by rule").
    candidates = proposed[: args.limit] + [c for c in found if c.filtered is not None]
    if len(proposed) > args.limit:
        # On stderr, so --format json and sarif stay parseable.
        print(
            f"dry-lint: showing the {args.limit} closest of {len(proposed)} look-alike pairs; "
            "raise --limit to see more",
            file=sys.stderr,
        )
    run = run_info(root, None)
    # The backlog view: every function is an owner, so every repeated operation in the repository is nominated.
    families = (
        family_discovery(root, settings, detector, detector.functions, run, staged=False)
        if settings.discovery.families is not None
        else None
    )
    report = judged(
        candidates,
        settings,
        root,
        args,
        run,
        0,
        refresh=args.refresh,
        functions=len(detector.functions),
        scope="repository",
        family_discovery=families,
    )
    return finish(report, settings, args)


def require_split_compatible(settings: Settings) -> None:
    """Both halves of split CI must reject a family policy that needs a single change campaign."""
    if settings.discovery.families is not None:
        raise ValueError("Operation-family discovery currently requires check; split detect/judge is not supported")


def detect(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    require_split_compatible(settings)
    detector, primary = detector_for(root, settings, args)
    changed, run = review_scope(root, detector, primary, args, whole_repository=args.all)
    candidates = detector.scan() if args.all else detector.candidates(changed)
    found = CandidatesFile(
        run=run,
        changed=len(changed),
        functions=len(detector.functions),
        candidates=reviewed(
            root, candidates, staged=args.staged, committed=settings.discovery.enabled and not args.staged
        ),
    )
    if model_review.enabled(settings, args.models, staged=args.staged):
        model_detector, model_changed, pairs, _ = model_candidates_for(root, settings, args, run)
        found.model_candidates = pairs
        found.models, found.changed_models = len(model_detector.functions), len(model_changed)
    text = found.model_dump_json(indent=1)
    if args.out:
        args.out.write_text(text + "\n")
        proposed = sum(c.filtered is None for c in candidates)
        print(
            f"dry-lint: {len(changed)} changed function(s), {proposed} candidate pair(s) to judge, "
            f"{len(candidates) - proposed} settled by a rule; wrote {args.out}"
        )
    else:
        print(text)
    return 0


def judge_models(
    root: Path,
    settings: Settings,
    args: argparse.Namespace,
    run: Run,
    candidates: list[Candidate],
    changed: int,
    count: int,
    debt: Baseline | None,
) -> Report:
    profile = model_review.profile(settings)
    if settings.judge.use == "none" or not os.environ.get("TYPESAFE_AI_API_KEY"):
        profile = profile.model_copy(update={"judge": PluginChoice(use="none")})
    result = judged(model_review.allowances(candidates, debt), profile, root, args, run, changed, functions=count)
    # Model rankers never decide consolidation. Failed/budget-limited ranking is still an agent review task.
    if result.judge or settings.judge.use != "none":
        result.judge = result.judge or "source-review"
        for finding in result.findings:
            if finding.candidate.lane != "relative":
                finding.source_review = True
                finding.blocking = not finding.budget_deferred
                finding.reported = False
    return result


def judge(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    require_split_compatible(settings)
    found = CandidatesFile.model_validate_json(args.candidates.read_text())
    if args.models is True and found.model_candidates is None:
        raise ValueError(
            "Model review was requested but detection supplied no model inventory; rerun detection with models enabled"
        )
    result = prepare(
        judged(found.candidates, settings, root, args, found.run, found.changed, functions=found.functions),
        settings,
        args,
    )
    if found.model_candidates is not None and model_review.enabled(settings, args.models):
        debt = model_review.baseline(root, settings, base=args.baseline_ref)
        models = judge_models(
            root, settings, args, found.run, found.model_candidates, found.changed_models, found.models, debt
        )
        result = model_review.combine(result, models, debt)
    return finish(result, settings, args, prepared=True)


def report(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    return finish(Report.model_validate_json(args.source.read_text()), settings, args)


def feedback(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    source = args.source or last_report(root)
    report = Report.model_validate_json(source.read_bytes())
    matching = [f for f in report.findings if f.candidate.key == args.pair]
    if len(matching) != 1 or not (
        matching[0].reported
        or matching[0].review_required
        or args.action in {"accept", "dismiss"}
        and matching[0].candidate.new.declaration
    ):
        raise ValueError("Choose a reported or review-required pair key from this report")
    candidate = matching[0].candidate
    if candidate.new.declaration:
        settings = model_review.profile(settings)
    revision = git(root, "write-tree")
    if args.action == "accept":
        if not candidate.new.declaration or not candidate.existing.declaration:
            raise ValueError("Accepted model debt requires two model declarations")
        detector = Detector.for_tree(root, revision, settings, strict=True)
        functions = {f.qualname: f for f in detector.functions}
        names = (candidate.new.qualname, candidate.existing.qualname)
        if not all(name in functions for name in names) or evidence(
            detector.pair(*(functions[name] for name in names), candidate.similarity)
        ) != evidence(candidate):
            raise ValueError("The reviewed model evidence changed; rerun the check before accepting debt")
    if args.action == "fix":
        detector = Detector.for_tree(root, revision, settings)
        functions = {f.qualname: f for f in detector.functions}
        names = (candidate.new.qualname, candidate.existing.qualname)
        if all(name in functions for name in names):
            current = detector.pair(*(functions[name] for name in names), candidate.similarity)
            if evidence(current) == evidence(candidate):
                raise ValueError("Stage the repair before recording a fix; the reported source is unchanged")
    path = root / FILENAME
    decisions = Feedback.read(path)
    decisions.decisions.append(
        Decision(
            pair=candidate.key,
            evidence=evidence(candidate),
            action=args.action,
            reason=args.reason.strip(),
            reviewer=args.reviewer.strip(),
            revision=revision,
        )
    )
    decisions.write(path)
    print(f"Recorded {args.action} for {candidate.key} in {FILENAME}; review and stage this file.")
    return 0


def model_baseline(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    path = root / (args.baseline or settings.models.baseline or ".dry-lint/models.json")
    if args.init and path.exists():
        raise ValueError("Model baseline already exists; use --update to ratchet it")
    settings = settings.model_copy(
        update={"models": settings.models.model_copy(update={"baseline": path.relative_to(root).as_posix()})}
    )
    previous = (
        None
        if args.init
        else model_review.baseline(root, settings, staged=args.staged, base=args.baseline_ref or "HEAD")
    )
    updated = model_review.ratchet(
        root, settings, read_feedback(root, staged=args.staged), previous, staged=args.staged
    )
    if args.init or args.update:
        content = progress_content(root, settings, args, models=updated) if args.readme else None
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, updated.model_dump_json(indent=2) + "\n")
        if content is not None:
            write_text(root / args.readme, content)
    print(
        f"dry-lint models: {updated.count('remaining')} reviewed pairs remaining, {updated.count('cleaned')} cleaned, {updated.count('dismissed')} dismissed"
    )
    return 0


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


TYPICAL_PAIR_CHARS = 2_700  # the DRY prompt for an average gigaverse-ai pair: about 960 Sonnet tokens


def pair_usd(choice: PluginChoice | None, settings: Settings) -> str:
    """The estimated cost of one pair for a judge choice, from the price table, without building the judge."""
    if choice is None or choice.use == "none":
        return "-"
    if choice.use in ("claude-code", "codex"):
        return "subscription"
    model = choice.options().get("model") or {"anthropic": "claude-sonnet-5-5", "gemini": "gemini-3.1-pro-preview"}.get(
        choice.use, choice.use
    )
    rates = {**PRICES, **settings.prices}.get(model)
    if rates is None:
        return "unknown price"
    answer = ANSWERS.get(model, ANSWER_TOKENS)
    return f"${(TYPICAL_PAIR_CHARS / CHARS_PER_TOKEN * rates[0] + answer * rates[1]) / 1_000_000:.2g} per pair"


def scope_lines(root: Path, settings: Settings) -> list[str]:
    """Which tracked source files the settings put in scope, by top-level folder, so a wrong `include` shows."""
    extractors = [load("extractors", choice) for choice in settings.extractors]
    folders: dict[str, int] = {}
    for path in tracked_files(root, settings.include, settings.exclude):
        if extractor_for(path, extractors):
            folder = path.split("/", 1)[0] if "/" in path else "."
            folders[folder] = folders.get(folder, 0) + 1
    ranked = sorted(folders.items(), key=lambda item: (-item[1], item[0]))
    shown = ", ".join(f"{folder} {count}" for folder, count in ranked[:8]) + (", ..." if len(ranked) > 8 else "")
    return [
        f"scope: include {', '.join(settings.include)} - exclude {', '.join(settings.exclude) or 'nothing'}",
        f"  {sum(folders.values())} source files in scope" + (f": {shown}" if folders else ""),
        f"  {len(settings.patterns)} declared pattern(s)",
    ]


def config(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    """The resolved judging setup, the credentials that chose it (by name only), every preset, and the cost."""
    found = [
        v
        for v in ("TYPESAFE_AI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GEMINI_API_KEY")
        if os.environ.get(v)
    ]
    preset = PRESETS.get(settings.preset)
    explicit = sorted(
        f
        for f in ("judge", "escalate", "drop_below", "report_at", "fail_at")
        if f in Settings.load(root).model_fields_set
    )
    lines = [
        f"preset: {settings.preset}" + (f" - {preset.summary}" if preset else " - your own judge"),
        f"  credentials found: {', '.join(found) or 'none'}",
    ]
    if preset and preset.numbers:
        lines.append(f"  {'measured' if preset.measured else 'expected'}: {preset.numbers}")
    escalate = settings.escalate
    lines += [
        f"judge: {settings.judge.use}{' ' + str(settings.judge.options()) if settings.judge.options() else ''}"
        f" ({pair_usd(settings.judge, settings)})",
        "escalate: "
        + (
            f"{escalate.use} {escalate.options() or ''} on [{escalate.between[0]:g}, "
            f"{escalate.between[1]:g}) ({pair_usd(escalate, settings)})"
            if escalate
            else "none"
        ),
        f"thresholds: drop below {settings.drop_below:g} - report at {settings.report_at:g} - "
        f"fail at {max(settings.report_at, settings.fail_at):g}"
        + (f" - first judge alone at {escalate.first_at:g}" if escalate and escalate.first_at is not None else "")
        + (f" (set explicitly: {', '.join(explicit)})" if explicit else ""),
        f"budget: ${settings.budget.usd:g} per pull request at list price, subscriptions included; "
        f"{settings.budget.subscription_calls} "
        "subscription calls",
        *scope_lines(root, settings),
        "",
        "presets:",
    ]
    for name in LISTED:
        p = PRESETS[name]
        missing = [v for v in p.needs if not os.environ.get(v)]
        lines.append(
            f"  {'*' if name == settings.preset else ' '} {name:22} {p.summary}"
            + (f"  [needs {', '.join(missing)}]" if missing else "")
            + ("  [named only]" if not p.automatic else "")
        )
    print("\n".join(lines))
    return 0


def bench(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    if args.replay is not None:
        return bench_replay(root, settings, args)
    if args.label is not None:
        raise ValueError("--label labels a replay's pairs: use it with --replay")
    gold = load_gold(args.gold)
    if args.comparer:
        result = bench_comparer(gold, Detector.for_repository(root, settings))
        print(result.model_dump_json(indent=2) if args.format == "json" else result.as_text())
        return 0
    chosen = make_judge(settings.judge)
    if chosen is None:
        raise ValueError("bench needs a judge: set TYPESAFE_AI_API_KEY, or pass --judge")
    escalation = make_escalation(settings)
    result = bench_judge(gold, chosen, settings, load("extractors", settings.extractors[0]), escalation)
    print(result.model_dump_json(indent=2) if args.format == "json" else result.as_text(settings))
    return 0


def default_gold(root: Path) -> Path:
    """Inside the git directory, beside the verdict store: gold sets hold code and are never committed by accident."""
    return (root / git(root, "rev-parse", "--git-common-dir")).resolve() / "dry-lint" / "gold" / "replay.jsonl"


def index(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    from dry_lint.function_index import export_index

    snapshot = export_index(root, args.repository, settings)
    args.out.write_bytes(snapshot.encode())
    print(snapshot.artifact_name)
    return 0


def bench_replay(root: Path, settings: Settings, args: argparse.Namespace) -> int:
    if args.repo or args.comparer:
        raise ValueError("--replay replays one repository's checks; it takes neither --repo nor --comparer")
    if args.format not in ("text", "json"):
        raise ValueError("--replay prints text or json")
    if args.replay < 1:
        raise ValueError("--replay needs a number of commits, at least 1")
    if args.label is not None and args.label < 1:
        raise ValueError("--label needs a number of pairs, at least 1")
    specs = args.labeller or settings.labellers
    labellers = [labeller(spec) for spec in specs] if args.label else []
    progress = lambda line: print(line, file=sys.stderr)  # noqa: E731
    result = replay(
        root, settings, open_store(settings, root, args.store), args.replay, base_ref(root, args.ref), progress=progress
    )
    if labellers:
        gold_path = args.gold_out or default_gold(root)
        pairs = sample([f for _, f in result.findings()], args.label)
        answers = label(
            pairs, labellers, gold_path.with_suffix(".answers.jsonl"), args.label_budget_usd, progress=progress
        )
        judge = result.commits[0].report.judge if result.commits else None
        result.labels = summarise(
            pairs, answers, [who.name for who in labellers], settings, gold_path, len(result.commits), judge
        )
    print(result.model_dump_json(indent=1) if args.format == "json" else result.as_text())
    if args.report:
        args.report.write_text(result.model_dump_json(indent=1) + "\n")
    return 0


def progress_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--readme", type=Path, help="Maintain function and model debt in this README.")
    command.add_argument(
        "--repository", default=os.environ.get("GITHUB_REPOSITORY", ""), help="README badge OWNER/NAME."
    )
    command.add_argument("--branch", default="main", help="README badge's published branch (default: main).")
    command.add_argument("--repository-id", default="", help="Numeric GitHub repository id for the counter sign.")
    command.add_argument("--no-counter-card", action="store_true", help="Leave the counter sign out of the README.")


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=Path.cwd(), help="Any path inside the repository.")
    common.add_argument(
        "--models",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include model review (default on; --no-models opts out).",
    )
    common.add_argument(
        "--env-file", type=Path, help="Optional local dotenv file for judge credentials only; requires dry-lint[hooks]."
    )
    common.add_argument(
        "--repo",
        action="append",
        default=[],
        metavar="OWNER/NAME=PATH",
        help="Repeat for every checkout; compare across repositories. Include --root for checks.",
    )
    common.add_argument(
        "--repo-index",
        action="append",
        default=[],
        metavar="OWNER/NAME@COMMIT=PATH",
        help="A versioned peer function index; no checkout needed. Repeat for each peer.",
    )
    common.add_argument("--detector", help="Comparer plugin, overriding the settings: tfidf, dryer, or installed.")
    common.add_argument(
        "--judge", help="Judge plugin, overriding the settings: auto, jev, command, none, or installed."
    )
    common.add_argument("--judge-command", help="For the command judge: a command reading the candidate on stdin.")
    common.add_argument("--store", type=Path, help="A folder for the verdict store, overriding the settings.")
    common.add_argument(
        "--session", help="Stable local campaign name; defaults to the branch. Use a new name for a new task."
    )
    common.add_argument(
        "--discovery-state", type=Path, help="Persistent SQLite campaign ledger; defaults beside verdicts."
    )
    common.add_argument("--format", choices=FORMATS, default="text")
    common.add_argument("--output", type=Path, help="Also write the markdown report here, e.g. for a PR comment.")
    common.add_argument("--report", type=Path, help="Also write report.json here.")
    common.add_argument(
        "--fail-at",
        type=float,
        help="Judge score at or above which a duplicate fails the run, overriding fail_at in the settings.",
    )
    common.add_argument(
        "--preset",
        help="Judging preset (judges and their thresholds), overriding the settings; `dry-lint config` lists them.",
    )
    common.add_argument(
        "--budget-usd",
        type=float,
        help="Most judging spends on this pull request (all its runs), overriding budget.usd.",
    )
    common.add_argument("--warn-only", action="store_true", help="Report, but always exit 0.")
    common.add_argument("--require-complete", action="store_true", help="Fail on missing or incomplete judging.")
    common.add_argument("--baseline", type=Path, help="Accepted duplication baseline, relative to --root.")
    common.add_argument("--baseline-ref", help="Reject widening compared to the baseline at this trusted Git ref.")

    main = argparse.ArgumentParser(prog="dry-lint", description="Find code that re-implements what already exists.")
    main.add_argument("--version", action="version", version=f"dry-lint {__version__}")
    commands = main.add_subparsers(dest="command", required=True)
    exporting = commands.add_parser(
        "index", parents=[common], help="Export committed functions for reuse by peer repositories."
    )
    exporting.add_argument("--repository", required=True, help="Source OWNER/NAME.")
    exporting.add_argument("--out", type=Path, required=True, help="Write the versioned gzip JSON snapshot here.")

    def where(command: argparse.ArgumentParser, everything: bool = False) -> None:
        group = command.add_mutually_exclusive_group()
        group.add_argument("--base", help="Compare HEAD with its merge base with this ref (default: origin/HEAD).")
        group.add_argument("--staged", action="store_true", help="Check the staged changes.")
        if everything:
            group.add_argument("--all", action="store_true", help="Propose the whole repository's backlog instead.")

    where(
        commands.add_parser("check", parents=[common], help="Detect, judge and report the functions a change touched.")
    )
    sweep = commands.add_parser("scan", parents=[common], help="Judge look-alike pairs across the whole repository.")
    sweep.add_argument("--limit", type=int, default=50, help="Judge and show at most this many pairs, closest first.")
    sweep.add_argument("--refresh", action="store_true", help="Re-judge verdicts from older versions of the judge.")
    ratcheting = commands.add_parser(
        "sweep", parents=[common], help="Scan all functions and shrink the accepted backlog."
    )
    ratcheting.add_argument("--init", action="store_true", help="Initialize once from a fully judged repository sweep.")
    ratcheting.add_argument(
        "--update", action="store_true", help="Write the shrinking baseline and progress after review."
    )
    progress_options(ratcheting)
    progress_options(
        commands.add_parser(
            "progress", parents=[common], help="Refresh README debt from existing baselines; no judging."
        )
    )
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
    measuring = commands.add_parser(
        "bench", parents=[common], help="Measure the judge or the comparer on a gold set, or replay recent commits."
    )
    source = measuring.add_mutually_exclusive_group(required=True)
    source.add_argument("--gold", type=Path, help="gold.jsonl (docs/benchmark.md).")
    source.add_argument(
        "--replay",
        type=int,
        metavar="N",
        help="Check each of the last N commits of the default branch as `check` would have, with these "
        "settings: what would have failed, warned and cost.",
    )
    measuring.add_argument("--comparer", action="store_true", help="Measure the comparer's recall instead.")
    measuring.add_argument("--ref", help="With --replay: the branch to replay (default: origin/HEAD).")
    measuring.add_argument(
        "--label",
        type=int,
        metavar="K",
        help="With --replay: label about K of its pairs, sampled by judge score, into a gold set, "
        "and report what the judging caught, missed and blocked wrongly.",
    )
    measuring.add_argument(
        "--gold-out",
        type=Path,
        help="With --label: the gold file (default: inside the git directory). Answers are kept "
        "beside it, so a second run only asks about new pairs.",
    )
    measuring.add_argument(
        "--labeller",
        action="append",
        default=[],
        help="With --label: an OpenRouter model id, or command:<cli>; repeat for a panel "
        "(default: the `labellers` setting, three vendors' models).",
    )
    measuring.add_argument(
        "--label-budget-usd",
        type=float,
        default=5.0,
        help="With --label: most this run spends on labellers that report their cost.",
    )
    commands.add_parser("config", parents=[common], help="The judging setup this repository would run, and its cost.")
    trailing = commands.add_parser(
        "trailers",
        parents=[common],
        help="Write the hook observations before this commit into its message (prepare-commit-msg).",
    )
    trailing.add_argument("message", type=Path, help="The commit message file git passes the hook.")
    trailing.add_argument("source", nargs="*", help="The message's source and commit, as git passes them; unused.")
    commands.add_parser(
        "baseline-migrate",
        parents=[common],
        help="Migrate a reviewed judging policy without widening baseline allowances.",
    )
    reviewing = commands.add_parser(
        "feedback", parents=[common], help="Record a reviewed fix or exact-source dismissal."
    )
    reviewing.add_argument("action", choices=("fix", "dismiss", "accept"))
    reviewing.add_argument("pair", help="Pair key shown in the finding.")
    reviewing.add_argument(
        "--from", dest="source", type=Path, help="Report to review; defaults to the last discovery check."
    )
    reviewing.add_argument("--reason", required=True)
    reviewing.add_argument("--reviewer", required=True, help="Person or coding agent that reviewed the finding.")
    model_debt = commands.add_parser(
        "model-baseline",
        parents=[common],
        help="Initialize reviewed model debt, or ratchet source removals and dismissals.",
    )
    model_debt.add_argument("--init", action="store_true")
    model_debt.add_argument("--update", action="store_true")
    progress_options(model_debt)
    model_debt.add_argument(
        "--function-baseline", default=".dry-lint/baseline.json", help="Function debt for --readme."
    )
    model_debt.add_argument(
        "--staged", action="store_true", help="Audit the Git index, for retiring debt before committing a repair."
    )
    schema_check = commands.add_parser(
        "schema-check",
        parents=[common],
        help="Check explicitly configured Python schema naming and ownership contracts.",
    )
    schema_check.add_argument("--staged", action="store_true")
    schema_check.add_argument(
        "--all", action="store_true", help="Audit pre-existing violations as well as changed code."
    )
    schema_check.add_argument("--base")
    return main


COMMANDS = {
    "check": check,
    "scan": scan,
    "sweep": sweep,
    "detect": detect,
    "judge": judge,
    "report": report,
    "explain": explain,
    "config": config,
    "index": index,
    "feedback": feedback,
    "model-baseline": model_baseline,
    "progress": progress,
    "baseline-migrate": baseline_migrate,
    "schema-check": schema_policy.check,
    "trailers": trailers,
    "bench": bench,
}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = repository_root(args.root)
        if args.env_file and (root / args.env_file).is_file():  # optional: the hook names .env whether or not it exists
            from dotenv import dotenv_values

            credentials = dotenv_values(root / args.env_file, interpolate=False)
            for name in ("ANTHROPIC_API_KEY", "TYPESAFE_AI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
                if credentials.get(name) and not os.environ.get(name):
                    os.environ[name] = credentials[name]
        with ExitStack() as snapshots:
            original = root.resolve()
            # GitHub may refresh refs/pull/N/merge after the event's base was recorded. Read the same
            # immutable head that run_info publishes, including its config and source-bound feedback.
            pull = github_event().get("pull_request") or {}
            head = (pull.get("head") or {}).get("sha")
            if args.command in {"check", "detect"} and not args.staged and head:
                head = git(root, "rev-parse", "--verify", f"{head}^{{commit}}")
                if head != git(root, "rev-parse", "HEAD"):
                    root = snapshots.enter_context(worktree(root, head))
                    args.root = root
                    # Peer scans must still recognize this snapshot as their primary repository.
                    args.repo = [
                        f"{name}={root}" if separator and repository_root(Path(path)).resolve() == original else spec
                        for spec in args.repo
                        for name, separator, path in [spec.partition("=")]
                    ]
            settings = settings_for(root, args)
            if root != original and args.store is None and settings.store.use == "dir":
                folder = settings.store.options().get("path")
                args.store = original / folder if folder else default_store(original)
            return COMMANDS[args.command](root, settings, args)
    except (subprocess.SubprocessError, httpx.HTTPError, ValueError, OSError) as error:
        detail = getattr(error, "stderr", None) or error
        print(f"dry-lint: {str(detail).strip()}", file=sys.stderr)
        return 2
