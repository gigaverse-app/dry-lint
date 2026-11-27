import json
import runpy
from pathlib import Path

audit = runpy.run_path(str(Path(__file__).parents[1] / "scripts/rank_lean_rewrites.py"))


def test_counts_rules_across_distinct_lists(tmp_path, capsys):
    src, build = tmp_path / "src", tmp_path / "build"
    src.mkdir()
    build.mkdir()
    (src / "Demo.lean").write_text(
        "theorem alpha (n : Nat) : n = n := by\n"
        "  have a : n = n := by simp only [Nat.add_zero, Nat.add_zero, Nat.mul_one]\n"
        "  simp only [Nat.mul_one, Nat.add_zero]\n"
        "theorem beta (n : Nat) : n = n := by\n"
        "  -- simp only [Nat.add_zero]\n"
        "  simp only [Nat.add_zero]\n",
        encoding="utf-8",
    )
    (src / "Unbuilt.lean").touch()
    (build / "Demo.ilean").write_text(
        json.dumps({"version": 6, "decls": {"alpha": [0, 0, 2, 40, 0, 8, 0, 13], "beta": [3, 0, 5, 26, 3, 8, 3, 12]}}),
        encoding="utf-8",
    )
    audit["main"]([str(src), str(build)])
    report = json.loads(capsys.readouterr().out)
    assert (report["built_modules"], report["unbuilt_modules"]) == (1, 1)
    assert report["findings"] == [
        {"path": "Demo.lean", "line": 1, "name": "alpha", "repeat_mentions": 2, "call_lines": [2, 3]}
    ]
