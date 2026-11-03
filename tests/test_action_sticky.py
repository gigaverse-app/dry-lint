import json
import re
from pathlib import Path

import httpx
import pytest

from dry_lint import sticky
from dry_lint.sticky import MARKER, GitHub, compose, marker, upsert

REPO, PR, HEAD = "acme/shop", 7, "a" * 40
REPORT = f"{MARKER}\n### dry-lint\n\n| Changed function | Looks like |\n| --- | --- |\n| `a.py::clip` | `b.py::shorten` |"


class FakeGitHub:
    """The slice of the GitHub REST API the sticky uses, in memory: comments of one pull request, and its head."""

    def __init__(self, comments: list[str] = (), head: str = HEAD, write_status: int = 200, banner: int = 404):
        self.comments = [{"id": i + 1, "body": body} for i, body in enumerate(comments)]
        self.head, self.write_status, self.banner = head, write_status, banner
        self.writes: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if request.url.host == "raw.githubusercontent.com":
            return httpx.Response(self.banner)
        if method == "GET" and path == f"/repos/{REPO}/pulls/{PR}":
            return httpx.Response(200, json={"head": {"sha": self.head}})
        if method == "GET" and path == f"/repos/{REPO}/issues/{PR}/comments":
            page, size = int(request.url.params["page"]), int(request.url.params["per_page"])
            return httpx.Response(200, json=self.comments[(page - 1) * size: page * size])
        if self.write_status != 200:
            return httpx.Response(self.write_status, json={"message": "Resource not accessible by integration"})
        self.writes.append(method)
        if method == "POST":
            body = json.loads(request.content)["body"]
            self.comments.append({"id": len(self.comments) + 100, "body": body})
            return httpx.Response(201, json={})
        number = int(path.rsplit("/", 1)[1])
        if method == "PATCH":
            next(c for c in self.comments if c["id"] == number)["body"] = json.loads(request.content)["body"]
        else:
            self.comments = [c for c in self.comments if c["id"] != number]
        return httpx.Response(200, json={})

    def stickies(self, key: str = "") -> list[str]:
        return [c["body"] for c in self.comments if c["body"].startswith(marker(key))]


def client(fake: FakeGitHub) -> GitHub:
    return GitHub("token", transport=httpx.MockTransport(fake))


def test_a_pull_request_with_findings_gets_exactly_one_comment_across_runs() -> None:
    fake = FakeGitHub(comments=["LGTM", "nice"])
    assert upsert(client(fake), REPO, PR, REPORT, findings=1) == "created"
    assert upsert(client(fake), REPO, PR, REPORT.replace("clip", "trim"), findings=1) == "updated"
    [body] = fake.stickies()
    assert "a.py::trim" in body and "a.py::clip" not in body
    assert [c["body"] for c in fake.comments[:2]] == ["LGTM", "nice"]


def test_a_clean_pull_request_gets_no_comment() -> None:
    fake = FakeGitHub()
    assert upsert(client(fake), REPO, PR, REPORT, findings=0) == "skipped"
    assert fake.writes == []


def test_fixing_the_findings_turns_the_comment_into_resolved() -> None:
    fake = FakeGitHub(comments=[compose(REPORT)])
    assert upsert(client(fake), REPO, PR, REPORT, findings=0) == "resolved"
    [body] = fake.stickies()
    assert "Resolved" in body and "b.py::shorten" not in body


def test_copies_left_by_racing_runs_are_removed() -> None:
    fake = FakeGitHub(comments=[compose(REPORT), "human", compose(REPORT)])
    assert upsert(client(fake), REPO, PR, REPORT, findings=1) == "updated"
    assert len(fake.stickies()) == 1 and "human" in [c["body"] for c in fake.comments]


def test_comments_are_found_beyond_the_first_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sticky, "PAGE", 2)
    fake = FakeGitHub(comments=["a", "b", "c", "d", compose(REPORT)])
    assert upsert(client(fake), REPO, PR, REPORT, findings=1) == "updated"
    assert fake.writes == ["PATCH"]


def test_each_key_keeps_its_own_comment() -> None:
    fake = FakeGitHub()
    upsert(client(fake), REPO, PR, REPORT, findings=1, key="api")
    upsert(client(fake), REPO, PR, REPORT, findings=1, key="web")
    upsert(client(fake), REPO, PR, REPORT, findings=1)
    assert len(fake.stickies("api")) == len(fake.stickies("web")) == len(fake.stickies()) == 1
    assert fake.stickies("api")[0].startswith("<!-- dry-lint:api -->")


def test_nothing_is_posted_once_the_pull_request_has_moved_on() -> None:
    fake = FakeGitHub(head="b" * 40)
    assert upsert(client(fake), REPO, PR, REPORT, findings=1, expect_head=HEAD) == "stale"
    assert fake.writes == []
    assert upsert(client(FakeGitHub()), REPO, PR, REPORT, findings=1, expect_head=HEAD) == "created"


@pytest.mark.parametrize("status", [403, 404])
def test_a_token_that_may_not_comment_is_reported_not_raised(status: int) -> None:
    assert upsert(client(FakeGitHub(write_status=status)), REPO, PR, REPORT, findings=1) == "forbidden"


def test_other_api_errors_are_raised() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        upsert(client(FakeGitHub(write_status=500)), REPO, PR, REPORT, findings=1)


def test_the_comment_carries_one_marker_the_banner_when_it_renders_and_its_source() -> None:
    body = compose(REPORT, key="api", banner=True, run_url="https://github.com/acme/shop/actions/runs/9", head=HEAD)
    assert body.startswith("<!-- dry-lint:api -->\n<picture>") and body.count("<!-- dry-lint") == 1
    assert "sticky-banner-dark.svg" in body and "sticky-banner-light.svg" in body
    assert f"commit {HEAD[:7]}" in body and "[run](https://github.com/acme/shop/actions/runs/9)" in body
    assert "<picture>" not in compose(REPORT) and "<sub>" not in compose(REPORT)


@pytest.mark.parametrize("status, expected", [(200, True), (404, False)])
def test_the_banner_is_used_only_when_github_can_fetch_it(status: int, expected: bool) -> None:
    assert sticky.banner_available(httpx.MockTransport(lambda request: httpx.Response(status))) is expected


def test_an_unreachable_banner_host_means_no_banner() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    assert sticky.banner_available(httpx.MockTransport(down)) is False


def test_the_command_posts_and_reports_the_outcome(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    body = tmp_path / "comment.md"
    body.write_text(REPORT)
    fake = FakeGitHub(banner=200)
    args = ["--body", str(body), "--repository", REPO, "--pull-request", str(PR), "--findings", "1"]
    assert sticky.main(args, transport=httpx.MockTransport(fake)) == 0
    assert "sticky comment: created" in capsys.readouterr().out
    assert fake.stickies()[0].startswith(MARKER + "\n<picture>")


@pytest.mark.parametrize("fake, extra, message", [
    (FakeGitHub(write_status=403), [], "may not comment"),
    (FakeGitHub(head="b" * 40), ["--expect-head", HEAD], "newer commit"),
])  # fmt: skip
def test_the_command_explains_skipped_comments_without_failing(fake, extra, message, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    body = tmp_path / "comment.md"
    body.write_text(REPORT)
    args = ["--body", str(body), "--repository", REPO, "--pull-request", str(PR), "--findings", "1", *extra]
    assert sticky.main(args, transport=httpx.MockTransport(fake)) == 0
    assert re.search(message, capsys.readouterr().out)


def test_without_a_token_the_command_warns_and_succeeds(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    body = tmp_path / "comment.md"
    body.write_text(REPORT)
    assert sticky.main(["--body", str(body), "--pull-request", "1", "--findings", "1"]) == 0
    assert "No GITHUB_TOKEN" in capsys.readouterr().out
