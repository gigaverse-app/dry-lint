import json
import runpy
from pathlib import Path

import pytest
from tree_sitter_language_pack import downloaded_languages

from dry_lint.lean import LeanExtractor

audit = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "audit_lean_coverage.py"))
pytestmark = pytest.mark.skipif("lean" not in downloaded_languages(), reason="Prefetch the Lean grammar")
SOURCE = """namespace Audit
/- 🌍 -/ def point := 3
theorem identity (a : Nat) : a = a := by
  rfl
end Audit
"""
# Produced by lean -i Audit.ilean Audit.lean. The two tables overlap for identity.
ARTIFACT = {
    "version": 6,
    "module": "Audit",
    "decls": {"Audit.identity": [2, 0, 3, 5, 2, 8, 2, 16]},
    "references": [
        [0, "Audit", "Audit.identity"],
        {"definition": [2, 8, 2, 16], "usages": []},
        [0, "Audit", "Audit.point"],
        {"definition": [1, 13, 1, 18], "usages": []},
        [0, "Init.Prelude", "Nat"],
        {"definition": None, "usages": [[2, 22, 2, 25, "Audit.identity"]]},
    ],
}


def test_compiler_site_locations_and_misses():
    # A two-line minimum deliberately omits point. Its LSP column follows a non-BMP character.
    count, missing = audit["compare_module"](LeanExtractor(min_lines=2), "Audit.lean", SOURCE, ARTIFACT)
    assert (count, missing) == (2, [(2, "Audit.point")])


def test_audit_module_inventory_and_format(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "Audit.lean").write_text(SOURCE, encoding="utf-8")
    (src / "Unbuilt.lean").touch()
    hidden = src / ".lake"
    hidden.mkdir()
    (hidden / "Dependency.lean").touch()
    artifact = tmp_path / "Audit.ilean"
    args = [str(src), str(tmp_path), "--show-missed"]
    with pytest.raises(SystemExit):
        audit["main"](args)
    assert "No eligible declaration" in capsys.readouterr().err
    artifact.write_text(json.dumps({**ARTIFACT, "version": 99}), encoding="utf-8")
    with pytest.raises(SystemExit):
        audit["main"](args)
    assert "expected Lean .ilean version 6" in capsys.readouterr().err
    artifact.write_text(json.dumps(ARTIFACT), encoding="utf-8")
    audit["main"](args)
    assert json.loads(capsys.readouterr().out) == {
        "built_modules": 1,
        "unbuilt_modules": 1,
        "eligible_sites": 2,
        "matched": 2,
        "missed": [],
    }
