import json
import re
from pathlib import Path

import httpx
import pytest
from test_ledger import push
from test_report import finding

from dry_lint import sticky
from dry_lint.ledger import SPREAD, PullLedger, RepositoryLedger
from dry_lint.report import CLEAN, NOTE_SLOT
from dry_lint.sticky import MARKER, GitHub, compose, marker, upsert

REPO, PR, HEAD = "acme/shop", 7, "a" * 40
REPORT = f"{MARKER}\n### dry-lint\n\n| Changed function | Looks like |\n| --- | --- |\n| `a.py::clip` | `b.py::shorten` |"


class FakeGitHub:
    """The slice of the GitHub REST API the sticky uses, in memory: comments of one pull request, and its head."""

    def __init__(self, comments: list[str] = (), head: str = HEAD, write_status: int = 200, banner: int = 404,
                 labels: list[str] = (), merged: list[dict] = (), elsewhere: dict[int, list[str]] | None = None,
                 pulls_status: int = 200, counter_status: int = 200):
        self.comments = [{"id": i + 1, "body": body} for i, body in enumerate(comments)]
        self.merged, self.elsewhere, self.pulls_status = list(merged), elsewhere or {}, pulls_status
        self.counter_status, self.counted = counter_status, []
        self.labels = [{"name": name} for name in labels]
        self.head, self.write_status, self.banner = head, write_status, banner
        self.writes: list[str] = []
        self.check_runs: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if request.url.host == "raw.githubusercontent.com":
            return httpx.Response(self.banner)
        if request.url.host.endswith(".workers.dev"):  # dry-lint's global counter
            if self.counter_status == 200:
                self.counted.append(json.loads(request.content))
            return httpx.Response(self.counter_status, json={"counted": True})
        if method == "GET" and path == f"/repos/{REPO}/pulls/{PR}":
            return httpx.Response(200, json={"head": {"sha": self.head}, "labels": self.labels})
        if method == "GET" and path == f"/repos/{REPO}/pulls":
            return httpx.Response(self.pulls_status, json=self.merged)
        if method == "GET" and (other := re.fullmatch(rf"/repos/{REPO}/issues/(\d+)/comments", path)) and \
                int(other[1]) != PR:
            return httpx.Response(200, json=[{"id": 900, "body": body} for body in self.elsewhere.get(int(other[1]), [])])
        if method == "GET" and path == f"/repos/{REPO}/issues/{PR}/comments":
            page, size = int(request.url.params["page"]), int(request.url.params["per_page"])
            return httpx.Response(200, json=self.comments[(page - 1) * size: page * size])
        if self.write_status != 200:
            return httpx.Response(self.write_status, json={"message": "Resource not accessible by integration"})
        self.writes.append(method)
        if path == f"/repos/{REPO}/check-runs":
            self.check_runs.append(json.loads(request.content))
            return httpx.Response(201, json={})
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


CLEAN_REPORT = f"{MARKER}\n{CLEAN}\n### dry-lint · ✨ No duplicated concepts\n\n{NOTE_SLOT}\n\n| Look-alike pairs | 0 |"


def test_a_clean_pull_request_gets_a_clean_report_unless_skipped() -> None:
    fake = FakeGitHub()
    assert upsert(client(fake), REPO, PR, CLEAN_REPORT, findings=0) == "created"
    [body] = fake.stickies()
    assert "✨ No duplicated concepts" in body and "Resolved" not in body
    assert upsert(client(fake), REPO, PR, CLEAN_REPORT, findings=0) == "updated"
    assert "Resolved" not in fake.stickies()[0]
    quiet = FakeGitHub()
    assert upsert(client(quiet), REPO, PR, CLEAN_REPORT, findings=0, skip_clean=True) == "skipped"
    assert quiet.writes == []


def test_fixing_the_findings_turns_the_comment_into_resolved() -> None:
    for skip_clean in (False, True):
        fake = FakeGitHub(comments=[compose(REPORT)])
        assert upsert(client(fake), REPO, PR, CLEAN_REPORT, findings=0, skip_clean=skip_clean) == "resolved"
        [body] = fake.stickies()
        assert body.index("> [!TIP]\n> **Resolved:**") < body.index("| Look-alike pairs | 0 |")
        assert "b.py::shorten" not in body


def test_copies_left_by_racing_runs_are_removed() -> None:
    fake = FakeGitHub(comments=[compose(REPORT), "human", compose(REPORT)])
    assert upsert(client(fake), REPO, PR, REPORT, findings=1) == "updated"
    assert len(fake.stickies()) == 1 and "human" in [c["body"] for c in fake.comments]


def test_comments_are_found_beyond_the_first_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sticky, "PAGE", 2)
    fake = FakeGitHub(comments=["a", "b", "c", "d", compose(REPORT)])
    assert upsert(client(fake), REPO, PR, REPORT, findings=1) == "updated"
    assert fake.writes == ["PATCH"]


def test_legacy_keys_are_migrated_to_one_comment_without_touching_human_discussion() -> None:
    fake = FakeGitHub(comments=[compose(REPORT, key="repository-audit"), "human discussion",
                               compose(REPORT), compose(REPORT, key="cross-repository")])
    upsert(client(fake), REPO, PR, REPORT, findings=1)
    assert len(fake.stickies()) == 1
    assert [c["body"] for c in fake.comments][1:] == ["human discussion"]
    upsert(client(fake), REPO, PR, REPORT, findings=1, key="web")
    assert len(fake.comments) == 2
    assert len(fake.stickies("web")) == 1


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
    assert "sticky-banner-dark.svg" in body and "sticky-banner-light.svg\" width=\"100%\"" in body
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
    assert sticky.main(["--body", str(body), "--pull-request", "1", "--findings", "1", "--skip-clean"]) == 0
    assert "No GITHUB_TOKEN" in capsys.readouterr().out


def test_effective_status_precedes_findings_so_overrides_are_visible() -> None:
    body = compose(REPORT, note="**Blocking:** 1 finding(s)", head=HEAD)
    assert body.index("**Blocking:**") < body.index("b.py::shorten") < body.index(f"commit {HEAD[:7]}")
    assert "**Blocking:**" not in compose(REPORT)


def test_a_status_note_fills_the_reports_slot_and_an_empty_one_leaves_no_trace() -> None:
    slotted = f"{MARKER}\n### dry-lint\n\nbadges\n\n{NOTE_SLOT}\n\nlead\n\n| a | b |"
    body = compose(slotted, note="> [!CAUTION]\n> **Blocking:** 1 finding(s)")
    assert body.index("> [!CAUTION]") < body.index("<details>") < body.index("badges") and NOTE_SLOT not in body
    assert "badges\n\nlead" in compose(slotted) and NOTE_SLOT not in compose(slotted)


def test_combined_scan_details_are_collapsed_with_one_visible_status_note(tmp_path: Path) -> None:
    local, peers = tmp_path / "local.md", tmp_path / "cross-repository.md"
    local.write_text(f"{MARKER}\n### dry-lint · 1 duplicated concept\n\n{NOTE_SLOT}\n\nlong finding explanation")
    peers.write_text(f"{MARKER}\n{CLEAN}\n### dry-lint · ✨ No duplicated concepts\n\n{NOTE_SLOT}\n\nscan accounting")
    body = compose(sticky.combine([local, peers]), note="Checks are advisory.")
    assert body.count("Checks are advisory.") == 1
    assert body.index("Checks are advisory.") < body.index("<details>")
    assert "<summary><strong>Local · 1 duplicated concept</strong></summary>" in body
    assert "<summary><strong>Cross repository · ✨ No duplicated concepts</strong></summary>" in body
    assert "long finding explanation" in body and "scan accounting" in body
    assert "## Local" not in body and "### dry-lint" not in body and CLEAN not in body


def test_unavailable_scan_and_untrusted_headings_stay_clear_in_collapsed_summaries() -> None:
    body = compose("## Local\n\n> [!WARNING]\n> Scan did not complete.")
    assert "Local · Assessment unavailable</strong></summary>" in body
    assert "Scan did not complete." in body
    body = compose("### dry-lint · <img src=x>\n\nevidence")
    assert "<summary><strong>&lt;img src=x&gt;</strong></summary>" in body
    assert "<img src=x>" not in body


def test_the_source_line_names_dry_lint_the_commit_and_the_run() -> None:
    body = compose(REPORT, run_url="https://github.com/acme/shop/actions/runs/9", head=HEAD)
    assert body.rstrip().endswith(f"<sub>[dry-lint](https://github.com/gigaverse-app/dry-lint) · commit {HEAD[:7]} · "
                                  "[run](https://github.com/acme/shop/actions/runs/9)</sub>")


def test_combined_report_posts_both_scopes_once_and_does_not_claim_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    local, peers = tmp_path / "local.md", tmp_path / "cross-repository.md"
    local.write_text(CLEAN_REPORT, encoding="utf-8")
    peers.write_text(REPORT, encoding="utf-8")
    fake = FakeGitHub(comments=[compose(REPORT, key="audit"), compose(REPORT, key="cross-repository")])
    args = ["--body", str(local), "--body", str(peers), "--repository", REPO,
            "--pull-request", str(PR), "--findings", "1", "--expect-head", HEAD]
    sticky.main(args, transport=httpx.MockTransport(fake))
    [body] = fake.stickies()
    assert len(fake.comments) == 1
    assert "<summary><strong>Local ·" in body and "<summary><strong>Cross repository ·" in body
    assert "b.py::shorten" in body and "Look-alike pairs" in body
    assert CLEAN not in body and body.count(MARKER) == 1
    peers.write_text(CLEAN_REPORT, encoding="utf-8")
    args[args.index("--findings") + 1] = "0"
    sticky.main(args, transport=httpx.MockTransport(fake))
    [body] = fake.stickies()
    assert CLEAN in body and "Resolved" in body


def test_an_incomplete_scope_cannot_resolve_previous_findings(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    local, peers = tmp_path / "local.md", tmp_path / "cross-repository.md"
    local.write_text(CLEAN_REPORT, encoding="utf-8")
    peers.write_text("> [!WARNING]\n> This scope did not complete.", encoding="utf-8")
    fake = FakeGitHub(comments=[compose(REPORT)])
    sticky.main(["--body", str(local), "--body", str(peers), "--repository", REPO,
                 "--pull-request", str(PR), "--findings", "0"], transport=httpx.MockTransport(fake))
    [body] = fake.stickies()
    assert "Resolved" not in body and "did not complete" in body


def test_a_failed_peer_scope_does_not_claim_its_earlier_duplicate_was_kept_out(tmp_path, monkeypatch):
    """INVARIANT: the ledger's "kept out" counts only duplicates whose own scope reported again without them."""
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    fake = FakeGitHub()
    local, peers = tmp_path / "local.md", tmp_path / "cross-repository.md"
    local_json, peers_json = tmp_path / "local.json", tmp_path / "cross-repository.json"
    local.write_text(CLEAN_REPORT, encoding="utf-8")
    peers.write_text(REPORT, encoding="utf-8")
    local_json.write_text(push("a" * 40).model_dump_json())
    peers_json.write_text(push("a" * 40, finding("duplicate")).model_dump_json())
    common = ["--body", str(local), "--body", str(peers), "--repository", REPO, "--pull-request", str(PR)]
    sticky.main([*common, "--findings", "1", "--run", "1", "--report", f"local={local_json}",
                 "--report", f"cross-repository={peers_json}"], transport=httpx.MockTransport(fake))
    assert ledger_of(fake).count("open") == 1
    peers.write_text("> [!WARNING]\n> This scope did not complete.", encoding="utf-8")
    local_json.write_text(push("b" * 40).model_dump_json())
    sticky.main([*common, "--findings", "0", "--run", "2", "--report", f"local={local_json}"],
                transport=httpx.MockTransport(fake))
    assert (ledger_of(fake).count("open"), ledger_of(fake).count("kept-out")) == (1, 0)
    assert "kept out of the codebase**" not in fake.stickies()[0]


@pytest.mark.parametrize("argument, expected", [
    ("local=/tmp/local.json", ("local", Path("/tmp/local.json"))),
    ("/tmp/report.json", ("", Path("/tmp/report.json"))),
    ("/tmp/odd=name.json", ("", Path("/tmp/odd=name.json"))),
])  # fmt: skip
def test_a_report_argument_names_its_scope_or_has_none(argument: str, expected: tuple[str, Path]) -> None:
    assert sticky.scoped(argument) == expected


def post(fake: FakeGitHub, tmp_path: Path, report, run: str, *extra: str) -> None:
    body, saved = tmp_path / "comment.md", tmp_path / f"report-{run}.json"
    body.write_text(REPORT)
    saved.write_text(report.model_dump_json())
    args = ["--body", str(body), "--repository", REPO, "--pull-request", str(PR), "--findings", "0",
            "--report", str(saved), "--run", run, *extra]
    assert sticky.main(args, transport=httpx.MockTransport(fake)) == 0


def ledger_of(fake: FakeGitHub) -> PullLedger:
    [body] = fake.stickies()
    return PullLedger.read(body)


def test_the_comment_keeps_the_pull_requests_ledger_across_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    fake = FakeGitHub()
    post(fake, tmp_path, push("a" * 40, finding("duplicate")), "1")
    post(fake, tmp_path, push("b" * 40), "2")
    post(fake, tmp_path, push("b" * 40), "2")  # the same run, posting again
    ledger = ledger_of(fake)
    assert (ledger.pushed, ledger.tally.runs, ledger.count("kept-out")) == (2, 2, 1)
    assert "**1 duplicate kept out of the codebase** for $0.004 of judging, across 2 pushes." in fake.stickies()[0]
    body = fake.stickies()[0]
    assert body.index("### 🧹 A little less lint") < body.index("<summary><strong>Scan details")
    assert "| **1 pair** | **0 pairs** | **0 pairs** |" in body.replace(SPREAD, "")
    assert "`bbbbbbb` · **+1 pair cleaned up**" in body


def test_the_run_defaults_to_the_workflow_run_and_attempt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_RUN_ID", "41")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    fake = FakeGitHub()
    body, saved = tmp_path / "comment.md", tmp_path / "report.json"
    body.write_text(REPORT)
    saved.write_text(push("a" * 40).model_dump_json())
    sticky.main(["--body", str(body), "--repository", REPO, "--pull-request", str(PR), "--findings", "0",
                 "--report", str(saved)], transport=httpx.MockTransport(fake))
    assert ledger_of(fake).runs == ["41-2"]


def test_the_ledger_with_the_most_runs_survives_racing_copies() -> None:
    fewer = PullLedger().advance([push("a" * 40)], run="1")
    more = fewer.advance([push("b" * 40, finding("duplicate"))], run="2")
    fake = FakeGitHub([f"{MARKER}\nold\n{fewer.snapshot()}", f"{MARKER}\nnew\n{more.snapshot()}"])
    upsert(client(fake), REPO, PR, REPORT, 1, reports=[push("c" * 40)], run="3")
    ledger = ledger_of(fake)
    assert ledger.pushed == 3 and ledger.count("kept-out") == 1


def test_a_post_without_a_report_keeps_the_ledger_as_it_was() -> None:
    before = PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1")
    fake = FakeGitHub([f"{MARKER}\nold\n{before.snapshot()}"])
    upsert(client(fake), REPO, PR, REPORT, 1)
    assert ledger_of(fake) == before


def test_no_ledger_is_shown_before_a_run_reports() -> None:
    fake = FakeGitHub()
    upsert(client(fake), REPO, PR, REPORT, 1)
    assert "so far" not in fake.stickies()[0] and PullLedger.read(fake.stickies()[0]) is None


def test_the_repositorys_totals_follow_the_pull_requests_own(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    totals = RepositoryLedger(repository=REPO, since="2026-10-01T00:00:00+00:00")
    totals.add_pull(3, PullLedger().advance([push("a" * 40, finding("duplicate"))], run="1").advance([push("b" * 40)], run="2"))
    saved = tmp_path / "repository.json"
    saved.write_text(totals.model_dump_json())
    fake = FakeGitHub()
    post(fake, tmp_path, push("c" * 40), "5", "--repository-ledger", str(saved))
    post(fake, tmp_path, push("d" * 40), "6", "--repository-ledger", str(tmp_path / "missing.json"))
    assert "🏆" not in fake.stickies()[0]
    fake = FakeGitHub()
    post(fake, tmp_path, push("c" * 40), "5", "--repository-ledger", str(saved))
    assert "<sub>🏆 `acme/shop` since Oct 1, 2026: **1 duplicate kept out of the codebase**" in fake.stickies()[0]
