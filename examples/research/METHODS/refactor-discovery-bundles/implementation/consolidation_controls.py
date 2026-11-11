# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: F401, F403, F405, I001
"""Synthetic before/after regression using actual product extractor and settling rule."""

from bundles import *
from run_study import HERE, write
from dry_lint.detector import Detector
from dry_lint.comparers import TfidfComparer
from dry_lint.extractors import PythonExtractor

BEFORE = '''class Service:
    def shared(self, value: int) -> int:
        """Advance the value once."""
        return value + 1

    def wrapper(self, value: int) -> int:
        """Advance the value once."""
        return value + 1
'''
AFTER = BEFORE.rsplit("return value + 1", 1)[0] + "return self.shared(value)\n"


def control():
    extractor = PythonExtractor()
    results = {}
    for name, code in [("before", BEFORE), ("after", AFTER)]:
        fs = extractor.functions("service.py", code)
        d = Detector(fs, Settings(discovery={"enabled": False}), TfidfComparer(), [extractor], same_file=True)
        c = d.pair(fs[1], fs[0], 1.0)
        results[name] = {"candidate": c.model_dump(mode="json"), "filtered": c.filtered, "code": code}
    assert results["before"]["filtered"] is None
    assert results["after"]["filtered"] == "forwarding wrapper"
    return {
        "kind": "synthetic language-adapter before/after control; not historical source gold",
        "meaning": "After extraction, unchanged forwarding wrapper is settled by actual Detector.pair and cannot enter active bundle leads. Full function signatures/docs retained.",
        "results": results,
        "provider_calls": 0,
    }


if __name__ == "__main__":
    write("consolidation-control.json", control())
