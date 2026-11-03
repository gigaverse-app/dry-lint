import base64
import io
import json
import subprocess
import zipfile

import httpx
import pytest
from test_action import outputs

from dry_lint import action
from dry_lint.function_index import export_index
from dry_lint.index_github import PUBLISHER, IndexClient, blob_hash
from dry_lint.settings import Settings

pytest_plugins = ["test_action"]


@pytest.fixture
def index_server(repo):
    snapshot = export_index(repo.root, "org/app", Settings())
    archive = subprocess.run(["git", "-C", str(repo.root), "archive", "--format=tar.gz", "--prefix=app/", "HEAD"],
                             capture_output=True, check=True).stdout
    files = {p: subprocess.run(["git", "-C", str(repo.root), "show", f"HEAD:{p}"], capture_output=True, check=True).stdout
             for p in repo.git("ls-files").splitlines()}
    tree = [{"path": p, "sha": blob_hash(data), "mode": "100644", "type": "blob"} for p, data in files.items()]
    artifact = {"id": 7, "name": snapshot.artifact_name, "expired": False,
                "workflow_run": {"id": 8, "head_sha": snapshot.commit, "repository_id": 1, "head_repository_id": 1}}
    run = {"path": PUBLISHER, "head_sha": snapshot.commit, "head_branch": "main", "event": "push",
           "status": "completed", "conclusion": "success", "head_repository": {"full_name": "org/app"}}
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w") as output:
        output.writestr("functions.json.gz", snapshot.encode())
    responses = {
        "/repos/org/app/commits/main": {"sha": snapshot.commit, "commit": {"tree": {"sha": "tree"}}},
        "/repos/org/app/actions/artifacts": {"total_count": 1, "artifacts": [artifact]},
        "/repos/org/app/actions/runs/8": run,
        "/repos/org/app/actions/artifacts/7/zip": zipped.getvalue(),
        "/repos/org/app/git/trees/tree": {"tree": tree, "truncated": False},
        f"/repos/org/app/tarball/{snapshot.commit}": archive,
    }
    for data in files.values():
        responses[f"/repos/org/app/git/blobs/{blob_hash(data)}"] = {"encoding": "base64", "content": base64.b64encode(data).decode()}
    calls = []

    def handle(request):
        calls.append(request)
        value = responses[request.url.path]
        if callable(value):
            return value(request)
        if isinstance(value, bytes):
            return httpx.Response(200, content=value)
        return httpx.Response(200, json=value)

    return snapshot, responses, calls, httpx.MockTransport(handle)


def fetch(server):
    client = IndexClient("secret", transport=server[3])
    try:
        return client.fetch("org/app", "main", Settings())
    finally:
        client.close()


def test_artifact_hit_never_fetches_peer_source_and_retains_full_identity(index_server):
    snapshot, _, calls, _ = index_server
    result = fetch(index_server)
    assert result.index == snapshot
    assert result.source == "published artifact"
    assert len(calls) == 4
    assert result.transferred > 0
    assert snapshot.commit in result.receipt()
    assert all("tarball" not in str(call.url) and "/git/" not in str(call.url) for call in calls)


@pytest.mark.parametrize("field,value", [("path", "evil.yml"), ("head_branch", "feature"), ("event", "pull_request"),
                                        ("head_sha", "wrong"), ("status", "in_progress"), ("conclusion", "failure"),
                                        ("head_repository", {"full_name": "fork/app"})])
def test_untrusted_producer_rebuilds_requested_commit(index_server, field, value):
    index_server[1]["/repos/org/app/actions/runs/8"][field] = value
    result = fetch(index_server)
    assert result.index == index_server[0]
    assert "fallback" in result.source


@pytest.mark.parametrize("problem", ["expired", "wrong-name", "fork", "old-head", "missing", "corrupt", "403", "404", "410"])
def test_missing_expired_incompatible_or_corrupt_artifact_is_recovered(index_server, problem):
    responses = index_server[1]
    listing = responses["/repos/org/app/actions/artifacts"]
    artifact = listing["artifacts"][0]
    if problem == "expired":
        artifact["expired"] = True
    elif problem == "wrong-name":
        artifact["name"] = "old"
    elif problem == "fork":
        artifact["workflow_run"]["head_repository_id"] = 99
    elif problem == "old-head":
        artifact["workflow_run"]["head_sha"] = "old"
    elif problem == "missing":
        listing.update(total_count=0, artifacts=[])
    elif problem == "corrupt":
        responses["/repos/org/app/actions/artifacts/7/zip"] = b"broken"
    else:
        path = "/repos/org/app/actions/artifacts" if problem in {"403", "404"} else "/repos/org/app/actions/artifacts/7/zip"
        responses[path] = lambda _: httpx.Response(int(problem))
    assert fetch(index_server).index == index_server[0]


def test_export_ignore_and_export_subst_cannot_remove_or_change_indexed_source(index_server):
    snapshot, responses, _, _ = index_server
    import tarfile
    empty = io.BytesIO()
    with tarfile.open(fileobj=empty, mode="w:gz"):
        pass
    responses[f"/repos/org/app/tarball/{snapshot.commit}"] = empty.getvalue()
    responses["/repos/org/app/actions/artifacts"]["artifacts"] = []
    assert fetch(index_server).index == snapshot
    assert any("/git/blobs/" in str(call.url) for call in index_server[2])


def test_artifact_lookup_follows_pagination(index_server):
    responses = index_server[1]
    listing = responses["/repos/org/app/actions/artifacts"]
    responses["/repos/org/app/actions/artifacts"] = lambda request: httpx.Response(200, json=(
        {"total_count": 101, "artifacts": []} if request.url.params["page"] == "1" else listing))
    assert fetch(index_server).source == "published artifact"


def test_download_redirect_does_not_forward_token_to_storage(index_server):
    _, responses, _, transport = index_server
    zipped = responses["/repos/org/app/actions/artifacts/7/zip"]
    responses["/repos/org/app/actions/artifacts/7/zip"] = lambda _: httpx.Response(302, headers={"location": "https://storage.example/archive"})

    def storage(request):
        assert "authorization" not in request.headers
        return httpx.Response(200, content=zipped)

    responses["/archive"] = storage
    assert fetch(index_server).source == "published artifact"


def test_truncated_tree_cannot_be_reported_as_a_complete_index(index_server):
    responses = index_server[1]
    responses["/repos/org/app/actions/artifacts"]["artifacts"] = []
    responses["/repos/org/app/git/trees/tree"]["truncated"] = True
    with pytest.raises(ValueError, match="incomplete"):
        fetch(index_server)


@pytest.mark.parametrize("mode", ["single", "fetch-indexes"])
def test_action_consumes_indexes_through_the_real_cli(index_server, github_env, repo, tmp_path, twin_judge, mode):
    github_env("workflow_dispatch", {}, mode=mode, working_directory=str(repo.root), base="HEAD",
               repository_indexes="\norg/app@main\n", comment="false", judge="command", judge_command=twin_judge)
    assert action.main(["run"], transport=index_server[3]) == 0
    manifest = json.loads((action.workdir() / "index-arguments.json").read_text())
    assert manifest[0] == "--repo-index"
    assert index_server[0].commit in manifest[1]
    assert "published artifact" in (tmp_path / "summary").read_text()
    assert len(index_server[2]) == 4
    if mode == "single":
        report = json.loads((action.workdir() / "report.json").read_text())
        assert report["functions"] == len(index_server[0].functions) * 2


def test_action_publishes_functions_without_judging_or_commenting(github_env, repo, tmp_path):
    github_env("push", {}, mode="index", working_directory=str(repo.root))
    assert action.main(["run"]) == 0
    snapshot = export_index(repo.root, "acme/shop", Settings())
    assert (action.workdir() / "functions.json.gz").read_bytes() == snapshot.encode()
    assert outputs(tmp_path)["index-name"] == snapshot.artifact_name
    assert not (action.workdir() / "comment.md").exists()


def test_repeated_peer_indexes_cannot_double_count_functions(index_server, github_env, repo):
    github_env("workflow_dispatch", {}, working_directory=str(repo.root), base="HEAD",
               repository_indexes="org/app@main\n\norg/app@main", comment="false", judge="none")
    assert action.main(["run"], transport=index_server[3]) == 2


@pytest.mark.parametrize("mode,spec", [("detect", "org/app@main"), ("judge", "org/app@main"), ("single", "org/app")])
def test_action_rejects_peer_indexes_in_untrusted_modes_and_malformed_specs(github_env, repo, mode, spec):
    github_env("workflow_dispatch", {}, mode=mode, working_directory=str(repo.root), repository_indexes=spec)
    assert action.main(["run"]) == 2


@pytest.mark.parametrize("path", ["/repos/org/app/actions/artifacts", "/repos/org/app/actions/artifacts/7/zip"])
def test_server_errors_are_not_hidden_as_cache_misses(index_server, path):
    index_server[1][path] = lambda _: httpx.Response(500)
    with pytest.raises(httpx.HTTPStatusError):
        fetch(index_server)


def test_artifact_with_unexpected_members_is_rebuilt(index_server):
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w") as output:
        output.writestr("functions.json.gz", index_server[0].encode())
        output.writestr("unexpected", b"no")
    index_server[1]["/repos/org/app/actions/artifacts/7/zip"] = zipped.getvalue()
    assert "fallback" in fetch(index_server).source


def test_oversized_download_is_rejected(index_server, monkeypatch):
    monkeypatch.setattr("dry_lint.index_github.MAX_INDEX_BYTES", 1)
    with pytest.raises(ValueError, match="size limit"):
        fetch(index_server)


def test_missing_ref_is_rejected_before_network_access(index_server):
    client = IndexClient("secret", transport=index_server[3])
    try:
        with pytest.raises(ValueError, match="trusted ref"):
            client.fetch("org/app", "", Settings())
    finally:
        client.close()
    assert not index_server[2]


def test_unsafe_tree_paths_are_rejected(index_server):
    responses = index_server[1]
    responses["/repos/org/app/actions/artifacts"]["artifacts"] = []
    responses["/repos/org/app/git/trees/tree"]["tree"][0]["path"] = "../outside.py"
    with pytest.raises(ValueError, match="Unsafe"):
        fetch(index_server)


@pytest.mark.parametrize("problem", ["oversized", "encoding", "digest"])
def test_archive_and_blob_recovery_are_bounded_and_verified(index_server, monkeypatch, problem):
    import tarfile
    snapshot, responses, _, _ = index_server
    responses["/repos/org/app/actions/artifacts"]["artifacts"] = []
    expected = responses["/repos/org/app/git/trees/tree"]["tree"][0]
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as output:
        if problem == "oversized":
            member = tarfile.TarInfo("app/" + expected["path"])
            member.size = 20000
            output.addfile(member, io.BytesIO(b"a" * member.size))
            monkeypatch.setattr("dry_lint.index_github.MAX_INDEX_BYTES", 10000)
    responses[f"/repos/org/app/tarball/{snapshot.commit}"] = archive.getvalue()
    blob = responses[f"/repos/org/app/git/blobs/{expected['sha']}"]
    if problem == "encoding":
        blob["encoding"] = "none"
    elif problem == "digest":
        blob["content"] = base64.b64encode(b"wrong").decode()
    with pytest.raises(ValueError):
        fetch(index_server)
