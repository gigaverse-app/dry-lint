import json
import runpy
import sys
from pathlib import Path

import pytest
from tree_sitter_language_pack import downloaded_languages

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_lean_proof_references.py"
audit = runpy.run_path(str(SCRIPT))
pytestmark = pytest.mark.skipif("lean" not in downloaded_languages(), reason="Prefetch the Lean grammar")


def write_module(root, name, symbols, binder, *, include_proof=True, version=6):
    source = root / "src" / f"{name}.lean"
    artifact = root / "build" / f"{name}.ilean"
    source.parent.mkdir(parents=True, exist_ok=True)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    statements = (
        [f"theorem {name} : True := by -- Different local names"]
        + [f"  have {binder}{i} := {symbol}" for i, symbol in enumerate(symbols)]
        + ["  trivial"]
        if include_proof
        else [f"def {name} : Nat :="] + ["  1 +" for _ in symbols] + ["  0"]
    )
    source.write_text("\n".join(statements) + "\n", encoding="utf-8")
    references = [
        [0, "Lean.Meta", "Lean.Meta.common"],
        {"usages": [[2, 0, 2, 1, name]]},
        [1, name, "local"],
        {"usages": [[2, 0, 2, 1, name]]},
        [0, "Mathlib.Example", "Outside.statement"],
        {"usages": [[0, 10, 0, 20, name], [2, 0, 2, 1, None]]},
    ]
    for i, symbol in enumerate(symbols):
        references.extend([[0, "Mathlib.Example", symbol], {"usages": [[i + 1, 10, i + 1, 20, name]]}])
    artifact.write_text(json.dumps({"version": version, "module": name, "references": references}), encoding="utf-8")


def test_reference_audit_aligns_compiler_names_across_local_names(tmp_path, capsys, monkeypatch):
    symbols = [f"Example.fact{i}" for i in range(14)]
    write_module(tmp_path, "Left", symbols, "left")
    write_module(tmp_path, "Right", symbols, "different")
    write_module(tmp_path, "Decoy", symbols[:5] + ["Example.decoy"] * 9, "decoy")
    write_module(tmp_path, "TermMode", symbols, "term", include_proof=False)
    hidden = tmp_path / "src/.ignored"
    hidden.mkdir()
    (hidden / "Hidden.lean").touch()
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(tmp_path / "src"), str(tmp_path / "build")])
    runpy.run_path(str(SCRIPT), run_name="__main__")
    report = json.loads(capsys.readouterr().out)
    assert report["analyzed_proofs"] == 3
    assert report["matches"] == [
        {
            "score": 14.0,
            "shared_lines": 14,
            "left": {"path": "Left.lean", "name": "Left", "start": 2, "end": 16},
            "right": {"path": "Right.lean", "name": "Right", "start": 2, "end": 16},
            "references": [[i, i, symbol] for i, symbol in enumerate(symbols, start=2)],
        }
    ]


def test_reference_audit_rejects_missing_or_incompatible_artifacts(tmp_path, capsys):
    args = [str(tmp_path / "src"), str(tmp_path / "build")]
    with pytest.raises(SystemExit):
        audit["main"](args)
    assert "No eligible proofs" in capsys.readouterr().err
    write_module(tmp_path, "Invalid", [], "unused", version=7)
    with pytest.raises(SystemExit):
        audit["main"](args)
    assert "expected version 6" in capsys.readouterr().err
    (tmp_path / "build/Invalid.ilean").unlink()
    with pytest.raises(SystemExit):
        audit["main"](args)
    assert "Invalid.ilean" in capsys.readouterr().err
