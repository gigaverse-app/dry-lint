# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, F401, F403, F405, I001
from policy_common import *
import re, collections


def export_source_only(queue, out):
    out = pathlib.Path(out).resolve()
    assert out.is_relative_to(H.resolve())
    assert not out.exists()
    out.mkdir()
    files = out / "files"
    files.mkdir()
    panels = [
        r["source"]
        for r in json.loads((B / "BANK-MANIFEST.json").read_text())["backgrounds"]
        if r["repository"] != "anomalyco/opencode"
    ]
    cache = {}
    packets = []
    copied = {}

    def copy_file(proof):
        path = pathlib.Path(proof["source_file"])
        key = proof["file_sha256"]
        if key not in copied:
            assert sha(path) == key
            target = files / (key + path.suffix + ".txt")
            target.write_bytes(path.read_bytes())
            copied[key] = {"path": str(target), "sha256": key, "git_blob_sha1": proof.get("git_blob_sha1")}
        return copied[key]

    for r in queue:
        p = next(
            p
            for p in panels
            if p["repository"] == r["repository"]
            and p["revision"] == r["revision"]
            and p["background_sha256"] == r["background_proof"]["sha256"]
        )
        cid = p["cohort_id"]
        if cid not in cache:
            fs = jl(p["functions_path"])
            proofs = {(x["id"], x["source_sha256"]): x for x in jl(p["source_proof_path"])}
            cache[cid] = (fs, proofs)
        fs, proofs = cache[cid]
        endpoints = []
        callers = []
        for side in ["new", "existing"]:
            f = r["candidate"][side]
            name = f["path"] + "::" + ((f.get("owner") + ".") if f.get("owner") else "") + f["name"]
            pr = proofs[name, digest(f["code"])]
            full = copy_file(pr)
            endpoints.append(
                {
                    "function": f,
                    "source_id": name,
                    "body_sha256": digest(f["code"]),
                    "file": full,
                    "line": f["line"],
                    "end_line": f["end_line"],
                    "source_proof": {k: pr.get(k) for k in ["git_blob_sha1", "file_sha256", "matching_native_symbols"]},
                }
            )
            pattern = re.compile(r"(?<![\w$])" + re.escape(f["name"]) + r"\s*\(")
            matches = []
            for g in fs:
                if g["code"] == f["code"]:
                    continue
                lines = [
                    g.get("line", 0) + n
                    for n, line in enumerate(g["code"].splitlines())
                    if pattern.search(line)
                    and not re.search(r"\b(?:def|function)\s+" + re.escape(f["name"]) + r"\s*\(", line)
                ]
                if lines:
                    matches.append((g, lines))
            matches.sort(key=lambda x: (x[0]["path"], x[0].get("line", 0), x[0]["name"]))
            selected = matches[:8]
            evidence = []
            for g, lines in selected:
                gn = g["path"] + "::" + ((g.get("owner") + ".") if g.get("owner") else "") + g["name"]
                pr = proofs.get((gn, digest(g["code"])))
                if not pr:
                    continue
                evidence.append(
                    {
                        "function": g,
                        "source_id": gn,
                        "body_sha256": digest(g["code"]),
                        "matching_lines": lines,
                        "file": copy_file(pr),
                        "target_resolution": "lexical candidate only; receiver/import resolution unproven",
                    }
                )
            callers.append(
                {
                    "endpoint_source_id": name,
                    "search": "exact symbol followed by call parentheses among functions in this exact background; definitions excluded where syntax recognized",
                    "total_lexical_function_matches": len(matches),
                    "shown_limit": 8,
                    "matches": evidence,
                    "limitation": "Static lexical matches may be unrelated overloads or dynamic calls; no exhaustive caller or ownership claim.",
                }
            )
        packets.append(
            {
                "schema": 1,
                "id": r["id"],
                "repository": r["repository"],
                "revision": r["revision"],
                "endpoints": endpoints,
                "caller_evidence": callers,
                "background_proof": r["background_proof"],
                "review_scope": "Assess whole duplication, a useful bounded independently repeated operation, already-shared ownership, relatedness, tiny convenience, separation, dispute or unknown. Preserve source contracts. No provider outcome supplied.",
            }
        )
    write(out / "questions.jsonl", packets)
    write(
        out / "MANIFEST.json",
        {
            "schema": 1,
            "questions": len(packets),
            "question_file": {"path": str(out / "questions.jsonl"), "sha256": sha(out / "questions.jsonl")},
            "files": list(copied.values()),
            "identity_set_sha256": digest(json.dumps(sorted(r["id"] for r in queue))),
            "selection_information_omitted": [
                "method",
                "role",
                "scores",
                "nomination reasons",
                "expected labels",
                "provider outcomes",
            ],
            "source_boundary": "Exact native function bodies and full source files from frozen producer proofs. Caller evidence is explicitly bounded lexical search.",
            "provider_calls": 0,
        },
    )
    print("SOURCE ONLY READY", out / "questions.jsonl", len(packets), len(copied), "files")
    return packets


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", type=pathlib.Path, default=H / "filtered-v1/queue.jsonl")
    ap.add_argument("--out", type=pathlib.Path, default=H / "source-only-v1")
    a = ap.parse_args()
    export_source_only(jl(a.queue), a.out)


if __name__ == "__main__":
    main()
