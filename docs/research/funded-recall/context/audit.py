"""Recompute the published context results without providers or third-party packages."""

import csv
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    for line in (root / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
    evidence = json.loads((root / "evidence.json").read_text())
    receipts = [json.loads(line) for line in (root / "request-hash-receipts.jsonl").read_text().splitlines()]
    assert len(receipts) == len({r["execution_id"] for r in receipts}) == 80
    assert all(r["ledger_settled"] for r in receipts)
    paid = defaultdict(Decimal)
    for receipt in receipts:
        paid[receipt["round"]] += Decimal(str(receipt["cost_usd"]))
    assert paid["round1"] == Decimal(str(evidence["round1_new_usd"]))
    assert paid["round2"] == Decimal(str(evidence["round2_new_usd"]))
    assert all(cost >= Decimal(".20") for cost in paid.values())
    with (root / "paired-results.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len({(r["id"], r["kind"]) for r in rows}) == 32
    results = {}
    for kind in ("jev", "claude"):
        selected = [r for r in rows if r["kind"] == kind]
        assert len(selected) == 16
        counts = Counter({field: sum(r[field] == "True" for r in selected)
                          for field in ("recovery", "lost_positive", "new_false_report")})
        expected = evidence["round2"]["effects"][kind]
        assert counts["recovery"] == expected["recoveries"]
        assert counts["lost_positive"] == expected["lost_positives"]
        assert counts["new_false_report"] == expected["new_false_reports"]
        results[kind] = dict(counts)
    print(json.dumps({"paid_calls": len(receipts), "paid_usd": {k: str(v) for k, v in paid.items()},
                      "round2_paired_results": results, "artifact_hashes_verified": True}, indent=2))


if __name__ == "__main__":
    main()
