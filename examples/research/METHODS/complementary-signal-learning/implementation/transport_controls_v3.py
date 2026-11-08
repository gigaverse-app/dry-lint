# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E402, F401, F841, I001
"""Add actual retained funded controls to canonical exports, never fake displacements."""

from _recovery_paths import recovery_path
import pathlib, json, hashlib, sqlite3, collections, sys

sys.dont_write_bytecode = True
BASE = pathlib.Path(recovery_path("jobs/encoder-corpus-evaluation/.lab-results"))
sys.path.insert(0, str(BASE))
import native_harness as nh
from common import jl, write, sha, digest
from dry_lint.models import Candidate


def ref(p):
    return {"path": str(pathlib.Path(p).resolve()), "sha256": sha(p), "bytes": pathlib.Path(p).stat().st_size}


def canonical(c):
    return digest(json.dumps(c.model_dump(mode="json"), sort_keys=True, ensure_ascii=True, allow_nan=False))


def add_retained(out, campaigns, panel, frontier_packets):
    folder = out / "handoff"
    queue = jl(folder / "queue.jsonl")
    admissions = jl(folder / "admissions.jsonl")
    normal = {r["id"]: r for r in admissions}
    assert len(normal) == len(admissions)
    native_manifest = json.loads((folder / "campaign-admissions.json").read_text())
    native = jl(folder / "native-occurrences.jsonl")
    rendered = jl(folder / "rendered-prompts.jsonl")
    proof = {(r["id"], r["source_sha256"]): r for r in jl(panel["source_proof_path"])}
    existing_ids = {r["id"] for r in queue}
    frontier_bodies = {
        digest(f["code"]) for r in frontier_packets for f in [r["candidate"]["new"], r["candidate"]["existing"]]
    }
    options = []
    for camp in campaigns:
        orig = camp["native"]["minilm_stack"]
        bykey = {
            Candidate.model_validate(raw).key: Candidate.model_validate(raw) for raw in camp["arms"]["minilm_stack"]
        }
        campaign = panel["cohort_id"] + ":" + str(camp["query_positions"])
        extras = [a for a in camp["arms"] if a.startswith("fusion_")]
        retained = set.intersection(
            *[{e["key"] for e in camp["native"][arm]["events"] if e["admitted"]} for arm in extras]
        )
        for event in orig["events"]:
            c = bykey[event["key"]]
            aid = digest(campaign + "minilm_stack" + c.key)
            if not event["admitted"] or c.key not in retained or not normal[aid]["admitted"] or c.filtered:
                continue
            qid = "ENC-" + canonical(c)[:20]
            if qid in existing_ids:
                continue
            options.append((digest(c.key + panel["revision"]), camp, c, event, aid, qid))
    if not options:
        return {"controls": 0, "reason": "No native-and-normal funded retained control in selected campaigns"}
    _, camp, c, event, aid, qid = min(options, key=lambda x: x[0])
    orig = camp["native"]["minilm_stack"]
    eps = []
    for f in [c.new, c.existing]:
        p = proof[f.qualname, digest(f.code)]
        assert p["matching_native_symbols"] == 1 and (f.line, f.end_line) == (p["line"], p["end_line"])
        assert sha(p["source_file"]) == p["file_sha256"]
        eps.append(
            {
                "path": f.path,
                "source_id": f.qualname,
                "line": f.line,
                "end_line": f.end_line,
                "body_sha256": digest(f.code),
                "file_sha256": p["file_sha256"],
                "git_blob_sha1": p["git_blob_sha1"],
                "revision": panel["revision"],
            }
        )
    queue.append(
        {
            "id": qid,
            "repository": panel["repository"],
            "revision": panel["revision"],
            "role": "control",
            "purpose": "deployment_exposure",
            "candidate": c.model_dump(mode="json"),
            "background_proof": {"path": panel["background_path"], "sha256": panel["background_sha256"]},
            "source_proofs": eps,
            "admission_ids": [aid],
        }
    )
    db = folder / ("retained-native-" + digest(orig["database"])[:20] + ".sqlite")
    with (
        sqlite3.connect(pathlib.Path(orig["database"]).resolve().as_uri() + "?mode=ro", uri=True) as src,
        sqlite3.connect(db) as dst,
    ):
        src.backup(dst)
    entry = {
        "id": qid,
        "attempt_index": event["attempt_index"],
        "candidate_sha256": canonical(c),
        "native_held_usd": event["native_held_usd"],
        "normal_estimate_usd": event["normal_estimate_usd"],
        "database": ref(db),
        "run": orig["run"],
        "settings": orig["settings"],
    }
    native_manifest["admissions"].append(entry)
    native.append(entry)
    rendered.append(
        {
            "id": qid,
            "judge": nh.JUDGE.name,
            "model": nh.JUDGE.model,
            "prompt_version": nh.JUDGE.version,
            "max_output_tokens": 2048,
            "rendered_input": nh.JUDGE.input_text(c),
            "rendered_input_sha256": digest(nh.JUDGE.input_text(c)),
            "candidate_sha256": canonical(c),
            "answer": None,
        }
    )
    write(folder / "queue.jsonl", queue)
    write(folder / "campaign-admissions.json", native_manifest)
    write(folder / "native-occurrences.jsonl", native)
    write(folder / "rendered-prompts.jsonl", rendered)
    manifest = json.loads((folder / "HANDOFF.json").read_text())
    manifest.update(
        queue=ref(folder / "queue.jsonl"),
        campaign_admissions=ref(folder / "campaign-admissions.json"),
        selection="Frozen8-casefrontier membership plus one actually retained native-and-normal-funded control per available repository/revision. No source outcome, length or agreement gate on controls.",
        question="Does the new funded frontier add useful independent operations while preserving original admitted work? Retained controls are exposures, not accepted negative labels.",
    )
    write(folder / "HANDOFF.json", manifest)
    return {
        "controls": 1,
        "id": qid,
        "opaque_control_id": "retained-" + digest(c.key + panel["revision"])[:16],
        "role": "retained baseline exposure; may share a query/family with frontier; no independence or negative label asserted",
        "repository": panel["repository"],
        "revision": panel["revision"],
        "key": c.key,
        "normal_admission_id": aid,
    }
