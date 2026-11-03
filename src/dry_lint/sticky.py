"""
The sticky pull request comment: one comment per pull request (and key), edited in place on every run.

    python -m dry_lint.sticky --body comment.md --repository owner/repo --pull-request 12 --findings 2 \
        [--key api] [--expect-head SHA] [--run-url URL] [--skip-clean]

- **Found by its marker.** The comment's first line is `<!-- dry-lint -->`, or `<!-- dry-lint:KEY -->` when one
  repository reports several packages or workflows. Extra copies left by two runs racing are deleted.
- **Clean is news too.** A clean pull request gets a clean report with what was checked, unless `--skip-clean`.
  A comment from an earlier run with findings is updated to say they are resolved, so it never goes stale.
- **Never about the wrong commit.** With `--expect-head`, nothing is posted once the pull request has moved on
  to a newer commit: that commit's own run will post.
- **Never fails the build for lack of permission.** A pull request from a fork gets a read-only token: the
  comment is skipped with a warning, and the annotations and job summary still carry the findings.

The token comes from GITHUB_TOKEN, and the API root from GITHUB_API_URL (GitHub Enterprise Server works).
"""

import argparse
import os
import sys
from pathlib import Path

import httpx

from dry_lint.report import CLEAN, NOTE_SLOT

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


def compose(markdown: str, key: str = "", banner: bool = False, run_url: str = "", head: str = "", note: str = "") -> str:
    """The comment body: the marker, the banner if it can render, the report, and where it came from."""
    lines = markdown.strip().splitlines()
    if lines and lines[0].strip().startswith("<!-- dry-lint"):
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

    def check_run(self, repository: str, body: dict) -> None:
        self.client.post(f"/repos/{repository}/check-runs", json=body).raise_for_status()

    def delete(self, repository: str, comment: int) -> None:
        self.client.delete(f"/repos/{repository}/issues/comments/{comment}").raise_for_status()


def upsert(github: GitHub, repository: str, number: int, markdown: str, findings: int, key: str = "",
           expect_head: str = "", banner: bool = False, run_url: str = "", note: str = "",
           skip_clean: bool = False) -> str:
    """
    Create, update or leave the sticky comment, and say which: created, updated, resolved (it had findings and has
    none now), skipped (clean, `skip_clean`, never commented), stale (the pull request moved on) or forbidden (the
    token may not comment).
    """
    try:
        if expect_head and github.head_of(repository, number) != expect_head:
            return "stale"
        mine = [c for c in github.comments(repository, number) if c.get("body", "").startswith(marker(key))]
        if not mine and findings == 0 and skip_clean:
            return "skipped"
        resolving = findings == 0 and bool(mine) and CLEAN not in mine[0].get("body", "")
        if resolving:
            note = "\n\n".join(part for part in (RESOLVED, note) if part)
        body = compose(markdown, key, banner, run_url, expect_head, note)
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


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dry_lint.sticky", description="Upsert dry-lint's PR comment.")
    parser.add_argument("--body", type=Path, required=True, help="The markdown report (dry-lint --output).")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--findings", type=int, required=True, help="How many findings the report has.")
    parser.add_argument("--key", default="", help="Keeps one comment per key, for several reports per PR.")
    parser.add_argument("--expect-head", default="", help="Post only while this is still the PR's head commit.")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--note", default="", help="A line before the report, e.g. whether the findings block.")
    parser.add_argument("--skip-clean", action="store_true", help="Post nothing for a clean report never commented on.")
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("::warning title=dry-lint::No GITHUB_TOKEN, so no pull request comment.")
        return 0
    github = GitHub(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"), transport)
    outcome = upsert(github, args.repository, args.pull_request, args.body.read_text(), args.findings, args.key,
                     args.expect_head, banner_available(transport), args.run_url, args.note, args.skip_clean)
    if outcome == "forbidden":
        print("::warning title=dry-lint::This token may not comment on the pull request (a fork?). "
              "The findings are in the annotations and the job summary.")
    elif outcome == "stale":
        print("::notice title=dry-lint::The pull request has a newer commit; its own run will comment.")
    print(f"dry-lint sticky comment: {outcome}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
