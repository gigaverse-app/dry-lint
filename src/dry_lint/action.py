"""
The GitHub Action's logic, as code with tests instead of shell inside action.yml.

    python -m dry_lint.action plan   # decide the mode; action.yml uses it to pick its download/cache/upload steps
    python -m dry_lint.action run    # run dry-lint in that mode, comment, and write outputs and the job summary

Modes:

- **single**: detect, judge and comment in one job. For pull requests from the same repository, which get the
  repository's secrets and a token that can comment.
- **detect**: a pull request from a fork gets no secrets and a read-only token. Propose candidates only, and
  hand them to the judge job as the `dry-lint-candidates` artifact. No judge runs and nothing can fail.
- **judge**: a `workflow_run` job, which runs from the default branch with secrets. Judge the candidates of the
  run that triggered it, and comment on its pull request.
- **auto** (the default): judge on `workflow_run`, detect on a fork's pull request, single otherwise.

The candidates in judge mode come from code nobody has reviewed yet, so the judge job never runs it, and it only
comments when the artifact's commit is the triggering run's head commit and still the pull request's head.
Inputs arrive as INPUT_* environment variables set by action.yml.
"""

import base64
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

from dry_lint import goldens, sticky
from dry_lint.detector import base_ref, changed_functions, given
from dry_lint.function_index import export_index
from dry_lint.git import git
from dry_lint.github import github_event
from dry_lint.index_github import IndexClient
from dry_lint.ledger import COUNTER, PullLedger, RepositoryLedger, Tally, counter_key
from dry_lint.report import NOTE_SLOT, Report
from dry_lint.settings import Settings

ARTIFACT = "dry-lint-candidates"
OVERRIDE_LABEL = "dry-lint: override"
HISTORY_DEPTHS = (2, 32, 128, 512, 2048)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def flag(name: str) -> bool:
    return env(name).lower() in ("true", "1", "yes")


def is_fork(event: dict) -> bool:
    pull = event.get("pull_request") or {}
    head, base = (pull.get("head") or {}).get("repo") or {}, (pull.get("base") or {}).get("repo") or {}
    return bool(head) and head.get("full_name") != base.get("full_name")


def resolve_mode(requested: str, event_name: str, event: dict) -> str:
    if requested and requested != "auto":
        if requested not in ("single", "detect", "judge", "sweep", "index", "fetch-indexes"):
            raise ValueError(
                f"Unknown mode: {requested} (use auto, single, detect, judge, sweep, index or fetch-indexes)"
            )
        return requested
    if event_name == "workflow_run":
        return "judge"
    return "detect" if is_fork(event) else "single"


def resolve_base(explicit: str, event_name: str, event: dict) -> str:
    """
    What to compare with: the input, the PR's base commit, or the previous push. A branch's first push reports
    an all-zero commit; dry-lint itself turns that, and "", into the default branch.
    """
    if explicit:
        return explicit
    if event_name.startswith("pull_request"):
        return ((event.get("pull_request") or {}).get("base") or {}).get("sha", "")
    return event.get("before", "") if event_name == "push" else ""


JUDGE_KEYS = ("TYPESAFE_AI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")


def resolve_judge(requested: str, has_key: bool) -> str:
    """
    "auto" while some judge's key is present: dry-lint then picks its judging preset itself (jev+opus, jev, ...).
    "none" without any key. An explicit choice passes through, and makes the preset "custom".
    """
    requested = requested or "auto"
    return ("auto" if has_key else "none") if requested == "auto" else requested


def judging_options() -> list[str]:
    """The preset and budget inputs, passed through only when set (older dry-lint versions lack the flags)."""
    options = []
    for name, flag_ in (("INPUT_PRESET", "--preset"), ("INPUT_BUDGET_USD", "--budget-usd")):
        if env(name):
            options += [flag_, env(name)]
    if flag("INPUT_REQUIRE_COMPLETE"):
        options.append("--require-complete")
    if env("INPUT_BASELINE"):
        options += ["--baseline", env("INPUT_BASELINE")]
    return options


def fetch_history(root: Path, *refs: str, depth: int) -> None:
    environment = dict(os.environ)
    token = env("GITHUB_TOKEN")
    if token:
        count = int(environment.get("GIT_CONFIG_COUNT", "0"))
        server = env("GITHUB_SERVER_URL", "https://github.com")
        environment.update(
            {
                "GIT_CONFIG_COUNT": str(count + 2),
                f"GIT_CONFIG_KEY_{count}": f"http.{server}/.extraheader",
                f"GIT_CONFIG_VALUE_{count}": "",
                f"GIT_CONFIG_KEY_{count + 1}": f"http.{server}/.extraheader",
                f"GIT_CONFIG_VALUE_{count + 1}": "AUTHORIZATION: basic "
                + base64.b64encode(f"x-access-token:{token}".encode()).decode(),
            }
        )
    git(root, "fetch", "--quiet", "--no-tags", f"--depth={depth}", "origin", *refs, env=environment)


def ensure_history(root: Path, base: str) -> None:
    """Fetch only the compared refs, bounded to 2048 ancestors; never fetch every branch or unshallow."""
    shallow = git(root, "rev-parse", "--is-shallow-repository", check=False) == "true"
    if not shallow:
        if given(base) and not git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", check=False):
            git(root, "fetch", "--quiet", "--no-tags", "origin", base, check=False)
        return
    base = base_ref(root, base)
    head = git(root, "rev-parse", "HEAD")
    remote_base = base.removeprefix("refs/remotes/origin/").removeprefix("origin/")
    if remote_base != base:
        remote_base = f"{remote_base}:refs/remotes/origin/{remote_base}"
    for depth in HISTORY_DEPTHS:
        if git(root, "merge-base", base, "HEAD", check=False):
            return
        fetch_history(root, remote_base, head, depth=depth)
    if not git(root, "merge-base", base, "HEAD", check=False):
        raise ValueError(
            "No merge base within 2048 commits of the compared refs; rebase the branch or provide history."
        )


def dry_lint(*args: str, echo: bool = True) -> tuple[int, list[str]]:
    """Run the dry-lint CLI, echo its output (annotations take effect that way) and return the exit code and lines."""
    result = subprocess.run([sys.executable, "-m", "dry_lint", *args], capture_output=True, text=True)
    if echo:
        sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode not in (0, 1) or (args[0] == "detect" and result.returncode != 0):
        if not echo:
            sys.stdout.write(result.stdout)
        action_error(f"dry-lint {args[0]} failed with exit code {result.returncode}; see the command output above.")
        return 2, result.stdout.splitlines()
    return result.returncode, result.stdout.splitlines()


def count_findings(lines: list[str]) -> tuple[int, int]:
    """All findings, and the blocking ones (dry-lint marks a finding at or above `fail_at` as an error)."""
    return sum(line.startswith(("::warning file=", "::error file=")) for line in lines), sum(
        line.startswith("::error file=") for line in lines
    )


def judged(report: Path) -> bool:
    """Whether a judge actually ran, by report.json; the repository's settings can turn judging off."""
    return bool(json.loads(report.read_text()).get("judge"))


def fail_at() -> list[str]:
    """The fail-at input, passed through to dry-lint; empty means the repository's `fail_at` setting."""
    return ["--fail-at", env("INPUT_FAIL_AT")] if env("INPUT_FAIL_AT") else []


def override_label() -> str:
    return env("INPUT_OVERRIDE_LABEL") or OVERRIDE_LABEL


def labels_of(pull: dict) -> set[str]:
    return {label.get("name", "") for label in pull.get("labels") or []}


def status_note(blocking: int, overridden: bool, baselined: bool = False) -> str:
    """Lead the comment with the effective check status, including advisory mode and overrides."""
    if not blocking:
        return ""
    if baselined:
        return (
            f"> [!CAUTION]\n> **Blocking:** {blocking} new or changed duplicate(s) exceed the baseline. "
            "Refactor them or document a deliberate distinct concept in code; an override label cannot widen the ratchet."
        )
    if overridden:
        return (
            f"> [!NOTE]\n> **Overridden:** the `{override_label()}` label is set, so the {blocking} blocking "
            "finding(s) do not fail this pull request."
        )
    if flag("INPUT_WARN_ONLY"):
        return "> [!NOTE]\n> **Advisory mode:** `warn-only` is enabled, so this check does not fail on these findings."
    return (
        f"> [!CAUTION]\n> **Blocking:** {blocking} finding(s) require review or reach `fail_at`, so this check fails. A false "
        f"positive? Use the scoped decisions below, or add the `{override_label()}` label to this pull request."
    )


def write_outputs(**outputs: object) -> None:
    path = env("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as handle:
            handle.writelines(f"{name.replace('_', '-')}={value}\n" for name, value in outputs.items())


def write_summary(comment: Path, note: str = "") -> None:
    path = env("GITHUB_STEP_SUMMARY")
    if path and comment.exists():
        with open(path, "a") as handle:
            text = comment.read_text()
            handle.write((note + "\n\n" if note else "") + text.replace(NOTE_SLOT, "") + "\n")


def action_error(message: str) -> None:
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error title=dry-lint::{escaped}")
    write_outputs(exit_code=2, models_checked="false")
    if path := env("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as handle:
            handle.write("\n### dry-lint failed\n\n" + message + "\n")


def run_url() -> str:
    server, repository, run = (
        env("GITHUB_SERVER_URL", "https://github.com"),
        env("GITHUB_REPOSITORY"),
        env("GITHUB_RUN_ID"),
    )
    return f"{server}/{repository}/actions/runs/{run}" if repository and run else ""


def comment(
    repository: str,
    number: int,
    body: Path,
    findings: int,
    expect_head: str,
    transport: httpx.BaseTransport | None = None,
    note: str = "",
) -> str:
    if not flag("INPUT_COMMENT") or not number or not body.exists():
        return "off"
    args = [
        "--body",
        str(body),
        "--repository",
        repository,
        "--pull-request",
        str(number),
        "--findings",
        str(findings),
        "--key",
        env("INPUT_STICKY_KEY"),
        "--run-url",
        run_url(),
        "--note",
        note,
    ]
    if expect_head:
        args += ["--expect-head", expect_head]
    if (report := body.parent / "report.json").exists():
        args += ["--report", str(report)]
    if ledger_path().exists():
        args += ["--repository-ledger", str(ledger_path())]
    if env("INPUT_COMMENT_ON_CLEAN", "true").lower() in ("false", "0", "no"):
        args.append("--skip-clean")
    sticky.main(args, transport=transport)
    return "posted"


def check_run(
    root: Path, repository: str, report: Path, transport: httpx.BaseTransport | None = None, blocked: bool = False
) -> str:
    """
    A workflow_run job does not show among a pull request's checks, so judge mode posts a check run on the pull
    request's head commit: a failure when a finding blocks, otherwise neutral with findings and success without.
    """
    token = env("GITHUB_TOKEN")
    if not flag("INPUT_CHECK_RUN") or not token or not report.exists():
        return "off"
    code, lines = dry_lint(
        "report",
        "--root",
        str(root),
        "--from",
        str(report),
        "--format",
        "check-run",
        *fail_at(),
        *([] if blocked else ["--warn-only"]),
        echo=False,
    )
    try:
        body = json.loads("\n".join(lines))
    except json.JSONDecodeError:
        code = 2
    if code == 2:  # 1 only means the report has findings
        raise ValueError("Could not render the check run.")
    if blocked:
        body["conclusion"] = "failure"
    github = sticky.GitHub(token, env("GITHUB_API_URL", "https://api.github.com"), transport)
    try:
        github.check_run(repository, body)
    except httpx.HTTPStatusError as error:
        if error.response.status_code not in (403, 404):
            raise
        print("::warning title=dry-lint::No check run: give the judge job `checks: write`.")
        return "forbidden"
    return "posted"


def ledger_path() -> Path:
    """The repository's ledger, beside the verdicts: in the cache every pull request restores from."""
    return workdir() / "verdicts" / "ledger" / "repository.json"


def default_branch(event_name: str, event: dict) -> str:
    """The default branch, when this run is a push to it; otherwise ""."""
    default = (event.get("repository") or {}).get("default_branch", "")
    return default if event_name == "push" and default and event.get("ref") == f"refs/heads/{default}" else ""


def fold(repository: str, branch: str, head: str, report: Path, transport: httpx.BaseTransport | None = None) -> str:
    """
    Add this default-branch run, and the final ledger of each pull request merged since the repository's ledger
    began, to that ledger. Each run looks back over the latest merged pull requests, not only this push's, so a
    run that was cancelled or failed is caught up by the next. The pull request this push merged counts even when
    the ledger is new.
    """
    path = ledger_path()
    ledger = RepositoryLedger.load(path.read_text() if path.exists() else "", repository)
    if report.exists():
        ledger.add_run(Tally.of(Report.model_validate_json(report.read_text())), sticky.run_id())
    outcome = "folded"
    shared = 0
    repository_id = env("GITHUB_REPOSITORY_ID")
    key = counter_key(repository_id) if sharing() and repository_id else ""
    token = env("GITHUB_TOKEN")
    if token:
        github = sticky.GitHub(token, env("GITHUB_API_URL", "https://api.github.com"), transport)
        since = datetime.fromisoformat(ledger.since)
        try:
            for pull in github.merged_pulls(repository, branch):
                number = pull["number"]
                if (
                    number in ledger.pulls
                    or number in ledger.unaccounted
                    or not (pull.get("merge_commit_sha") == head or datetime.fromisoformat(pull["merged_at"]) >= since)
                ):
                    continue
                found = [
                    pulled
                    for c in sticky.ours(github.comments(repository, number))
                    if (pulled := PullLedger.read(c.get("body", ""))) is not None
                ]
                if found:
                    final = max(found, key=lambda pulled: pulled.tally.runs)
                    ledger.add_pull(number, final, key)
                    if sharing_goldens():
                        shared += goldens.append(
                            report.parent / "goldens.jsonl", goldens.settled(repository, number, final)
                        )
                else:
                    ledger.unaccounted.append(number)
        except httpx.HTTPError as error:
            print(f"::warning title=dry-lint::Could not read merged pull requests for the ledger: {error}")
            outcome = "partial"
    share(ledger, transport)
    if key:
        print(
            f"dry-lint: this repository's counter key is {key}; its sign is "
            f"{env('DRY_LINT_COUNTER', COUNTER)}/v1/sign.svg?key={key}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger.model_dump_json(indent=2) + "\n")
    if shared:
        print(f"dry-lint: {shared} settled pair(s) kept as the {goldens.ARTIFACT} artifact (share-goldens).")
        write_outputs(goldens="true")
    return outcome


def sharing() -> bool:
    return env("INPUT_SHARE_TOTALS", "true").lower() not in ("false", "0", "no")


def sharing_goldens() -> bool:
    """Opt in, never opt out: settled pairs leave the run only when the repository says so."""
    return env("INPUT_SHARE_GOLDENS", "false").lower() in ("true", "1", "yes")


def share(ledger: RepositoryLedger, transport: httpx.BaseTransport | None = None) -> int:
    """
    Send the global counter what it has not confirmed: one merged pull request's counts each, under the
    repository's counter key (ledger.counter_key). It counts each pull request once, so a resend is harmless, and what fails stays in
    the outbox for the next push. Never fails the run; `share-totals: "false"` sends nothing and empties it.
    """
    if not sharing():
        ledger.outbox = []
        return 0
    sent = []
    with httpx.Client(timeout=5, transport=transport) as client:
        for contribution in ledger.outbox:
            try:
                client.post(f"{env('DRY_LINT_COUNTER', COUNTER)}/v1/pulls", json=contribution).raise_for_status()
            except httpx.HTTPError as error:
                print(f"::notice title=dry-lint::The global counter is unavailable; will retry: {error}")
                break
            sent.append(contribution)
    ledger.outbox = [contribution for contribution in ledger.outbox if contribution not in sent]
    return len(sent)


def pull_labels(repository: str, number: int, transport: httpx.BaseTransport | None = None) -> set[str]:
    """In judge mode the event is the workflow run, not the pull request: ask the API for the labels."""
    token = env("GITHUB_TOKEN")
    if not token or not number:
        return set()
    github = sticky.GitHub(token, env("GITHUB_API_URL", "https://api.github.com"), transport)
    try:
        return labels_of(github.pull(repository, number))
    except httpx.HTTPStatusError:
        return set()


def plan() -> int:
    event_name, event = env("GITHUB_EVENT_NAME"), github_event()
    write_outputs(
        mode=resolve_mode(env("INPUT_MODE", "auto"), event_name, event),
        workflow_run_id=(event.get("workflow_run") or {}).get("id", ""),
    )
    return 0


def workdir() -> Path:
    return Path(env("RUNNER_TEMP", "/tmp")) / "dry-lint"


def index_specs() -> list[tuple[str, str]]:
    """The repository-indexes input as (OWNER/NAME, REF) pairs."""
    specs = []
    for spec in env("INPUT_REPOSITORY_INDEXES").splitlines():
        if not spec.strip():
            continue
        repository, separator, ref = spec.strip().partition("@")
        if not separator:
            raise ValueError("repository-indexes expects OWNER/NAME@REF, one per line")
        specs.append((repository, ref))
    return specs


def peer_indexes(root: Path, work: Path, transport: httpx.BaseTransport | None = None) -> tuple[list[str], str]:
    arguments, receipts = [], []
    client = IndexClient(
        env("INPUT_INDEX_TOKEN") or env("GITHUB_TOKEN"), env("GITHUB_API_URL", "https://api.github.com"), transport
    )
    try:
        for repository, ref in index_specs():
            fetched = client.fetch(repository, ref, Settings.load(root))
            index = fetched.index
            path = work / f"{repository.replace('/', '--')}-{index.commit}.json.gz"
            path.write_bytes(index.encode())
            arguments.extend(["--repo-index", f"{repository}@{index.commit}={path}"])
            receipts.append(fetched.receipt())
    finally:
        client.close()
    manifest = work / "index-arguments.json"
    manifest.write_text(json.dumps(arguments))
    write_outputs(index_arguments=str(manifest))
    receipt = (
        (
            "\n\n### Peer function indexes\n\n| Repository | Source commit | Functions | Source | Bytes downloaded |\n"
            "| --- | --- | ---: | --- | ---: |\n" + "\n".join(receipts) + "\n"
        )
        if receipts
        else ""
    )
    return arguments, receipt


UNTOUCHED = (
    "\n\n### Peer function indexes\n\nNot downloaded: this change touches no function in scope, so there "
    "is nothing to compare with peer repositories.\n"
)


def changes_functions(root: Path, base: str) -> bool:
    """Whether the change touches any function in scope: without one, peer indexes have nothing to be compared with."""
    ensure_history(root, base)
    return bool(changed_functions(root, Settings.load(root), base or None, repository=env("GITHUB_REPOSITORY")))


def run(transport: httpx.BaseTransport | None = None) -> int:
    event_name, event = env("GITHUB_EVENT_NAME"), github_event()
    mode = resolve_mode(env("INPUT_MODE", "auto"), event_name, event)
    work = workdir()
    work.mkdir(parents=True, exist_ok=True)
    root = Path(env("INPUT_WORKING_DIRECTORY", ".") or ".").resolve()
    models = Settings.load(root).models
    model_arguments = [
        "--models"
        if env("INPUT_MODELS", "true").lower() in ("true", "1", "yes") and models.enabled and models.sticky
        else "--no-models"
    ]
    if mode == "index":
        snapshot = export_index(root, env("GITHUB_REPOSITORY"), Settings.load(root))
        path = work / "functions.json.gz"
        path.write_bytes(snapshot.encode())
        write_outputs(mode=mode, exit_code=0, index_name=snapshot.artifact_name, index_path=str(path))
        print(
            f"Published index: {snapshot.repository}@{snapshot.commit}, {len(snapshot.functions)} functions, {path.stat().st_size} bytes"
        )
        return 0
    index_arguments, receipt = [], ""
    if env("INPUT_REPOSITORY_INDEXES"):
        if mode in {"detect", "judge"}:
            raise ValueError("Peer indexes are consumed only in trusted single or fetch-indexes mode")
        index_specs()  # a malformed input fails even when there is nothing to compare
        if mode == "single" and not changes_functions(root, resolve_base(env("INPUT_BASE"), event_name, event)):
            receipt = UNTOUCHED
        else:
            index_arguments, receipt = peer_indexes(root, work, transport)
    if mode == "fetch-indexes":
        (work / "indexes.md").write_text(receipt)
        write_summary(work / "indexes.md")
        write_outputs(mode=mode, exit_code=0)
        return 0
    store, report, body = work / "verdicts", work / "report.json", work / "comment.md"
    report.unlink(missing_ok=True)
    body.unlink(missing_ok=True)
    judge = resolve_judge(env("INPUT_JUDGE"), any(env(key) for key in JUDGE_KEYS))
    # dry-lint logs as text; annotations are rendered from report.json afterwards, and only when a judge ran:
    # unjudged look-alikes on every pull request would be noise. dry-lint exits 1 when a finding blocks (at or
    # above fail_at); the action decides what that means. "auto" leaves the judging preset to dry-lint.
    judging = [
        *([] if judge == "auto" else ["--judge", judge]),
        "--store",
        str(store),
        "--report",
        str(report),
        "--output",
        str(body),
        *fail_at(),
        *judging_options(),
        *model_arguments,
    ]
    judging += ["--format", "text", *(["--warn-only"] if judge == "none" else [])]
    if flag("INPUT_WARN_ONLY"):
        judging.append("--warn-only")
    if env("INPUT_JUDGE_COMMAND"):
        judging += ["--judge-command", env("INPUT_JUDGE_COMMAND")]
    repositories = [
        argument
        for line in env("INPUT_REPOSITORIES").splitlines()
        if line.strip()
        for argument in ("--repo", line.strip())
    ]
    if index_arguments and not repositories:
        repositories = ["--repo", f"{env('GITHUB_REPOSITORY')}={root}"]
    repositories.extend(index_arguments)

    if mode == "sweep":
        code, _ = dry_lint(
            "sweep",
            "--root",
            str(root),
            "--repository",
            env("GITHUB_REPOSITORY"),
            "--branch",
            (event.get("repository") or {}).get("default_branch", "main"),
            "--readme",
            env("INPUT_SWEEP_README", "README.md"),
            *repositories,
            *judging,
        )
        write_summary(body)
        write_outputs(mode=mode, exit_code=code)
        return code

    if mode == "detect":
        base = resolve_base(env("INPUT_BASE"), event_name, event)
        ensure_history(root, base)
        code, _ = dry_lint(
            "detect",
            "--root",
            str(root),
            "--out",
            str(work / "candidates.json"),
            *(["--base", base] if base else []),
            *repositories,
            *(["--require-complete"] if flag("INPUT_REQUIRE_COMPLETE") else []),
            *model_arguments,
        )
        write_outputs(mode=mode, exit_code=code, findings=0)
        if code != 0:
            return 2
        print(f"::notice title=dry-lint::Candidates saved as the {ARTIFACT} artifact for the judge workflow.")
        return 0

    if mode == "judge":
        candidates = work / "in" / "candidates.json"
        if not candidates.exists():
            if flag("INPUT_REQUIRE_COMPLETE"):
                raise ValueError("Required judging has no candidate artifact; rerun the detection workflow")
            print("::notice title=dry-lint::The triggering run left no candidates; nothing to judge.")
            write_outputs(mode=mode, exit_code=0, findings=0)
            return 0
        code, lines = dry_lint("judge", "--root", str(root), "--candidates", str(candidates), *judging)
        head = (event.get("workflow_run") or {}).get("head_sha", "")
        run_info = json.loads(report.read_text()).get("run", {}) if report.exists() else {}
        if code != 2 and run_info.get("head") != head:
            print("::error title=dry-lint::The candidates are not from the triggering run's head commit; not posting.")
            write_outputs(mode=mode, exit_code=2, findings=0)
            return 2
        number, repository = run_info.get("pull_request") or 0, env("GITHUB_REPOSITORY")
        labels = pull_labels(repository, number, transport) if code == 1 else set()
    else:
        base = resolve_base(env("INPUT_BASE"), event_name, event)
        ensure_history(root, base)
        if env("INPUT_BASELINE") and base:
            judging += ["--baseline-ref", base]
        code, lines = dry_lint(
            "check", "--root", str(root), *(["--base", base] if base else []), *repositories, *judging
        )
        pull = event.get("pull_request") or {}
        number, repository, head = (
            pull.get("number") or 0,
            env("GITHUB_REPOSITORY"),
            (pull.get("head") or {}).get("sha", ""),
        )
        labels = labels_of(pull)

    if code != 2 and judge != "none":
        if judged(report):
            rendered, lines = dry_lint(
                "report", "--root", str(root), "--from", str(report), "--format", "github", *fail_at(), echo=False
            )
            if rendered == 2:
                code = 2
        else:  # the repository's settings turn judging off (preset or judge "none") although keys are present
            judge, code = "none", 0
    findings, blocking = count_findings(lines)
    write_outputs(
        models_checked=str(
            code != 2 and report.exists() and json.loads(report.read_text()).get("model_judging") is not None
        ).lower()
    )
    if receipt and body.exists():
        body.write_text(body.read_text() + receipt)
    if code == 2:
        write_summary(body)
        if mode == "judge":
            check_run(root, repository, report, transport, blocked=True)
        write_outputs(mode=mode, exit_code=2, findings=findings, blocking=blocking, overridden="false")
        return 2
    if judge == "none":
        write_summary(body)
        print(
            "::notice title=dry-lint::Look-alikes are listed unjudged in the log. Set typesafe-api-key (or "
            "judge-command) to judge them; until then dry-lint does not comment or fail."
        )
        write_outputs(mode=mode, exit_code=0, findings=0, blocking=0, overridden="false")
        return 0
    blocking = blocking if code == 1 or flag("INPUT_WARN_ONLY") else 0
    baselined = bool(env("INPUT_BASELINE"))
    overridden = bool(blocking) and not baselined and override_label() in labels
    blocked = code == 1 and not overridden and not flag("INPUT_WARN_ONLY")
    for line in lines:
        print(line.replace("::error file=", "::warning file=", 1) if not blocked else line)
    if overridden:
        rendered, _ = dry_lint(
            "report",
            "--root",
            str(root),
            "--from",
            str(report),
            "--format",
            "markdown",
            "--output",
            str(body),
            "--warn-only",
            *fail_at(),
            echo=False,
        )
        if rendered == 2:
            return 2
        if receipt and body.exists():
            body.write_text(body.read_text() + receipt)
    note = status_note(blocking, overridden, baselined)
    write_summary(body, note)
    if overridden:
        print(f"::notice title=dry-lint::{blocking} blocking finding(s) overridden by the `{override_label()}` label.")
    if mode == "judge":
        check_run(root, repository, report, transport, blocked)
    comment(repository, number, body, findings, head, transport, note)
    if branch := default_branch(event_name, event):
        fold(repository, branch, event.get("after", ""), report, transport)
    write_outputs(mode=mode, exit_code=code, findings=findings, blocking=blocking, overridden=str(overridden).lower())
    return 1 if blocked else 0


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    command = (argv if argv is not None else sys.argv[1:])[:1]
    try:
        if command == ["plan"]:
            return plan()
        return run(transport)
    except (ValueError, OSError, httpx.HTTPError, subprocess.CalledProcessError) as error:
        action_error(str(error))
        return 2
    finally:
        # action.yml saves the verdict cache only when there is something to save (hashFiles cannot see RUNNER_TEMP).
        if command != ["plan"]:
            store = workdir() / "verdicts"
            write_outputs(stored=str(store.is_dir() and any(store.iterdir())).lower())


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
