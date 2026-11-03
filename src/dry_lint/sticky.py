"""
The sticky pull request comment: one comment per pull request, edited in place on every run.

    python -m dry_lint.sticky --body comment.md --repository owner/repo --pull-request 12 --findings 2 \
        [--report report.json] [--repository-ledger ledger.json] [--key api] [--expect-head SHA] [--run-url URL] \
        [--skip-clean]

- **Found by its marker.** The comment's first line is `<!-- dry-lint -->`, or `<!-- dry-lint:KEY -->` when one
  repository labels its report. All legacy keys are reconciled into one comment. Serialize publishers per PR.
  GitHub has no atomic comment upsert; independent writers must not race.
- **Clean is news too.** A clean pull request gets a clean report with what was checked, unless `--skip-clean`.
  A comment from an earlier run with findings is updated to say they are resolved, so it never goes stale.
- **Never about the wrong commit.** With `--expect-head`, nothing is posted once the pull request has moved on
  to a newer commit: that commit's own run will post.
- **Keeps a running account.** With `--report`, the comment carries the pull request's ledger (ledger.py): what
  every push cost, and every duplicate it caught and kept out of the codebase. The previous comment is the only
  state, so a run counts once however often it posts.
- **Never fails the build for lack of permission.** A pull request from a fork gets a read-only token: the
  comment is skipped with a warning, and the annotations and job summary still carry the findings.

The token comes from GITHUB_TOKEN, and the API root from GITHUB_API_URL (GitHub Enterprise Server works).
"""

import argparse
import os
import re
import sys
from pathlib import Path

import httpx

from dry_lint.ledger import PullLedger, RepositoryLedger
from dry_lint.ledger import render as ledger_render
from dry_lint.report import CLEAN, NOTE_SLOT, Report

MARKER = "<!-- dry-lint -->"
ASSETS = "https://raw.githubusercontent.com/gigaverse-app/dry-lint/main/docs/assets"
PAGE = 100


def marker(key: str = "") -> str:
    return f"<!-- dry-lint:{key} -->" if key else MARKER


def banner_available(transport: httpx.BaseTransport | None = None) -> bool:
    """The banner only renders when GitHub can fetch it anonymously, i.e. once dry-lint's repository is public."""
    try:
        with httpx.Client(timeout=5, transport=transport, follow_redirects=True) as client:
            return client.head(f"{ASSETS}/sticky-banner-light.svg").status_code == 200
    except httpx.HTTPError:
        return False


def compose(markdown: str, key: str = "", banner: bool = False, run_url: str = "", head: str = "", note: str = "",
            ledger: str = "") -> str:
    """The comment body: marker, banner, cleanup progress, current findings, and source."""
    lines = markdown.strip().splitlines()
    if lines and re.fullmatch(r"<!-- dry-lint(?::[^\n]*?)? -->", lines[0].strip()):
        lines = lines[1:]
    parts = [marker(key)]
    if banner:
        parts.append(
            "<picture>\n"
            f'  <source media="(prefers-color-scheme: dark)" srcset="{ASSETS}/sticky-banner-dark.svg">\n'
            f'  <img alt="dry-lint" src="{ASSETS}/sticky-banner-light.svg" width="640">\n'
            "</picture>\n"
        )
    report = "\n".join(lines).strip()
    if NOTE_SLOT in report:
        report = report.replace(NOTE_SLOT, note).replace("\n\n\n\n", "\n\n")
    elif note:
        report = f"{note}\n\n{report}"
    if ledger:
        parts.append(f"\n{ledger}\n\n---\n")
    parts.append(report)
    source = ["[dry-lint](https://github.com/gigaverse-app/dry-lint)", f"commit {head[:7]}" if head else "",
              f"[run]({run_url})" if run_url else ""]
    if head or run_url:
        parts.append(f"\n<sub>{' · '.join(s for s in source if s)}</sub>")
    return "\n".join(parts) + "\n"


RESOLVED = "> [!TIP]\n> **Resolved:** the duplicated concepts reported earlier on this pull request are gone."


class GitHub:
    def __init__(self, token: str, api: str = "https://api.github.com", transport: httpx.BaseTransport | None = None):
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        self.client = httpx.Client(base_url=api, headers=headers, timeout=30, transport=transport)

    def pull(self, repository: str, number: int) -> dict:
        response = self.client.get(f"/repos/{repository}/pulls/{number}")
        response.raise_for_status()
        return response.json()

    def head_of(self, repository: str, number: int) -> str:
        return self.pull(repository, number)["head"]["sha"]

    def comments(self, repository: str, number: int) -> list[dict]:
        found, page = [], 1
        while True:
            response = self.client.get(f"/repos/{repository}/issues/{number}/comments",
                                       params={"per_page": PAGE, "page": page})
            response.raise_for_status()
            batch = response.json()
            found += batch
            if len(batch) < PAGE:
                return found
            page += 1

    def create(self, repository: str, number: int, body: str) -> None:
        self.client.post(f"/repos/{repository}/issues/{number}/comments", json={"body": body}).raise_for_status()

    def update(self, repository: str, comment: int, body: str) -> None:
        self.client.patch(f"/repos/{repository}/issues/comments/{comment}", json={"body": body}).raise_for_status()

    def merged_pulls(self, repository: str, base: str) -> list[dict]:
        """The most recently updated pull requests merged into `base`."""
        response = self.client.get(f"/repos/{repository}/pulls", params={
            "state": "closed", "base": base, "sort": "updated", "direction": "desc", "per_page": PAGE})
        response.raise_for_status()
        return [pull for pull in response.json() if pull.get("merged_at")]

    def check_run(self, repository: str, body: dict) -> None:
        self.client.post(f"/repos/{repository}/check-runs", json=body).raise_for_status()

    def delete(self, repository: str, comment: int) -> None:
        self.client.delete(f"/repos/{repository}/issues/comments/{comment}").raise_for_status()


def ours(comments: list[dict]) -> list[dict]:
    return [c for c in comments if re.match(r"^<!-- dry-lint(?::[^\n]*?)? -->", c.get("body", ""))]


def run_id() -> str:
    """This workflow run and attempt, so posting it again does not count it twice."""
    return "-".join(filter(None, (os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_RUN_ATTEMPT", ""))))


def upsert(github: GitHub, repository: str, number: int, markdown: str, findings: int, key: str = "",
           expect_head: str = "", banner: bool = False, run_url: str = "", note: str = "",
           skip_clean: bool = False, reports: list[Report] = (), run: str = "",
           repository_ledger: RepositoryLedger | None = None) -> str:
    """
    Create, update or leave the sticky comment, and say which: created, updated, resolved (it had findings and has
    none now), skipped (clean, `skip_clean`, never commented), stale (the pull request moved on) or forbidden (the
    token may not comment).
    """
    try:
        if expect_head and github.head_of(repository, number) != expect_head:
            return "stale"
        mine = ours(github.comments(repository, number))
        if not mine and findings == 0 and skip_clean:
            return "skipped"
        resolving = (findings == 0 and CLEAN in markdown and len(mine) == 1
                     and mine[0].get("body", "").startswith(marker(key)) and CLEAN not in mine[0].get("body", ""))
        if resolving:
            note = "\n\n".join(part for part in (RESOLVED, note) if part)
        body = compose(markdown, key, banner, run_url, expect_head, note,
                       account(mine, list(reports), run, repository_ledger))
        if not mine:
            github.create(repository, number, body)
            return "created"
        github.update(repository, mine[0]["id"], body)
        for extra in mine[1:]:
            github.delete(repository, extra["id"])
        return "resolved" if resolving else "updated"
    except httpx.HTTPStatusError as error:
        if error.response.status_code in (403, 404):
            return "forbidden"
        raise


def account(mine: list[dict], reports: list[Report], run: str, repository: RepositoryLedger | None) -> str:
    """
    The ledger section: the previous comment's ledger with this run added. With copies left by racing runs, the
    one that counted the most runs wins. Nothing before the first run with a report.
    """
    previous = [found for c in mine if (found := PullLedger.read(c.get("body", ""))) is not None]
    start = max(previous, key=lambda found: found.tally.runs, default=PullLedger())
    ledger = start.advance(reports, run)
    return ledger_render(ledger, repository) if ledger.tally.runs else ""


def combine(paths: list[Path]) -> str:
    if len(paths) == 1:
        return paths[0].read_text(encoding="utf-8")
    sections = []
    clean = True
    for path in paths:
        body = path.read_text(encoding="utf-8")
        clean = clean and CLEAN in body
        body = re.sub(r"^<!-- dry-lint(?::[^\n]*?)? -->\n?", "", body).replace(CLEAN, "")
        sections.append(f"## {path.stem.replace('-', ' ').capitalize()}\n\n{body.strip()}")
    return (CLEAN + "\n" if clean else "") + "\n\n---\n\n".join(sections)


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dry_lint.sticky", description="Upsert dry-lint's PR comment.")
    parser.add_argument("--body", type=Path, action="append", required=True,
                        help="Markdown report; repeat to combine scopes under headings from file names.")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--findings", type=int, required=True, help="How many findings the report has.")
    parser.add_argument("--key", default="",
                        help="Legacy marker label; all dry-lint markers share one comment. Serialize publishers per PR.")
    parser.add_argument("--expect-head", default="", help="Post only while this is still the PR's head commit.")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--note", default="", help="A line before the report, e.g. whether the findings block.")
    parser.add_argument("--skip-clean", action="store_true", help="Post nothing for a clean report never commented on.")
    parser.add_argument("--report", type=Path, action="append", default=[],
                        help="report.json of this run, to add to the pull request's ledger; repeat with --body.")
    parser.add_argument("--repository-ledger", type=Path, help="The repository's ledger, to show its totals.")
    parser.add_argument("--run", default=run_id(), help="This run's id, so posting it again does not count it twice.")
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("::warning title=dry-lint::No GITHUB_TOKEN, so no pull request comment.")
        return 0
    github = GitHub(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"), transport)
    reports = [Report.model_validate_json(path.read_text(encoding="utf-8")) for path in args.report]
    repository = args.repository_ledger
    totals = (RepositoryLedger.load(repository.read_text(encoding="utf-8"), args.repository)
              if repository and repository.exists() else None)
    outcome = upsert(github, args.repository, args.pull_request, combine(args.body), args.findings, args.key,
                     args.expect_head, banner_available(transport), args.run_url, args.note, args.skip_clean,
                     reports, args.run, totals)
    if outcome == "forbidden":
        print("::warning title=dry-lint::This token may not comment on the pull request (a fork?). "
              "The findings are in the annotations and the job summary.")
    elif outcome == "stale":
        print("::notice title=dry-lint::The pull request has a newer commit; its own run will comment.")
    print(f"dry-lint sticky comment: {outcome}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
