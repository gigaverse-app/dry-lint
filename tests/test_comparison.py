import base64
import json
from urllib.parse import unquote

import httpx
import pytest
from test_action_sticky import CLEAN_REPORT, HEAD, PR, REPO, REPORT, FakeGitHub, client
from test_ledger import push
from test_report import finding

from dry_lint.comparison import VIEWER, Comparisons
from dry_lint.evidence import PairEvidence, SourceReference
from dry_lint.ledger import EVIDENCE_BYTES, PullLedger
from dry_lint.models import Run
from dry_lint.sticky import upsert

AFTER = "b" * 40
PEER = "acme/peer"


class SourceGitHub(FakeGitHub):
    def __init__(self, visibility="public", status=200):
        super().__init__()
        self.metadata = {REPO: {"visibility": visibility, "private": visibility != "public"}}
        self.status, self.sources, self.reads = status, {}, []

    def __call__(self, request):
        path = unquote(request.url.path)
        if request.method == "GET" and path.startswith("/repos/"):
            repository = "/".join(path.split("/")[2:4])
            if path == f"/repos/{repository}":
                return httpx.Response(self.status, json=self.metadata.get(repository, {}))
            if "/contents/" in path:
                relative = path.split("/contents/", 1)[1]
                self.reads.append((repository, request.url.params["ref"], relative))
                status, source = self.sources.get(relative, (404, ""))
                return httpx.Response(status, text=source)
        return super().__call__(request)


def report(head=HEAD, *findings):
    return push(head, *findings).model_copy(update={"run": Run(repository=REPO, pull_request=PR, head=head)})


def post(fake, built, run):
    return upsert(client(fake), REPO, PR, REPORT if built.visible else CLEAN_REPORT, len(built.visible),
                  reports=[built], run=run)


def payload(body):
    encoded = body.split("#v2=", 1)[1].split(")", 1)[0]
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))


@pytest.mark.parametrize("visibility,status", [("private", 200), ("internal", 200), (None, 200),
                                               ("public", 403), ("public", 404), ("public", 500)])
def test_nonpublic_or_unverifiable_repositories_only_get_github_links(visibility, status):
    fake = SourceGitHub(visibility, status)
    post(fake, report(HEAD, finding("drifted", why="existing judgment")), "1")
    post(fake, report(AFTER), "2")
    body = fake.stickies()[0]
    assert f"https://github.com/{REPO}/blob/{HEAD}/src/widgets/caption.py#L1-L2" in body
    assert f"https://github.com/{REPO}/compare/{HEAD}...{AFTER}" in body
    assert "existing judgment" in body
    assert "#v2=" not in body and VIEWER not in body and fake.reads == []


def test_public_cleanup_links_both_originals_to_the_uniquely_remaining_symbol():
    fake = SourceGitHub()
    fake.sources["src/text.py"] = (200, "\n\ndef shorten(text, limit):\n    return text[:limit].strip()\n")
    built = report(HEAD, finding("drifted", why="shared concept", cached=True))
    post(fake, built, "1")
    initial = payload(fake.stickies()[0])
    assert initial["result"] is None and initial["state"] == "open"
    post(fake, report(AFTER), "2")
    body = fake.stickies()[0]
    data = payload(body)
    assert "Three-way view" in body
    assert data["evidence"]["a"]["revision"] == HEAD == data["evidence"]["b"]["revision"]
    assert data["result"]["revision"] == AFTER and data["result"]["line"] == 3
    assert data["result"]["name"] == "shorten" and data["state"] == "kept-out"
    assert data["evidence"]["verdict"] == built.findings[0].verdict.model_dump()
    assert "return text" not in json.dumps(data)
    assert "return text" not in body
    ledger = PullLedger.read(body)
    assert ledger.count("kept-out") == 1 and ledger.tally.judgments == 1
    assert body.index("Compare the code") < body.index("History and check stats")


@pytest.mark.parametrize("left,right", [(404, 404), (200, 200), (500, 200)])
def test_absence_or_failed_reads_do_not_invent_a_consolidated_result(left, right):
    fake = SourceGitHub()
    fake.sources = {"src/widgets/caption.py": (left, "def clip(text, limit):\n    return text[:limit]\n"),
                    "src/text.py": (right, "def shorten(text, limit):\n    return text[:limit]\n")}
    post(fake, report(HEAD, finding("duplicate")), "1")
    post(fake, report(AFTER), "2")
    assert payload(fake.stickies()[0])["result"] is None
    assert "Three-way view" not in fake.stickies()[0]


def test_a_private_peer_prevents_a_public_repository_from_linking_the_viewer():
    fake = SourceGitHub()
    candidate = finding("drifted")
    candidate.candidate.existing.origin = Run(repository=PEER, head=HEAD)
    fake.metadata[PEER] = {"visibility": "private", "private": True}
    post(fake, report(HEAD, candidate), "1")
    body = fake.stickies()[0]
    assert f"https://github.com/{PEER}/blob/{HEAD}" in body and "#v2=" not in body


@pytest.mark.parametrize("label,score,outcome", [
    ("drifted", .76, "Not reported: low confidence"),
    ("duplicate", .71, "Not reported: low confidence"),
    ("separate", .51, "Not reported: judged separate"),
    ("separate", .95, "Not reported: judged separate"),
])
def test_unreported_candidates_distinguish_low_confidence_from_separate(label, score, outcome):
    fake = SourceGitHub("private")
    post(fake, report(HEAD, finding(label, score=score, why="different boundaries")), "1")
    body = fake.stickies()[0]
    assert outcome in body and f"{label}; confidence {score:.2f}" in body and "different boundaries" in body
    assert "not counted as tangled" in body
    assert "[A](https://github.com/" in body


def test_cleanup_includes_direct_helper_coordinates_without_extra_reads_or_judgments():
    fake = SourceGitHub()
    fake.sources["src/text.py"] = (200, "def shared(text):\n    return text.strip()\n\n"
                                       "def shorten(text, limit):\n    return shared(text)[:limit]\n")
    post(fake, report(HEAD, finding("drifted")), "1")
    post(fake, report(AFTER), "2")
    data = payload(fake.stickies()[0])
    assert data["schema"] == 2
    assert data["helpers"] == [{"repository": REPO, "revision": AFTER, "path": "src/text.py",
                                "name": "shared", "owner": None, "line": 1, "end_line": 2}]
    assert len(fake.reads) == 2
    assert "return text" not in json.dumps(data)
    assert PullLedger.read(fake.stickies()[0]).tally.judgments == 1


def test_old_ledgers_still_load_without_inventing_historical_evidence():
    ledger = PullLedger.model_validate({"schema": 5, "pairs": {"old": {"new": "a", "existing": "b", "found": 1}}})
    assert ledger.pairs["old"].evidence is None
    assert Comparisons(client(SourceGitHub()), REPO, HEAD, VIEWER).render(ledger, []) == ""


@pytest.mark.parametrize("viewer", ["", "http://example.com", "https://user:password@example.com", "javascript:alert(1)",
                                    "https://example.com/?secret=a", "https://example.com/#old"])
def test_invalid_viewer_configuration_keeps_useful_github_links(viewer):
    fake = SourceGitHub()
    built = report(HEAD, finding("duplicate"))
    upsert(client(fake), REPO, PR, REPORT, 1, reports=[built], viewer_url=viewer)
    body = fake.stickies()[0]
    assert "[A](https://github.com/" in body and "#v2=" not in body


def test_oversized_links_fall_back_without_discarding_the_github_evidence():
    fake = SourceGitHub()
    built = report(HEAD, finding("duplicate", why="x" * 15000))
    post(fake, built, "1")
    body = fake.stickies()[0]
    assert "#v2=" not in body and "[A](https://github.com/" in body


def test_enterprise_sources_stay_on_their_github_host(monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.example.com")
    fake = SourceGitHub()
    post(fake, report(HEAD, finding("duplicate")), "1")
    assert "[A](https://github.example.com/" in fake.stickies()[0]
    assert "#v2=" not in fake.stickies()[0]


def test_invalid_coordinates_are_not_persisted_as_evidence():
    built = report("not-a-commit", finding("duplicate"))
    assert PairEvidence.of(built.findings[0], built.run) is None
    for update in ({"repository": "bad"}, {"path": "../private.py"}):
        good = PairEvidence.of(finding("duplicate"), Run(repository=REPO, head=HEAD)).a
        with pytest.raises(ValueError):
            SourceReference.model_validate({**good.model_dump(), **update})


def test_judge_text_is_escaped_in_the_sticky_and_inert_in_the_viewer_payload():
    fake = SourceGitHub()
    reason = '--><script>alert(1)</script> [click](https://evil.example) | new row'
    post(fake, report(HEAD, finding("drifted", why=reason)), "1")
    body = fake.stickies()[0]
    visible = body.split("<!-- dry-lint-ledger ")[0]
    assert '<script>' not in body and '[click](https://evil.example)' not in visible
    assert PullLedger.read(body).pairs[finding("drifted").candidate.key].evidence.verdict.why == reason
    assert payload(body)["evidence"]["verdict"]["why"] == reason


@pytest.mark.parametrize("path,repository,head,source", [
    ("unknown.rs", REPO, AFTER, ""),
    ("src/text.py", PEER, AFTER, ""),
    ("src/text.py", REPO, "main", ""),
    ("src/text.py", REPO, AFTER, "def shorten(:\n"),
    ("src/text.py", REPO, AFTER, "def shorten(t,n):\n return t\ndef shorten(t,n):\n return n\n"),
])
def test_unresolvable_symbol_identities_never_select_a_result(path, repository, head, source):
    fake = SourceGitHub()
    fake.sources[path] = (200, source)
    reference = SourceReference.of(finding("duplicate").candidate.existing, Run(repository=repository, head=HEAD))
    reference.path = path
    assert Comparisons(client(fake), REPO, head, VIEWER).current(reference) == (False, None)


def test_typescript_resolution_uses_the_parser_and_caches_source_reads():
    fake = SourceGitHub()
    fake.sources['src/view.tsx'] = (200, 'export const View = () => <div>Hello</div>;\n')
    reference = SourceReference(repository=REPO, revision=HEAD, path='src/view.tsx', name='View', line=1, end_line=1)
    comparisons = Comparisons(client(fake), REPO, AFTER, VIEWER)
    known, result = comparisons.current(reference)
    assert known and result.name == 'View' and result.revision == AFTER
    assert comparisons.current(reference) == (known, result)
    assert comparisons.helpers(result) == []
    assert len(fake.reads) == 1


def test_large_pair_sets_have_bounded_links_and_keep_the_scan_report():
    fake = SourceGitHub()
    built = report(HEAD, *(finding("drifted", existing=f"copy_{i}", why="x" * 4000) for i in range(7)))
    post(fake, built, "1")
    body = fake.stickies()[0]
    table = body.split("<details><summary><strong>Compare")[1].split("</details>")[0]
    assert 'Showing 5 of 7 pairs' in table and len(table) < 24000
    assert table.count('#v2=') < 5 and table.count('[A](') == 5


def test_updating_an_old_ledger_emits_the_new_schema():
    old = PullLedger(schema=5)
    updated = old.advance([report(HEAD, finding("duplicate"))])
    assert updated.schema_version == 6 and PullLedger.read(updated.snapshot()).schema_version == 6


def test_large_evidence_does_not_grow_the_sticky_ledger_or_lose_cleanup_counts():
    fake = SourceGitHub("private")
    built = report(HEAD, *(finding("drifted", existing=f"copy_{i}", why="<>" * 1000) for i in range(40)))
    post(fake, built, "1")
    body = fake.stickies()[0]
    ledger = PullLedger.read(body)
    assert ledger.count("open") == 40
    assert sum(len(p.evidence.model_dump_json().encode()) for p in ledger.pairs.values() if p.evidence) <= EVIDENCE_BYTES
    assert len(body) < 50000
    post(fake, report(AFTER), "2")
    assert PullLedger.read(fake.stickies()[0]).count("kept-out") == 40
