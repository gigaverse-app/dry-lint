"""Standard-library replay of frozen post-retrieval questions and recorded answers. No network."""

import argparse
import ast
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()


def read(path):
    return json.loads(path.read_text())


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def constant(path, name):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(name)


def render(candidate, template):
    names = {}
    for side in ("new", "existing"):
        f = candidate[side]
        origin = f.get("origin") or {}
        prefix = (origin["repository"] + "/") if origin.get("repository") else ""
        names[side] = prefix + f["path"] + "::" + ((f["owner"] + ".") if f.get("owner") else "") + f["name"]
    for key, value in [
        ("new_name", names["new"]),
        ("new_code", candidate["new"]["code"]),
        ("existing_name", names["existing"]),
        ("existing_code", candidate["existing"]["code"]),
        ("new_context", candidate["new"].get("context", "")),
        ("existing_context", candidate["existing"].get("context", "")),
    ]:
        template = template.replace("<<" + key + ">>", value)
    if candidate.get("policies"):
        template += (
            "\nADOPTER POLICIES (configured rules and declared roles; verify applicability against source):\n"
            + json.dumps(candidate["policies"], ensure_ascii=True)
        )
    return template


def answer(text):
    for match in re.finditer(r"\{", text):
        try:
            value, _ = json.JSONDecoder().raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "label" in value:
            return dict(
                label=value["label"],
                score=float(value.get("score", 1)),
                owner=value.get("owner", ""),
                why=value.get("why", ""),
                behaves_differently=float(value.get("behaves_differently", 0)),
            )
    raise ValueError("No JSON verdict")


def reported(verdict):
    return verdict is not None and verdict["label"] != "separate" and verdict["score"] >= 0.5


def replay(root):
    manifest = read(root / "MANIFEST.json")
    for name, digest in manifest["files"].items():
        assert sha((root / name).read_bytes()) == digest, name
    for run, script in [
        ("initial24-v3", "run-grounded-diagnostic-initial-v3.py"),
        ("remaining31-v4", "run-grounded-diagnostic.py"),
    ]:
        ready = read(root / "root-provenance" / run / "ROOT-READY.json")
        binding = next(r for r in ready["artifact_refs"] if r["path"].endswith("/run-grounded-diagnostic.py"))
        assert sha((root / "root-provenance" / script).read_bytes()) == binding["sha256"]
    index = read(root / "artifact-index.json")
    ev = root / "evidence"
    requests = rows(ev / "queue.jsonl") + rows(ev / "extension-queue.jsonl")
    baselines = {
        r["id"]: r for file in ["baseline-observations.jsonl", "extension-baselines.jsonl"] for r in rows(ev / file)
    }
    groups = {r["id"]: r["split"] for r in rows(ev / "review-sidecar.jsonl")}
    baseline_template = constant(ev / "runtime/src/dry_lint/judges/command.py", "OPERATIONS_PROMPT")
    grounding = constant(ev / "policy.py", "GROUNDING")
    treatment_template = baseline_template.replace("# NEW: <<new_name>>", grounding + "# NEW: <<new_name>>", 1)
    no_send = {r["request_key"] for r in read(ev / "no-send-proof/ROOT-RECONCILIATION.json")["events"]}
    result = []
    paid = 0
    retained_holds = 0
    for request in requests:
        ident = request["identity"]
        candidate = request["packet"]["candidate"]
        old = baselines[request["id"]]
        assert sha(canonical(ident)) == request["request_key"]
        assert sha(canonical(candidate)) == ident["candidate_sha256"]
        assert sha(treatment_template.encode()) == ident["template_sha256"]
        assert render(candidate, treatment_template) == ident["rendered_input"]
        assert render(candidate, baseline_template) == old["identity"]["rendered_input"]
        assert (ident["model"], ident["max_output_tokens"]) == ("claude-haiku-5-5", 2048)
        assert request["wire_body"] == dict(
            model=ident["model"], max_tokens=2048, messages=[dict(role="user", content=ident["rendered_input"])]
        )
        assert ident["request_options"] == dict(
            prompt_policy="shared-operations-grounded-claim-v1",
            effort=None,
            max_retries=0,
            retry_malformed=False,
            server_side_fallbacks="disabled",
        )
        for proof in request["source_snapshots"]:
            raw = (ev / proof["snapshot"]).read_bytes()
            f = candidate[proof["side"]]
            assert sha(raw) == proof["file_sha256"] and sha(f["code"].encode()) == proof["body_sha256"]
            assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == proof["git_blob_sha1"]
            assert (f["line"], f["end_line"]) == (proof["line"], proof["end_line"])
        archived = read(root / index["baseline_observations"][request["id"]]["record"])
        direct = read(root / index["baseline_observations"][request["id"]]["direct"])
        assert archived["identity"] == old["identity"] and archived["verdict"] == old["verdict"]
        assert (
            direct["identity"]["rendered_input"] == old["identity"]["rendered_input"]
            and direct["verdict"] == old["verdict"]
        )
        direct_response = json.loads(direct["raw_responses"][0]["body"])
        direct_text = "".join(block["text"] for block in direct_response["content"] if block["type"] == "text")
        assert direct_text == old["final_responses"][0]["text"]
        b = answer(direct_text)
        assert all(old["verdict"][k] == v for k, v in b.items())
        receipt = read(root / index["new_observations"][request["request_key"]])
        assert receipt["identity"] == ident
        new = None
        kind = "answered"
        if request["request_key"] in no_send:
            assert receipt["raw_responses"] == [] and receipt["usage"] is None and receipt["usd"] is None
            kind = "local-unexecuted"
            retained_holds += request["reservation_usd"]
        else:
            assert len(receipt["raw_responses"]) == 1
            raw = receipt["raw_responses"][0]
            body = json.loads(raw["body"])
            assert body["model"] == ident["model"]
            usage = body["usage"]
            usd = (
                usage["input_tokens"] * 0.1
                + usage["output_tokens"] * 0.5
                + (usage.get("cache_creation_input_tokens") or 0) * 0.125
                + (usage.get("cache_read_input_tokens") or 0) * 0.01
            ) / 1e6
            assert math.isclose(usd, receipt["usd"], abs_tol=1e-12)
            paid += usd
            text = "".join(b["text"] for b in body["content"] if b["type"] == "text")
            try:
                new = answer(text)
            except ValueError:
                assert (
                    receipt["error"] == "ValueError"
                    and body["stop_reason"] == "max_tokens"
                    and usage["output_tokens"] == 2048
                )
                kind = "provider-unknown"
            else:
                assert not receipt["error"] and all(receipt["verdict"][k] == v for k, v in new.items())
        effect = (
            kind
            if kind == "local-unexecuted"
            else "unknown"
            if new is None
            else "retained"
            if reported(b) and reported(new)
            else "suppressed"
            if reported(b)
            else "added"
            if reported(new)
            else "neither"
        )
        result.append(
            dict(
                id=request["id"],
                split=groups.get(request["id"], "development"),
                report_effect=effect,
                transport_status=kind,
                before_reported=reported(b),
                after_reported=reported(new) if new else None,
            )
        )
    expected = rows(ev / "comparison-r1/pairs.jsonl")
    for got, want in zip(result, expected, strict=True):
        for key in ["id", "split", "report_effect", "before_reported", "after_reported"]:
            assert got[key] == want[key], (got["id"], key)
    summary = dict(
        questions=len(result),
        parsed=sum(r["transport_status"] == "answered" for r in result),
        provider_unknown=sum(r["transport_status"] == "provider-unknown" for r in result),
        local_unexecuted=sum(r["transport_status"] == "local-unexecuted" for r in result),
        settled_usd=round(paid, 10),
        retained_no_send_holds_usd=round(retained_holds, 10),
        groups={
            g: dict(Counter(r["report_effect"] for r in result if r["split"] == g))
            for g in sorted({r["split"] for r in result})
        },
        usefulness="pending independent labels",
        product_improvement=False,
    )
    assert math.isclose(paid, read(ev / "comparison-r1/summary.json")["known_settled_usd"], abs_tol=1e-12)
    labels_path = root / "labels.jsonl"
    if labels_path.exists():
        labels = rows(labels_path)
        by_id = {r["opaque_id"]: r for r in labels}
        mapping = rows(ev / "blind-review-batch1/coordinator-map.jsonl")
        packets = {r["opaque_id"]: r for r in rows(ev / "blind-review-batch1/packets.jsonl")}
        assert len(labels) == len(by_id) == len(mapping) == 54 and set(by_id) == set(packets)
        paired = {}
        for m in mapping:
            label = by_id[m["opaque_id"]]
            assert label["explanation_sha256"] == sha(packets[m["opaque_id"]]["explanation"].encode())
            assert label["source_truth_changed"] is False
            for anchor in (
                label["evidence"]["anchors"]
                + label["evidence"]["helpers"]
                + [a for op in label["claimed_operations"] for a in op["source_anchors"]]
            ):
                raw = (ev / "source-files" / Path(anchor["snapshot"]).name).read_bytes()
                assert sha(raw) == anchor["file_sha256"]
                assert (
                    sha(
                        "".join(
                            raw.decode().splitlines(keepends=True)[anchor["line"] - 1 : anchor["end_line"]]
                        ).encode()
                    )
                    == anchor["slice_sha256"]
                )
            paired.setdefault(m["case_id"], {})[m["arm"]] = label
        flags = {r["id"]: r for r in result}
        counts = {}
        for group in ["development", "source-family-evaluation-controls", "all"]:
            ids = [i for i in paired if group == "all" or flags[i]["split"] == group]
            counts[group] = {}
            for arm, flag in [("baseline", "before_reported"), ("grounded", "after_reported")]:
                counts[group][arm] = dict(
                    comparable_pairs=len(ids),
                    reported=sum(flags[i][flag] for i in ids),
                    strict_useful_reports=sum(
                        flags[i][flag] and paired[i][arm]["conservative_useful_credit"] for i in ids
                    ),
                    statuses=dict(Counter(paired[i][arm]["status"] for i in ids)),
                )
        root_join = read(root / "root-provenance/GROUNDED-CLAIM-ROOT-JOIN.json")
        assert counts == root_join["counts"]
        deltas = []
        for i, arms in paired.items():
            before = flags[i]["before_reported"] and arms["baseline"]["conservative_useful_credit"]
            after = flags[i]["after_reported"] and arms["grounded"]["conservative_useful_credit"]
            if before != after:
                deltas.append(dict(case_id=i, before=before, after=after, split=flags[i]["split"]))
        assert sorted(deltas, key=lambda r: r["case_id"]) == sorted(
            root_join["strict_useful_deltas"], key=lambda r: r["case_id"]
        )
        summary["claims"] = dict(
            groups={
                g: [counts[g]["baseline"]["strict_useful_reports"], counts[g]["grounded"]["strict_useful_reports"]]
                for g in counts
            },
            strict_gains=sum(r["after"] for r in deltas),
            strict_losses=sum(r["before"] for r in deltas),
            mixed_claim_repairs=sum(
                a["baseline"]["status"] == "mixed" and a["grounded"]["status"] == "useful" for a in paired.values()
            ),
            new_supported_claim=sum(
                flags[i]["after_reported"]
                and a["baseline"]["status"] == "nonuseful"
                and a["grounded"]["conservative_useful_credit"]
                for i, a in paired.items()
            ),
        )
        summary["usefulness"] = (
            "Specific explanation-precision benefit; two repairs of already useful components and one newly claimed authorization rule, with one useful claim lost to disputed. Not three new pair/family discoveries or campaign promotion."
        )
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=BASE)
    a = p.parse_args()
    print(json.dumps(replay(a.root.resolve()), indent=2, sort_keys=True))
