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


def test_family_command_aligns_three_declarations_and_does_not_join_disjoint_matches(repo, capsys):
    from dry_lint.cli import main

    shared = [f"Example.fact{i}" for i in range(14)]
    other = [f"Other.fact{i}" for i in range(14)]
    write_module(repo.root, "Left", shared + other, "pivot")
    write_module(repo.root, "Middle", shared, "decoy")
    write_module(repo.root, "Right", shared, "right")
    write_module(repo.root, "Separate", other, "right")
    repo.git("add", "src")
    args = [
        "lean-proof-families",
        "--root",
        str(repo.root),
        "--source-root",
        "src",
        "--artifact-root",
        "build",
    ]

    assert main([*args, "--format", "json", "--focus", "src/Right.lean"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["analyzed_proofs"] == 4
    assert result["families_found"] == 1
    [group] = result["families"]
    assert group["score"] == 28
    assert group["shared_lines"] == 14
    assert [member["path"] for member in group["members"]] == ["src/Left.lean", "src/Middle.lean", "src/Right.lean"]
    assert group["references"][0] == {"name": "Example.fact0", "lines": [2, 2, 2]}

    assert main(args) == 0
    output = capsys.readouterr().out
    assert "3 declarations · at least 14 aligned lines each" in output
    assert "2, 2, 2  Example.fact0" in output

    assert main([*args, "--focus", "src/Separate.lean"]) == 0
    assert "Found 0 Lean proof families across 4 analyzed declarations." in capsys.readouterr().out
    assert main([*args, "--limit", "-1"]) == 2
    assert "--limit must be nonnegative" in capsys.readouterr().err

    broken = repo.root / "build/Right.ilean"
    broken.write_text('{"version": 6, "module": "Right"}', encoding="utf-8")
    assert main(args) == 2
    assert "references" in capsys.readouterr().err


def test_family_ranking_prefers_the_shared_core_with_more_lines():
    from dry_lint.lean_proof_references import Alignment, rank_families

    sites = [(i, 0, f"Example.fact{i}") for i in range(1, 11)]
    collapsed = [(1, i, site[2]) for i, site in enumerate(sites)]
    full = tuple(zip(sites, sites, strict=True))
    short = full[:7]
    packed = tuple(zip(sites, collapsed, strict=True))

    [family] = rank_families([Alignment(0, 1, full), Alignment(0, 2, short), Alignment(1, 2, full)])
    assert family.shared_lines == 10
    assert family.members == (0, 1, 2)
    assert not rank_families([Alignment(0, 1, full), Alignment(0, 2, packed)])


def test_reference_audit_reports_disjoint_fragments_inside_a_proof(tmp_path, capsys):
    shared = [f"Example.fact{i}" for i in range(12)]
    first = shared[:6] + ["Example.first_only"] + shared[6:]
    second = shared[:9] + ["Example.second_only"] + shared[9:]
    write_module(tmp_path, "Repeated", first + ["Example.between"] * 4 + second, "local")
    write_module(tmp_path, "Single", first + ["Example.no_match"] * 9, "single")
    write_module(tmp_path, "SameSymbol", ["Example.common"] * 25, "common")

    audit["main"]([str(tmp_path / "src"), str(tmp_path / "build"), "--within-proof"])
    report = json.loads(capsys.readouterr().out)

    assert report["analyzed_proofs"] == 3
    assert report["matches"] == [
        {
            "score": 12.0,
            "shared_lines": 12,
            "left": {"path": "Repeated.lean", "name": "Repeated", "start": 2, "end": 14},
            "right": {"path": "Repeated.lean", "name": "Repeated", "start": 19, "end": 31},
            "references": [[i + 2 + (i >= 6), i + 19 + (i >= 9), name] for i, name in enumerate(shared)],
        }
    ]


@pytest.mark.parametrize("right_start", [7, 18])
def test_reference_audit_rejects_overlapping_or_sparse_fragments(right_start):
    from dry_lint.lean_proof_references import Proof

    proof = Proof("Example.lean", "example", 1, 40, [])
    rows = []
    for i, line in enumerate(range(1, 23, 3)):
        name = f"Example.fact{i}"
        rows.append(((line, 0, name), (right_start + i, 0, name)))
    assert audit["fragment_match"](proof, rows) is None


def test_reference_windows_ignores_repeated_triples_on_the_same_line():
    names = ["Example.a", "Example.b", "Example.c"] * 2
    refs = [(1, column, name) for column, name in enumerate(names)]
    assert audit["reference_windows"](refs, names) == []
