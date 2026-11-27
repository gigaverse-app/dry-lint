import json

from dry_lint.cli import main


def test_rank_families_by_distinct_declarations(tmp_path, capsys):
    declarations = {}
    source = []
    for name in ("north", "south", "east"):
        line = len(source)
        source.extend(
            [
                f"theorem {name} (n : Nat) : n = n := by",
                "  simp only [a, b, c]",
                "  simp only [x, y]",
            ]
        )
        declarations[name] = [line, 0, line + 2, 17, line, 8, line, 8 + len(name)]
    source.extend(["-- simp only [a, b, c]", "def outside := [a, b, c]"])
    source[1] = "  simp only [c, a, b, x, y]"
    source[2] = "  simp only [a, b, c, x, y]"
    source[8] = "  simp only [a, b, c]"
    declarations["generated"] = declarations["north"]
    (tmp_path / "Demo.lean").write_text("\n".join(source), encoding="utf-8")
    (tmp_path / "Demo.ilean").write_text(json.dumps({"version": 6, "decls": declarations}), encoding="utf-8")
    (tmp_path / "Missing.lean").touch()
    (tmp_path / "Empty.lean").touch()
    (tmp_path / "Empty.ilean").write_text('{"version": 6, "decls": {}}', encoding="utf-8")
    args = ["lean-rewrite-families", "--source-root", str(tmp_path), "--artifact-root", str(tmp_path)]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["built_modules"], report["unbuilt_modules"]) == (2, 1)
    (bundle,) = report["findings"]
    assert bundle["rules"] == ["a", "b", "c"]
    assert bundle["proof_count"] == 3
    assert sorted(site["line"] for site in bundle["sites"]) == [2, 3, 5, 8, 9]
    assert main([*args, "--rule", "x"]) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == []


def test_reject_missing_or_incompatible_artifacts(tmp_path):
    args = ["lean-rewrite-families", "--source-root", str(tmp_path), "--artifact-root", str(tmp_path)]
    assert main([*args, "--limit", "0"]) == 2
    assert main(args) == 2
    (tmp_path / "Demo.lean").touch()
    (tmp_path / "Demo.ilean").write_text('{"version": 5}', encoding="utf-8")
    assert main(args) == 2


def test_nested_declaration_owns_its_call(tmp_path, capsys):
    source = "def outer := inner where\n  def inner := by simp only [a, b]\ndef another := by simp only [a, b]\n"
    (tmp_path / "Demo.lean").write_text(source, encoding="utf-8")
    decls = {
        "outer": [0, 0, 1, 34, 0, 4, 0, 9],
        "outer.inner": [1, 2, 1, 34, 1, 6, 1, 11],
        "another": [2, 0, 2, 35, 2, 4, 2, 11],
    }
    (tmp_path / "Demo.ilean").write_text(json.dumps({"version": 6, "decls": decls}), encoding="utf-8")
    args = ["lean-rewrite-families", "--source-root", str(tmp_path), "--artifact-root", str(tmp_path)]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == []
