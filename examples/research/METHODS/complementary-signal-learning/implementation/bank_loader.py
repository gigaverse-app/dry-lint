# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E402, E741, F401, I001
"""Reconstruct source-complete native Candidates; no providers or embeddings.
The bank's native_eligible is only a structural prefilter. Detector.pair applies
why_skipped and the explicit settings supplied by the caller. Never infer adoption.
"""

import sys, pathlib, json, collections

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_bank import SRC, BASE, sha, digest, jl, Function, REF
from dry_lint.detector import Detector
from dry_lint.extractors import PythonExtractor
from dry_lint.typescript import TypeScriptExtractor
from dry_lint.models import Run
from dry_lint.settings import Settings
from dry_lint.presets import PRESETS


class BankComparer:
    name = "complementary-bank"
    version = "1-frozen-rrf60"
    similarity_reusable = False

    def index(self, functions):
        pass

    def similarity(self, a, b):
        return 0.0

    def neighbours(self, function, k, allowed):
        return []


def shadow_settings(panel):
    return Settings(
        preset="balanced",
        judge={
            "use": "anthropic",
            "model": "claude-haiku-5-5",
            "prompt_policy": "shared-operations",
            "max_tokens": 2048,
            "max_retries": 0,
        },
        discovery=PRESETS["balanced"].discovery,
        escalate={"use": "none"},
        budget={"usd": 0.04},
        report_at=0.5,
        drop_below=0.5,
        fail_at=0.5,
        drift_at=0.8,
        include=panel["scope"]["include"],
        exclude=panel["scope"]["exclude"],
    )


class BankLoader:
    def __init__(self, cohort_id, settings=None):
        self.receipt = json.loads((HERE / "bank" / cohort_id / "RECEIPT.json").read_text())
        self.panel = self.receipt["source"]
        p = self.panel
        assert sha(p["functions_path"]) == p["functions_sha256"]
        self.functions = [
            Function.model_validate(f if f.get("line") is not None else f | {"line": 0, "end_line": -1})
            for f in jl(p["functions_path"])
        ]
        self.settings = settings or shadow_settings(p)
        self.detector = Detector(
            self.functions, self.settings, BankComparer(), [PythonExtractor(), TypeScriptExtractor()], same_file=True
        )

    def candidate(self, row, score="fixed_fusion", lane="exploration"):
        assert row["cohort_id"] == self.panel["cohort_id"]
        assert row["source"]["functions_sha256"] == self.panel["functions_sha256"]
        assert row["source"]["background_sha256"] == self.panel["background_sha256"]
        q, t = row["query_position"], row["target_position"]
        a, b = self.functions[q], self.functions[t]
        assert q != t and a.qualname != b.qualname
        for f, endpoint in [(a, row["source"]["query"]), (b, row["source"]["target"])]:
            assert f.qualname == endpoint["source_id"] and digest(f.code) == endpoint["source_sha256"]
        value = row["scores"][score]
        if value is None:
            raise ValueError("Unavailable score is not zero")
        return self.detector.pair(a, b, float(value)).model_copy(update={"lane": lane})

    def run(self, query, arm):
        return Run(
            repository=self.panel["repository"],
            revision=self.panel["revision"],
            session=f"complementary-bank:{self.panel['cohort_id']}:{query}:{arm}",
        )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("shard")
    args = ap.parse_args()
    with open(args.shard) as f:
        row = next(json.loads(l) for l in f if json.loads(l)["native_eligible"])
    c = BankLoader(row["cohort_id"]).candidate(row)
    print(
        json.dumps(
            {
                "candidate_id": row["candidate_id"],
                "candidate": c.model_dump(mode="json"),
                "product_commit": REF,
                "filter_authority": "actual Detector.pair with explicit shadow settings; not authenticated adopter configuration",
            },
            sort_keys=True,
        )
    )
