"""Prove emitted native cache matches the CPU worker's unmodified input contract."""

import importlib.util

from common import HERE, ROOT, dump, folders, load, sha

path = ROOT / "jobs/improve-cpu-retrieval/.lab-results/common.py"
spec = importlib.util.spec_from_file_location("cpu_contract_read_only", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
rows = []
for p in folders():
    a, b, fs, n = load(p.parent)
    aa, bb, ffs, nn = module.load(p.parent)
    assert a == aa and b == bb and n == nn
    assert [f.model_dump(mode="json") for f in fs] == [f.model_dump(mode="json") for f in ffs]
    assert [f.tokens for f in fs] == [f.tokens for f in ffs]
    rows.append({"cohort_id": a["cohort_id"], "background": p.parent.name, "functions": len(fs), "compatible": True})
dump(
    HERE / "cpu-contract-check.json",
    {"source": str(path), "sha256": sha(path.read_bytes()), "backgrounds": rows, "status": "passed"},
)
print("PASS original CPU common.load contract:", len(rows), "backgrounds")
