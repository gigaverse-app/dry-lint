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

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

from dry_lint import sticky
from dry_lint.git import git

ARTIFACT = "dry-lint-candidates"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def flag(name: str) -> bool:
    return env(name).lower() in ("true", "1", "yes")


def load_event() -> dict:
    path = env("GITHUB_EVENT_PATH")
    return json.loads(Path(path).read_text()) if path and Path(path).exists() else {}


def is_fork(event: dict) -> bool:
    pull = event.get("pull_request") or {}
    head, base = (pull.get("head") or {}).get("repo") or {}, (pull.get("base") or {}).get("repo") or {}
    return bool(head) and head.get("full_name") != base.get("full_name")


def resolve_mode(requested: str, event_name: str, event: dict) -> str:
    if requested and requested != "auto":
        if requested not in ("single", "detect", "judge"):
            raise ValueError(f"Unknown mode: {requested} (use auto, single, detect or judge)")
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


def resolve_judge(requested: str, has_key: bool) -> str:
    requested = requested or "auto"
    return ("jev" if has_key else "none") if requested == "auto" else requested


def ensure_history(root: Path, base: str) -> None:
    """Comparing with a merge base needs history: deepen a shallow checkout, and fetch a base it does not have."""
    if git(root, "rev-parse", "--is-shallow-repository", check=False) == "true":
        git(root, "fetch", "--quiet", "--no-tags", "--unshallow", "origin", check=False)
    if base.strip("0") and not git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", check=False):
        git(root, "fetch", "--quiet", "--no-tags", "origin", base, check=False)


def dry_lint(*args: str, echo: bool = True) -> tuple[int, list[str]]:
    """Run the dry-lint CLI, echo its output (annotations take effect that way) and return the exit code and lines."""
    result = subprocess.run([sys.executable, "-m", "dry_lint", *args], capture_output=True, text=True)
    if echo:
        sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode, result.stdout.splitlines()


def count_findings(lines: list[str]) -> int:
    return sum(line.startswith(("::warning file=", "::error file=")) for line in lines)


def write_outputs(**outputs: object) -> None:
    path = env("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as handle:
            handle.writelines(f"{name.replace('_', '-')}={value}\n" for name, value in outputs.items())


def write_summary(comment: Path) -> None:
    path = env("GITHUB_STEP_SUMMARY")
    if path and comment.exists():
        with open(path, "a") as handle:
            handle.write(comment.read_text() + "\n")


def run_url() -> str:
    server, repository, run = env("GITHUB_SERVER_URL", "https://github.com"), env("GITHUB_REPOSITORY"), env("GITHUB_RUN_ID")
    return f"{server}/{repository}/actions/runs/{run}" if repository and run else ""


def comment(repository: str, number: int, body: Path, findings: int, expect_head: str,
            transport: httpx.BaseTransport | None = None) -> str:
    if not flag("INPUT_COMMENT") or not number or not body.exists():
        return "off"
    args = ["--body", str(body), "--repository", repository, "--pull-request", str(number),
            "--findings", str(findings), "--key", env("INPUT_STICKY_KEY"), "--run-url", run_url()]
    if expect_head:
        args += ["--expect-head", expect_head]
    sticky.main(args, transport=transport)
    return "posted"


def check_run(root: Path, repository: str, report: Path, transport: httpx.BaseTransport | None = None) -> str:
    """
    A workflow_run job does not show among a pull request's checks, so judge mode posts a check run on the pull
    request's head commit. It is neutral with findings and success without: it informs, never blocks.
    """
    token = env("GITHUB_TOKEN")
    if not flag("INPUT_CHECK_RUN") or not token or not report.exists():
        return "off"
    code, lines = dry_lint("report", "--root", str(root), "--from", str(report), "--format", "check-run", echo=False)
    try:
        body = json.loads("\n".join(lines))
    except json.JSONDecodeError:
        code = 2
    if code == 2:  # 1 only means the report has findings
        print("::warning title=dry-lint::Could not render the check run.")
        return "failed"
    github = sticky.GitHub(token, env("GITHUB_API_URL", "https://api.github.com"), transport)
    try:
        github.check_run(repository, body)
    except httpx.HTTPStatusError as error:
        if error.response.status_code not in (403, 404):
            raise
        print("::warning title=dry-lint::No check run: give the judge job `checks: write`.")
        return "forbidden"
    return "posted"


def plan() -> int:
    event_name, event = env("GITHUB_EVENT_NAME"), load_event()
    write_outputs(mode=resolve_mode(env("INPUT_MODE", "auto"), event_name, event),
                  workflow_run_id=(event.get("workflow_run") or {}).get("id", ""))
    return 0


def run(transport: httpx.BaseTransport | None = None) -> int:
    event_name, event = env("GITHUB_EVENT_NAME"), load_event()
    mode = resolve_mode(env("INPUT_MODE", "auto"), event_name, event)
    work = Path(env("RUNNER_TEMP", "/tmp")) / "dry-lint"
    work.mkdir(parents=True, exist_ok=True)
    root = Path(env("INPUT_WORKING_DIRECTORY", ".") or ".").resolve()
    store, report, body = work / "verdicts", work / "report.json", work / "comment.md"
    judge = resolve_judge(env("INPUT_JUDGE"), bool(env("TYPESAFE_AI_API_KEY")))
    # Unjudged look-alikes go to the log only: as annotations they would be noise on every pull request.
    judging = ["--judge", judge, "--store", str(store), "--report", str(report), "--output", str(body),
               "--format", "text" if judge == "none" else "github", "--warn-only"]
    if env("INPUT_JUDGE_COMMAND"):
        judging += ["--judge-command", env("INPUT_JUDGE_COMMAND")]

    if mode == "detect":
        base = resolve_base(env("INPUT_BASE"), event_name, event)
        ensure_history(root, base)
        code, _ = dry_lint("detect", "--root", str(root), "--out", str(work / "candidates.json"),
                           *(["--base", base] if base else []))
        write_outputs(mode=mode, exit_code=code, findings=0)
        print(f"::notice title=dry-lint::Candidates saved as the {ARTIFACT} artifact for the judge workflow.")
        return 2 if code == 2 else 0

    if mode == "judge":
        candidates = work / "in" / "candidates.json"
        if not candidates.exists():
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
        if code != 2 and judge != "none":
            check_run(root, repository, report, transport)
    else:
        base = resolve_base(env("INPUT_BASE"), event_name, event)
        ensure_history(root, base)
        code, lines = dry_lint("check", "--root", str(root), *(["--base", base] if base else []), *judging)
        pull = event.get("pull_request") or {}
        number, repository, head = pull.get("number") or 0, env("GITHUB_REPOSITORY"), ""

    findings = count_findings(lines)
    write_summary(body)
    if code == 2:
        write_outputs(mode=mode, exit_code=2, findings=findings)
        return 2
    if judge == "none":
        print("::notice title=dry-lint::Look-alikes are listed unjudged in the log. Set typesafe-api-key (or "
              "judge-command) to judge them; until then dry-lint does not comment or fail.")
        write_outputs(mode=mode, exit_code=0, findings=0)
        return 0
    comment(repository, number, body, findings, head, transport)
    failed = findings > 0 and flag("INPUT_FAIL_ON_FINDINGS")
    write_outputs(mode=mode, exit_code=1 if findings else 0, findings=findings)
    return 1 if failed else 0


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    command = (argv if argv is not None else sys.argv[1:])[:1]
    try:
        return plan() if command == ["plan"] else run(transport)
    except ValueError as error:
        print(f"::error title=dry-lint::{error}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
