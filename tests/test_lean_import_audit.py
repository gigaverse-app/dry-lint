import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_lean_imports.py"
audit = runpy.run_path(str(SCRIPT))


def add_module(root, module, *imports, version=6):
    relative = Path(*module.split("."))
    source = root / "src" / relative.with_suffix(".lean")
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("".join(f"import {dep}\n" for dep in imports), encoding="utf-8")
    artifact = root / ".lake/build/lib/lean" / relative.with_suffix(".ilean")
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "version": version,
                "module": module,
                "directImports": [[dep, False, False, False] for dep in imports],
            }
        ),
        encoding="utf-8",
    )
    return artifact


def candidate(module, name, **extra):
    return {"path": f"src/{module.replace('.', '/')}.lean", "line": 4, "name": name, **extra}


def finding(first, second):
    return {"candidate": {"new": first, "existing": second, "similarity": 0.9}}


def test_audit_prioritizes_matches_across_import_boundary(tmp_path, capsys, monkeypatch):
    add_module(tmp_path, "Main", "Proof.Core", "Mathlib")
    add_module(tmp_path, "Proof.Core")
    add_module(tmp_path, "Alternate.Route", "Alternate.Support", "Proof.Core")
    add_module(tmp_path, "Alternate.Support")
    add_module(tmp_path, "Standalone")
    hidden = tmp_path / "src/.cache"
    hidden.mkdir()
    (hidden / "Ignored.lean").touch()
    inside = candidate("Proof.Core", "primary")
    outside = candidate("Alternate.Route", "alternative")
    report = tmp_path / "scan.json"
    report.write_text(
        json.dumps(
            {
                "findings": [
                    finding(inside, outside),
                    finding(outside, candidate("Alternate.Support", "support")),
                    finding(candidate("Proof.Core", "peer", origin={"repository": "org/peer"}), outside),
                    finding(candidate("External", "other"), inside),
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(report), "--root", str(tmp_path), "--entry", "Main"])
    runpy.run_path(str(SCRIPT), run_name="__main__")
    assert json.loads(capsys.readouterr().out) == {
        "entry_modules": ["Main"],
        "project_modules": 5,
        "reachable_modules": 2,
        "outside_import_closure": [
            {
                "modules": ["Alternate.Route", "Alternate.Support"],
                "matches": [{"inside": inside, "outside": outside, "similarity": 0.9}],
            },
            {"modules": ["Standalone"], "matches": []},
        ],
    }


def test_audit_requires_complete_matching_artifacts(tmp_path, capsys):
    artifact = add_module(tmp_path, "Main", version=99)
    args = [str(tmp_path / "scan.json"), "--root", str(tmp_path), "--entry", "Missing"]
    with pytest.raises(SystemExit):
        audit["main"](args)
    assert "expected Lean .ilean version 6 for Main" in capsys.readouterr().err
    add_module(tmp_path, "Main")
    with pytest.raises(SystemExit):
        audit["main"](args)
    assert "Entry modules absent" in capsys.readouterr().err
    artifact.unlink()
    with pytest.raises(SystemExit):
        audit["main"](args)
    assert "Main.ilean" in capsys.readouterr().err


def test_audit_matches_scan_paths_when_the_project_is_below_the_checkout(tmp_path, capsys):
    # dry-lint names files from the top of the Git checkout, wherever --root points.
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    project = tmp_path / "proof"
    add_module(project, "Main", "Proof.Core")
    add_module(project, "Proof.Core")
    add_module(project, "Alternate")
    inside, outside = (
        {**candidate(module, name), "path": f"proof/src/{module.replace('.', '/')}.lean"}
        for module, name in (("Proof.Core", "primary"), ("Alternate", "alternative"))
    )
    report = tmp_path / "scan.json"
    report.write_text(json.dumps({"findings": [finding(inside, outside)]}), encoding="utf-8")
    audit["main"]([str(report), "--root", str(project), "--entry", "Main"])
    captured = capsys.readouterr()
    assert json.loads(captured.out)["outside_import_closure"] == [
        {"modules": ["Alternate"], "matches": [{"inside": inside, "outside": outside, "similarity": 0.9}]}
    ]
    assert captured.err == ""


def test_audit_warns_when_the_scan_stopped_at_its_default_limit(tmp_path, capsys):
    add_module(tmp_path, "Main")
    add_module(tmp_path, "Alternate")
    pair = finding(candidate("Main", "primary"), candidate("Alternate", "alternative"))
    report = tmp_path / "scan.json"
    report.write_text(json.dumps({"findings": [pair] * 50}), encoding="utf-8")
    audit["main"]([str(report), "--root", str(tmp_path), "--entry", "Main"])
    captured = capsys.readouterr()
    assert len(json.loads(captured.out)["outside_import_closure"][0]["matches"]) == 50
    assert "exactly 50 pairs, the default `scan --limit`" in captured.err
