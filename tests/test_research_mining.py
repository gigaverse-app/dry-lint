"""Tiny synthetic invariants; no corpus, provider, credential or network dependency."""

import copy
import json
import os
import runpy
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from research_mining import exact_cache  # noqa: E402
from research_mining.audit import audit_queue, source_binding  # noqa: E402
from research_mining.exact_cache import ExactCache, canonical, function_data, sha  # noqa: E402
from research_mining.source import validate_sources  # noqa: E402

from dry_lint.git import git  # noqa: E402
from dry_lint.models import Candidate  # noqa: E402

RAW = b"def transform(value):\n    adjusted = value + 1\n    normalized = adjusted * 2\n    return normalized\n"


@pytest.fixture
def sample(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Synthetic test")
    git(root, "config", "user.email", "test@example.invalid")
    for name in ("one.py", "two.py"):
        (root / name).write_bytes(RAW)
    git(root, "add", ".")
    git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "synthetic functions")
    revision = git(root, "rev-parse", "HEAD")
    cache = ExactCache(tmp_path / "cache")
    functions = [cache.extract("example/synthetic", revision, name, RAW)[0] for name in ("one.py", "two.py")]
    candidate = Candidate(new=functions[0], existing=functions[1], similarity=0.1, comparer="synthetic:1")
    packet = dict(
        id="synthetic-1",
        repository="example/synthetic",
        revision=revision,
        candidate=candidate.model_dump(mode="json"),
        status="disputed",
        related_pairs=["synthetic-2"],
        source_proofs=[dict(source_id=f.qualname, file_sha256=sha(RAW)) for f in functions],
    )
    repositories = {packet["repository"]: root}
    checks = validate_sources(packet, candidate, root, cache)
    binding = source_binding(packet, candidate, checks)
    requests, observations = [], []
    for reviewer, label in (("alpha", "separate"), ("beta", "duplicate")):
        identity = dict(
            binding,
            schema=1,
            kind=reviewer,
            judge="synthetic",
            version="v1",
            model="offline-model",
            prompt_version="p1",
            rendered_input="Synthetic exact prompt",
            max_output_tokens=100,
            request_options={"temperature": 0},
        )
        key = sha(canonical(identity))
        requests.append(dict(id=packet["id"], identity=identity, request_key=key))
        observations.append(dict(identity=identity, request_key=key, verdict=dict(label=label, why="Synthetic reason")))
    return packet, repositories, cache, requests, observations


def queue(sample, **overrides):
    packet, repositories, cache, requests, observations = sample
    args = dict(
        packets=[packet],
        repositories=repositories,
        cache=cache,
        requests=requests,
        observations=observations,
        reviewers=["alpha", "beta"],
        hints=True,
    )
    args.update(overrides)
    return audit_queue(**args)


@pytest.mark.parametrize(
    "path,raw",
    [
        ("a.py", RAW),
        ("a.ts", b"function f(x: number) { return x + 1; }\n"),
        ("a.tsx", b"function View() { return <span>ok</span>; }\n"),
    ],
)
def test_cold_warm_equality_including_excluded_fields(tmp_path, path, raw):
    first = ExactCache(tmp_path / "cache")
    cold = first.extract("example/repo", "a" * 40, path, raw)
    second = ExactCache(first.directory)
    warm = second.extract("example/repo", "a" * 40, path, raw)
    assert [function_data(f) for f in cold] == [function_data(f) for f in warm]
    assert (first.parses, second.parses, second.hits) == (1, 0, 1)
    cold[0].tokens.append("caller mutation")
    assert "caller mutation" not in second.extract("example/repo", "a" * 40, path, raw)[0].tokens


def test_pin_source_extractor_runtime_and_code_invalidation(tmp_path, monkeypatch):
    directory = tmp_path / "cache"
    cache = ExactCache(directory)
    args = ("example/repo", "a" * 40, "a.py", RAW)
    cache.extract(*args)
    cache.extract("example/repo", "b" * 40, "a.py", RAW)
    cache.extract("example/repo", "a" * 40, "a.py", RAW.replace(b"+ 1", b"+ 2"))
    cache.extract("example/other", "a" * 40, "a.py", RAW)
    cache.extract("example/repo", "a" * 40, "b.py", RAW)
    assert cache.parses == 5
    original = exact_cache.extraction_contract()
    for field in ("code", "tool", "runtime", "packages", "extractors"):
        changed = copy.deepcopy(original)
        changed[field] = ["changed"]
        with monkeypatch.context() as patch:
            patch.setattr(exact_cache, "extraction_contract", lambda contract=changed: contract)
            fresh = ExactCache(directory)
            fresh.extract(*args)
            assert (fresh.parses, fresh.hits) == (1, 0)
    with pytest.raises(ValueError, match="immutable"):
        cache.extract("example/repo", "main", "a.py", RAW)
    with pytest.raises(ValueError, match="Unsupported"):
        cache.extract("example/repo", "a" * 40, "a.js", RAW)


def test_contract_tracks_real_code_parser_and_extractor_changes(tmp_path, monkeypatch):
    code = tmp_path / "code"
    code.mkdir()
    source = code / "extractor.py"
    source.write_text("v1")
    before = exact_cache.implementation_digest(code)
    source.write_text("v2")
    assert exact_cache.implementation_digest(code) != before
    original = exact_cache.extraction_contract()
    monkeypatch.setattr(exact_cache, "version", lambda _: "changed-parser-version")
    assert exact_cache.extraction_contract() != original
    monkeypatch.setattr(exact_cache.PythonExtractor, "version", "changed-extractor-version")
    assert exact_cache.extraction_contract()["extractors"][0][1] == "changed-extractor-version"


@pytest.mark.parametrize(
    "path,raw",
    [
        ("a.py", RAW + b"\ndef broken(:\n"),
        ("a.ts", b"function good() { return 1; }\nfunction broken( {"),
    ],
)
def test_invalid_trailing_source_never_cached(tmp_path, path, raw):
    cache = ExactCache(tmp_path)
    with pytest.raises(ValueError, match="completely scan"):
        cache.extract("example/repo", "a" * 40, path, raw)
    assert not list(tmp_path.glob("*.json"))


@pytest.mark.parametrize("damage", ["truncated", "shape", "identity", "checksum", "model", "missing_tokens"])
def test_corrupted_cache_recomputed_safely(tmp_path, damage):
    cache = ExactCache(tmp_path)
    args = ("example/repo", "a" * 40, "a.py", RAW)
    expected = [function_data(f) for f in cache.extract(*args)]
    target = next(tmp_path.glob("*.json"))
    obj = json.loads(target.read_bytes())
    if damage == "truncated":
        target.write_text("{")
    elif damage == "shape":
        target.write_text("null")
    else:
        if damage == "identity":
            obj["identity"]["revision"] = "b" * 40
        elif damage == "checksum":
            obj["functions"][0]["code"] = "damaged"
        else:
            if damage == "model":
                obj["functions"][0]["line"] = "not a line"
            else:
                del obj["functions"][0]["tokens"]
            obj["functions_sha256"] = sha(canonical(obj["functions"]))
        target.write_bytes(canonical(obj))
    assert [function_data(f) for f in cache.extract(*args)] == expected
    assert cache.corruptions == 1
    assert [function_data(f) for f in cache.extract(*args)] == expected
    assert cache.hits == 1


def test_concurrent_cold_writers(tmp_path, monkeypatch):
    gate = Barrier(4)
    original = exact_cache.PythonExtractor.validate_source

    def synchronized(ex, path, source):
        gate.wait(timeout=10)
        return original(ex, path, source)

    def extract(_):
        return [function_data(f) for f in ExactCache(tmp_path).extract("example/repo", "a" * 40, "a.py", RAW)]

    monkeypatch.setattr(exact_cache.PythonExtractor, "validate_source", synchronized)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(extract, range(4)))
    assert all(result == results[0] for result in results)
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert not list(tmp_path.glob("*.tmp"))
    assert extract(0) == results[0]  # warm read bypasses synchronized parsing


def test_concurrent_evidence_publication_never_replaces_winner(tmp_path, monkeypatch):
    gate = Barrier(2)
    original = exact_cache.os.link

    def synchronized(source, target):
        gate.wait(timeout=10)
        return original(source, target)

    monkeypatch.setattr(exact_cache.os, "link", synchronized)
    target = tmp_path / "evidence.json"

    def publish(value):
        try:
            exact_cache.atomic_json(target, value, exclusive=True)
            return True
        except FileExistsError:
            return False

    values = [{"writer": "one", "rows": list(range(100))}, {"writer": "two", "rows": list(range(100, 200))}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = list(pool.map(publish, values))
    assert winners.count(True) == 1
    assert json.loads(target.read_bytes()) == values[winners.index(True)]
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_atomic_replacement_preserves_previous_evidence(tmp_path, monkeypatch):
    target = tmp_path / "cache.json"
    exact_cache.atomic_json(target, {"old": True})

    def fail_replace(*_):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(exact_cache.os, "replace", fail_replace)
    with pytest.raises(OSError, match="publication failure"):
        exact_cache.atomic_json(target, {"new": True})
    assert json.loads(target.read_bytes()) == {"old": True}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("packet", [None, 7, "scalar", [], {"id": []}, {"id": {}}, {"id": None}, {"id": ""}, {}])
def test_malformed_packet_envelopes_retained(sample, packet):
    result = queue(sample, packets=[packet, sample[0]])
    assert len(result["rows"]) == 2
    row = result["rows"][0]
    assert row["packet"] == packet and row["source_validation"] == "failed" and row["source_error"]
    assert not row["observations_complete"] and not row["navigation_hints"]
    assert result["rows"][1]["source_validation"] == "passed"


@pytest.mark.parametrize("proofs", [None, "proof", {}, [None], [7], ["proof"], [{}]])
def test_malformed_proof_lists_retained(sample, proofs):
    packet = dict(sample[0], source_proofs=proofs)
    row = queue(sample, packets=[packet])["rows"][0]
    assert row["packet"] == packet and row["source_validation"] == "failed" and row["source_error"]
    assert not row["observations"] and not row["navigation_hints"]


@pytest.mark.parametrize("status", ["unknown", "disputed", "separate", "duplicate", "drifted", "deferred", "filtered"])
def test_every_state_preserved_with_disagreement_and_navigation(sample, status):
    sample[0]["status"] = status
    sample[0]["accepted_gold"] = status == "separate"  # retain input claim, never newly accept it
    result = queue(sample)
    row = result["rows"][0]
    assert row["packet"] == sample[0]
    assert row["observations_complete"]
    assert row["disagreement_kind"] == "separate_vs_positive"
    assert row["audit_status"] == "unknown" and row["gold_label"] is None and not row["accepted_gold"]
    assert result["accepted_gold"] == result["provider_calls"] == 0
    assert row["navigation_hints"]
    for span in row["navigation_hints"][0]["spans"]:
        assert 1 <= span["start_line"] <= span["end_line"] <= len(RAW.splitlines())
    assert all(
        slot["operation_start"] is None and slot["owner_resolution"] is None for slot in row["operation_regions"]
    )


@pytest.mark.parametrize(
    "field",
    [
        "schema",
        "kind",
        "judge",
        "revision",
        "candidate_sha256",
        "source_evidence",
        "context_hash",
        "source_files",
        "rendered_input",
        "model",
        "version",
        "prompt_version",
        "max_output_tokens",
        "request_options",
    ],
)
def test_packet_match_alone_never_reuses_changed_request(sample, field):
    requests = copy.deepcopy(sample[3])
    identity = requests[0]["identity"]
    identity[field] = (
        101 if field == "max_output_tokens" else {"changed": True} if field == "request_options" else "changed"
    )
    requests[0]["request_key"] = sha(canonical(identity))
    row = queue(sample, requests=requests)["rows"][0]
    assert row["observations"][0]["state"] == "unknown"
    assert not row["observations_complete"]
    assert row["packet"]["status"] == "disputed"


def test_missing_duplicate_and_error_observations_remain_unknown(sample):
    requests, observations = sample[3:]
    cases = [
        dict(requests=[]),
        dict(observations=[]),
        dict(observations=observations[:1]),
        dict(requests=requests + [copy.deepcopy(requests[0])]),
        dict(observations=observations + [copy.deepcopy(observations[0])]),
        dict(observations=[dict(observations[0], error="recorded failure"), observations[1]]),
        dict(observations=[dict(observations[0], verdict=None), observations[1]]),
        dict(observations=[dict(observations[0], status="unknown"), observations[1]]),
    ]
    for case in cases:
        result = queue(sample, **case)
        row = result["rows"][0]
        assert not row["observations_complete"]
        assert row["priority"] == 3 and row["audit_status"] == "unknown"
        assert result["observation_records"] == case.get("observations", observations)
        assert result["request_manifest"] == case.get("requests", requests)


@pytest.mark.parametrize("field,value", [("model", ""), ("max_output_tokens", True), ("max_output_tokens", 0)])
def test_incomplete_expected_requests_stay_unknown(sample, field, value):
    requests = copy.deepcopy(sample[3])
    requests[0]["identity"][field] = value
    requests[0]["request_key"] = sha(canonical(requests[0]["identity"]))
    row = queue(sample, requests=requests)["rows"][0]
    assert row["observations"][0]["reason"] == "request_contract_mismatch"


def test_reviewers_must_be_explicit_and_distinct(sample):
    for reviewers in ([], ["alpha", "alpha"], [""]):
        with pytest.raises(ValueError, match="distinct expected reviewers"):
            queue(sample, reviewers=reviewers)


def test_unavailable_pinned_source_and_no_lexical_match_stay_retained(sample):
    packet = dict(sample[0], revision="0" * 40)
    row = queue(sample, packets=[packet])["rows"][0]
    assert row["source_validation"] == "failed" and row["packet"] == packet
    packet = copy.deepcopy(sample[0])
    root = sample[1][packet["repository"]]
    raw = b"def transform(value):\n    return value - 5\n"
    (root / "two.py").write_bytes(raw)
    git(root, "add", ".")
    git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "distinct synthetic function")
    packet["revision"] = git(root, "rev-parse", "HEAD")
    native = sample[2].extract(packet["repository"], packet["revision"], "two.py", raw)[0]
    packet["candidate"]["existing"] = native.model_dump(mode="json")
    packet["source_proofs"][1]["file_sha256"] = sha(raw)
    row = queue(sample, packets=[packet])["rows"][0]
    assert row["source_validation"] == "passed" and not row["navigation_hints"]
    assert row["audit_status"] == "unknown" and not row["accepted_gold"]


def test_forged_identity_and_duplicate_packet_id(sample):
    observations = copy.deepcopy(sample[4])
    observations[0]["identity"]["version"] = "wrong"  # retains old key
    assert queue(sample, observations=observations)["rows"][0]["observations"][0]["state"] == "unknown"
    rows = queue(sample, packets=[sample[0], copy.deepcopy(sample[0])])["rows"]
    assert len(rows) == 2 and all(r["source_validation"] == "failed" for r in rows)


def test_json_type_changes_are_not_exact_request_matches(sample):
    requests, observations = copy.deepcopy(sample[3]), copy.deepcopy(sample[4])
    requests[0]["identity"]["max_output_tokens"] = 1
    requests[0]["request_key"] = sha(canonical(requests[0]["identity"]))
    observations[0]["request_key"] = requests[0]["request_key"]
    observations[0]["identity"]["max_output_tokens"] = True
    row = queue(sample, requests=requests, observations=observations)["rows"][0]
    assert row["observations"][0]["reason"] == "observation_identity_mismatch"


@pytest.mark.parametrize(
    "labels,kind", [(("separate", "separate"), None), (("drifted", "duplicate"), "positive_subtype")]
)
def test_agreement_and_subtype_never_accept(sample, labels, kind):
    observations = copy.deepcopy(sample[4])
    for observation, label in zip(observations, labels, strict=True):
        observation["verdict"]["label"] = label
    row = queue(sample, observations=observations)["rows"][0]
    assert row["disagreement_kind"] == kind and not row["accepted_gold"]
    assert row["audit_status"] == "unknown"


@pytest.mark.parametrize(
    "damage", ["digest", "body", "coordinates", "structure", "proofs", "analysis", "origin", "pin"]
)
def test_source_checks_fail_closed_on_warm_cache(sample, damage):
    packet = copy.deepcopy(sample[0])
    if damage == "digest":
        packet["source_proofs"][0]["file_sha256"] = "0" * 64
    elif damage == "body":
        packet["candidate"]["new"]["code"] += "\n# changed"
    elif damage == "coordinates":
        packet["candidate"]["new"]["line"] += 1
    elif damage == "structure":
        packet["candidate"]["new"]["hash"] = "wrong"
    elif damage == "proofs":
        packet["source_proofs"].append(packet["source_proofs"][0])
    elif damage == "analysis":
        packet["candidate"]["new"]["analysis"]["version"] = "changed"
    elif damage == "origin":
        packet["candidate"]["new"]["origin"] = dict(repository="example/other", head="a" * 40, base="main")
    else:
        packet["revision"] = "main"
    row = queue(sample, packets=[packet])["rows"][0]
    assert row["source_validation"] == "failed" and row["source_error"]
    assert not row["observations"] and not row["navigation_hints"]
    assert row["packet"] == packet


def test_duplicate_native_id_and_invalid_pinned_tail(sample):
    packet, repositories, *_ = sample
    root = repositories[packet["repository"]]
    for raw in (RAW + RAW, RAW + b"def broken(:\n"):
        (root / "one.py").write_bytes(raw)
        git(root, "add", ".")
        git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "invalid endpoint source")
        damaged = copy.deepcopy(packet)
        damaged["revision"] = git(root, "rev-parse", "HEAD")
        damaged["source_proofs"][0]["file_sha256"] = sha(raw)
        row = queue(sample, packets=[damaged])["rows"][0]
        assert row["source_validation"] == "failed" and not row["observations_complete"]


def test_portable_cli_cold_warm_retains_all_rows(sample, tmp_path):
    packet, repositories, *_ = sample
    packets = [
        dict(packet, id=f"packet-{i}", status=status) for i, status in enumerate(("unknown", "separate", "disputed"))
    ]
    (tmp_path / "packets.jsonl").write_text("".join(json.dumps(p) + "\n" for p in packets))
    (tmp_path / "repositories.json").write_text(json.dumps({packet["repository"]: "source"}))
    # Invoke by module from an unrelated cwd with only caller-supplied import paths.
    env = dict(
        os.environ,
        PYTHONPATH=str(Path(__file__).resolve().parents[1] / "scripts")
        + os.pathsep
        + str(Path(__import__("dry_lint").__file__).resolve().parents[1]),
    )
    run_at = tmp_path / "elsewhere"
    run_at.mkdir()
    results = []
    for name in ("cold", "warm"):
        out = tmp_path / f"{name}.json"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "research_mining",
                "--packets",
                str(tmp_path / "packets.jsonl"),
                "--repositories",
                str(tmp_path / "repositories.json"),
                "--cache",
                str(tmp_path / "cli-cache"),
                "--reviewers",
                "alpha",
                "beta",
                "--hints",
                "--out",
                str(out),
            ],
            cwd=run_at,
            env=env,
            check=True,
            capture_output=True,
        )
        results.append(json.loads(out.read_bytes()))
    assert results[0]["rows"] == results[1]["rows"]
    assert [r["packet"] for r in results[0]["rows"]] == packets
    assert results[0]["cache"]["parses"] == 2 and results[1]["cache"]["parses"] == 0
    assert results[1]["cache"]["hits"] == 6


def test_complete_demo_and_cli_output_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(sys.path))
    directory = tmp_path / "complete-demo"
    monkeypatch.setattr(sys, "argv", ["demo", "--out-dir", str(directory)])
    runpy.run_module("research_mining.demo", run_name="__main__")
    cold = json.loads((directory / "cold.json").read_bytes())
    warm = json.loads((directory / "warm.json").read_bytes())
    assert cold["rows"] == warm["rows"] and warm["rows"][0]["observations_complete"]
    assert len(cold["request_manifest"]) == len(cold["observation_records"]) == 2
    out = directory / "cli-output.json"
    args = [
        "research_mining",
        "--packets",
        str(directory / "packets.jsonl"),
        "--repositories",
        str(directory / "repositories.json"),
        "--cache",
        str(directory / "cache"),
        "--reviewers",
        "alpha",
        "beta",
        "--out",
        str(out),
    ]
    monkeypatch.setattr(sys, "argv", args)
    runpy.run_module("research_mining", run_name="__main__")
    original = out.read_bytes()
    with pytest.raises(SystemExit) as error:
        runpy.run_module("research_mining", run_name="__main__")
    assert error.value.code == 2 and out.read_bytes() == original
