"""Replay the original synthetic mechanism control, with no corpus or inference."""

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--out", type=Path, required=True)
a = ap.parse_args()
out = a.out.resolve()
out.mkdir(parents=True, exist_ok=False)
# The toy reads no evidence; explicit sandbox root satisfies the legacy module's
# path declarations while its output directory is overridden before execution.
os.environ["DRY_LINT_EVIDENCE_ROOT"] = str(out)
impl = Path(__file__).resolve().parent / "implementation"
sys.path.insert(0, str(impl))
spec = importlib.util.spec_from_file_location("spectral_recovered", impl / "spectral.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.H = out
module.toy()
actual = json.loads((out / "TOY.json").read_text())
expected = json.loads((Path(__file__).resolve().parent / "toy-expected.json").read_text())
for row in (actual, expected):
    row["partition"].pop("seconds", None)
assert actual == expected
(out / "VALIDATION.json").write_text(
    json.dumps(
        {
            "passed": True,
            "scope": "Original synthetic graph cuts and overlapping-operation memberships; no empirical quality claim",
            "provider_calls": 0,
            "encoder_calls": 0,
        },
        indent=2,
    )
    + "\n"
)
