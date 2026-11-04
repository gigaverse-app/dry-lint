"""What judging did on a repository's recent pull requests, from dry-lint's sticky comments and the PRs' checks.

    uv run python scripts/audit_judging.py gigaverse-app/gigaverse-ai --limit 100

For each pull request with a dry-lint comment: the preset, what judging spent against the budget (all pushes),
whether the budget ran out or a judge failed, whether the check failed, and whether the override label let it
through. Compare with the simulation in docs/benchmark.md#within-a-budget. Needs `gh`, logged in.
"""

import argparse
import json
import re
import subprocess
from collections.abc import Callable

from pydantic import BaseModel

MARKER = "<!-- dry-lint"
CHECK = "Duplicated concepts"
OVERRIDE = "dry-lint: override"
BILL = re.compile(r"est\. \$(?P<run>[\d.]+)(?: \(\$(?P<total>[\d.]+) so far\))? of \$(?P<budget>[\d.]+)")


class Judged(BaseModel):
    """One pull request's judging, as its sticky comment and checks show it."""

    number: int
    preset: str = ""
    spent: float | None = None
    budget: float | None = None
    capped: bool = False
    judge_failed: str = ""
    check_failed: bool = False
    overridden: bool = False


def judging_line(body: str) -> str:
    """The comment's judging line, unescaped; empty when the comment has none."""
    for line in reversed(body.splitlines()):
        text = re.sub(r"\\(.)", r"\1", line.removeprefix("<sub>").removesuffix("</sub>"))
        if BILL.search(text) or text.startswith("preset "):
            return text
    return ""


def judged(number: int, body: str, labels: list[str], checks: list[dict]) -> Judged:
    line = judging_line(body)
    bill = BILL.search(line)
    failure = re.search(r"· (\S+) failed \((.*?)\): \d+ pairs kept", line)
    return Judged(
        number=number,
        preset=m.group(1) if (m := re.match(r"preset (\S+)", line)) else "",
        spent=float(bill["total"] or bill["run"]) if bill else None,
        budget=float(bill["budget"]) if bill else None,
        capped="not judged (budget)" in line,
        judge_failed=f"{failure[1]}: {failure[2]}" if failure else "",
        check_failed=any(c.get("name") == CHECK and c.get("conclusion") == "FAILURE" for c in checks),
        overridden=OVERRIDE in labels,
    )


def gh(*args: str) -> object:
    return json.loads(subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout)


def audit(repository: str, limit: int, state: str = "merged", fetch: Callable[..., object] = gh) -> list[Judged]:
    pulls = fetch(
        "pr",
        "list",
        "--repo",
        repository,
        "--state",
        state,
        "--limit",
        str(limit),
        "--json",
        "number,labels,statusCheckRollup",
    )
    found = []
    for pull in pulls:
        comments = fetch("api", "--paginate", f"repos/{repository}/issues/{pull['number']}/comments")
        bodies = [c["body"] for c in comments if MARKER in c["body"]]
        if bodies:
            found.append(
                judged(
                    pull["number"],
                    bodies[-1],
                    [label["name"] for label in pull["labels"]],
                    pull["statusCheckRollup"] or [],
                )
            )
    return found


def summary(rows: list[Judged]) -> str:
    billed = [r for r in rows if r.spent is not None]
    lines = [f"{len(rows)} pull requests with a dry-lint comment; {len(billed)} show what judging spent"]
    if billed:
        spent = sorted(r.spent for r in billed)
        lines.append(
            f"spent a pull request: average ${sum(spent) / len(spent):.4f}, median ${spent[len(spent) // 2]:.4f}, "
            f"most ${spent[-1]:.4f}"
        )
    presets = sorted({r.preset for r in rows if r.preset})
    lines += [
        f"presets: {', '.join(presets) or 'none shown'}",
        f"budget ran out: {sum(r.capped for r in rows)}",
        f"a judge failed: {sum(bool(r.judge_failed) for r in rows)}",
        f"check failed: {sum(r.check_failed for r in rows)}; let through with '{OVERRIDE}': "
        f"{sum(r.overridden for r in rows)}",
    ]
    lines += [f"  #{r.number}: {r.judge_failed}" for r in rows if r.judge_failed]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repository", help="OWNER/NAME")
    parser.add_argument("--limit", type=int, default=100, help="The most recent pull requests to read.")
    parser.add_argument("--state", default="merged", choices=("merged", "open", "closed", "all"))
    parser.add_argument("--json", action="store_true", help="One JSON line per pull request instead of the summary.")
    args = parser.parse_args(argv)
    rows = audit(args.repository, args.limit, args.state)
    print("\n".join(r.model_dump_json() for r in rows) if args.json else summary(rows))


if __name__ == "__main__":
    main()
