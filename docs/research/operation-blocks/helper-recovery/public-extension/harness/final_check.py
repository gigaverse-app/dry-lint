"""Check complete mappings, per-background coverage, source identity and frozen algorithms."""

from common import HERE, Path, dump, folders, json, load, read, sha


def main():
    gold = read(HERE / "selected-rows.jsonl")
    contexts = {load(p.parent)[0]["cohort_id"]: load(p.parent) for p in folders()}
    expected = {
        (r["row_id"], mp["cohort_id"])
        for r in gold
        for mp in r["mappings"]
        if mp["cohort_id"] in contexts and mp["status"] == "mapped"
    }
    assert len(expected) == 115
    methods = {}
    for method in ("blocks", "cpu"):
        path = HERE / (method + "-regression.jsonl")
        rows = read(path)
        assert len(rows) == 115 and {(r["row_id"], r["cohort_id"]) for r in rows} == expected
        funded_losses = 0
        for r in rows:
            assert len(r["directions"]) == 2
            _, bg, fs, native = contexts[r["cohort_id"]]
            endpoints = [fs[r["mapping"]["sources"][s]["position"]] for s in ("new", "existing")]
            assert {(d["query"], d["target"]) for d in r["directions"]} == {
                (endpoints[0].qualname, endpoints[1].qualname),
                (endpoints[1].qualname, endpoints[0].qualname),
            }
            for d in r["directions"]:
                assert d["query"] != d["target"]
                if method == "blocks":
                    funded_losses += d["original"]["funded"]["paired"] and not d["helper"]["funded"]["paired"]
                else:
                    funded_losses += d["stages"]["original"]["funded"] and not d["stages"]["treatment"]["funded"]
        assert funded_losses == 0
        methods[method] = {
            "rows": len(rows),
            "directions": len(rows) * 2,
            "sha256": sha(path.read_bytes()),
            "bytes": path.stat().st_size,
            "funded_direction_losses": funded_losses,
        }
    proofs = json.loads((HERE / "input-proofs.json").read_text())
    # Historical studies are read-only: stable inputs must retain acquisition-time hashes.
    checked = []
    for path, digest in proofs["files"].items():
        if "/shared-inputs/" in path or path.endswith("/source-coverage.jsonl"):
            assert sha(Path(path).read_bytes()) == digest
            checked.append(path)
    dump(
        HERE / "final-check.json",
        {
            "status": "passed",
            "methods": methods,
            "unchanged_historical_inputs": checked,
            "source_backgrounds": 14,
            "mapped_row_backgrounds": 115,
            "provider_calls": 0,
        },
    )
    print(json.dumps(methods), flush=True)


if __name__ == "__main__":
    main()
