"""
The sticky pull request comment: one comment per pull request (and key), edited in place on every run.

    python -m dry_lint.sticky --body comment.md --repository owner/repo --pull-request 12 --findings 2 \
        [--key api] [--expect-head SHA] [--run-url URL]

- **Found by its marker.** The comment's first line is `<!-- dry-lint -->`, or `<!-- dry-lint:KEY -->` when one
  repository reports several packages or workflows. Extra copies left by two runs racing are deleted.
- **Quiet when clean.** A clean pull request gets no comment. A comment from an earlier run is updated to say
  the findings are resolved, so it never goes stale.
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
    if note:
        parts.append(f"\n{note}\n")
    parts.append("\n".join(lines).strip())
    source = [f"commit {head[:7]}" if head else "", f"[run]({run_url})" if run_url else ""]
    if any(source):
        parts.append(f"\n<sub>dry-lint · {' · '.join(s for s in source if s)}</sub>")
    return "\n".join(parts) + "\n"


def resolved(key: str = "", banner: bool = False, run_url: str = "", head: str = "") -> str:
    return compose("### dry-lint · Resolved\n\nNo findings remain at the configured report threshold in this run.", key,
                   banner, run_url, head)


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
           expect_head: str = "", banner: bool = False, run_url: str = "", note: str = "") -> str:
    """
    Create, update or leave the sticky comment, and say which: created, updated, resolved, skipped (clean and
    never commented), stale (the pull request moved on) or forbidden (the token may not comment).
    """
    try:
        if expect_head and github.head_of(repository, number) != expect_head:
            return "stale"
        mine = [c for c in github.comments(repository, number) if c.get("body", "").startswith(marker(key))]
        if not mine and findings == 0:
            return "skipped"
        body = compose(markdown, key, banner, run_url, expect_head, note) if findings else resolved(key, banner, run_url, expect_head)
        if not mine:
            github.create(repository, number, body)
            return "created"
        github.update(repository, mine[0]["id"], body)
        for extra in mine[1:]:
            github.delete(repository, extra["id"])
        return "updated" if findings else "resolved"
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
    parser.add_argument("--note", default="", help="A line after the report, e.g. whether the findings block.")
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("::warning title=dry-lint::No GITHUB_TOKEN, so no pull request comment.")
        return 0
    github = GitHub(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"), transport)
    outcome = upsert(github, args.repository, args.pull_request, args.body.read_text(), args.findings, args.key,
                     args.expect_head, banner_available(transport), args.run_url, args.note)
    if outcome == "forbidden":
        print("::warning title=dry-lint::This token may not comment on the pull request (a fork?). "
              "The findings are in the annotations and the job summary.")
    elif outcome == "stale":
        print("::notice title=dry-lint::The pull request has a newer commit; its own run will comment.")
    print(f"dry-lint sticky comment: {outcome}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
