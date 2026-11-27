import io
import json
import sys

import pytest
from tree_sitter_language_pack import downloaded_languages

from dry_lint.cli import main
from dry_lint.comparers import TfidfComparer
from dry_lint.lean import LeanExtractor
from dry_lint.plugins import load
from dry_lint.settings import PluginChoice

from conftest import Repo


@pytest.fixture
def lean():
    if "lean" not in downloaded_languages():
        pytest.skip("Prefetch the Lean grammar as described in CONTRIBUTING.md")
    return load("extractors", PluginChoice(use="lean"))


def test_namespace_scopes_proof_ranges_and_body_tokens(lean):
    source = """namespace Outer
section Inner
/- A nested /- theorem phantom := 1 -/ comment -/
open Nat in
@[simp] private lemma id_eq (α : Nat) : α = α := by
  -- the tactic is the entire body
  rfl

end Inner
namespace Nested
def pick : Nat → Nat
  | 0 => 1
  | n + 1 => n
end Nested
opaque bare : Nat
instance : Inhabited Nat where
  default := 0
def tiny := 1
end Outer
"""
    lean.validate_source("A.lean", source)
    proof, pick = lean.functions("A.lean", source)
    assert (proof.qualname, proof.line, proof.end_line) == ("A.lean::Outer.id_eq", 4, 7)
    assert proof.code == "\n".join(source.splitlines()[3:7])
    assert proof.tokens == ["by", "rfl", "type:α", "type:=", "type:α"]
    assert pick.qualname == "A.lean::Outer.Nested.pick"
    assert "=>" in pick.tokens and "n" in pick.tokens
    assert lean.structure_hash(pick) != lean.structure_hash(
        pick.model_copy(update={"code": pick.code.replace("=> 1", "=> 2")})
    )


def test_named_instance_root_override_and_parse_recovery(lean):
    source = """namespace A
instance _root_.zeroNat : Inhabited Nat where
  default := 0
end A
def broken (x :
"""
    (instance,) = lean.functions("A.lean", source)
    assert instance.qualname == "A.lean::zeroNat"
    assert "default" in instance.tokens
    with pytest.raises(ValueError, match="Cannot completely scan A.lean"):
        lean.validate_source("A.lean", source)


def test_discovers_a_proof_that_uses_unsupported_notation_without_weakening_strict_validation(lean):
    source = """postfix:max "ᴴ" => id
namespace Example
theorem first (n : Nat) : nᴴ = n := by
  rfl
/-- A later declaration. -/
theorem second : True := by
  trivial
end Example
"""
    with pytest.raises(ValueError, match="Cannot completely scan A.lean"):
        lean.validate_source("A.lean", source)

    first, second = lean.functions("A.lean", source)
    assert (first.qualname, first.line, first.end_line) == ("A.lean::Example.first", 3, 4)
    assert first.code == "theorem first (n : Nat) : nᴴ = n := by\n  rfl"
    assert first.tokens == ["by", "rfl", "type:n", "type:ᴴ", "type:=", "type:n"]
    assert (second.qualname, second.line, second.end_line) == ("A.lean::Example.second", 6, 7)


@pytest.mark.parametrize(
    "source",
    [
        "theorem first : True := by\n  have := (\ntheorem second : True := by\n  trivial\n",
        "theorem first : True := by\n  trivial ?\n#check True\n",
    ],
)
def test_skips_a_recovered_declaration_that_consumes_another_command(lean, source):
    assert lean.functions("A.lean", source) == []


@pytest.mark.parametrize(
    "source",
    [
        "theorem : ℕ := \n",
        "def first ( | 0 => ?_",
        "def first ℕ := : by rfl",
        "def first ℕ := \n",
        "def first : ℕᴴ := 0 ) :)",
    ],
)
def test_skips_incomplete_recovery_without_a_named_and_bounded_assignment(lean, source):
    assert lean.functions("A.lean", source) == []


@pytest.mark.parametrize("delimiter", ['"', 'r#"'])
def test_string_declarations_compare_the_literal_instead_of_its_delimiters(lean, delimiter):
    closing = '"' if delimiter == '"' else '"#'
    help_text = f"{delimiter}Check this project\nsecond line\n{closing}"
    workflow = f"{delimiter}name: Update Dependencies\nsecond line\n{closing}"
    source = [help_text, workflow, help_text]
    declarations = [lean.functions(f"{i}.lean", f"def message :=\n{text}\n")[0] for i, text in enumerate(source)]
    help_def, workflow_def, duplicate = declarations
    comparer = TfidfComparer(max_df=1.0)
    comparer.index(declarations)
    assert comparer.similarity(help_def, workflow_def) == 0
    assert comparer.similarity(help_def, duplicate) == pytest.approx(1)


def test_missing_lean_extra_has_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    with pytest.raises(ImportError, match=r"dry-lint\[lean\]"):
        LeanExtractor()


def test_detect_reports_a_changed_lean_proof_against_an_existing_file(tmp_path, lean):
    repo = Repo(tmp_path / "project")
    repo.write(".dry-lint/config.toml", 'extractors = ["lean"]\ncomparer = { use = "tfidf", max_df = 1.0 }')
    proof = "theorem {name} (ν : Nat) : ν + 0 = ν := by\n  exact Nat.add_zero ν\n"
    repo.write("Existing.lean", proof.format(name="first"))
    repo.commit()
    repo.git("switch", "-c", "feature")
    repo.write("Added.lean", proof.format(name="second"))
    repo.commit()
    out = tmp_path / "candidates.json"
    assert main(["detect", "--root", str(repo.root), "--base", "main", "--out", str(out)]) == 0
    [pair] = json.loads(out.read_text(encoding="utf-8"))["candidates"]
    assert (pair["new"]["name"], pair["existing"]["name"]) == ("second", "first")
    assert pair["new"]["context_digest"] != pair["existing"]["context_digest"]


def test_scan_can_select_lean_without_configuring_the_extractor(tmp_path, lean, capsys):
    repo = Repo(tmp_path / "project")
    repo.write(".dry-lint/config.toml", 'comparer = { use = "tfidf", max_df = 1.0 }')
    proof = "theorem {name} (n : Nat) : n + 0 = n := by\n  exact Nat.add_zero n\n"
    repo.write("First.lean", proof.format(name="first"))
    repo.write("Second.lean", proof.format(name="second"))
    repo.commit()
    command = ["scan", "--root", str(repo.root), "--judge", "none", "--format", "json"]

    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == []
    assert main([*command, "--extractor", "lean"]) == 0
    [finding] = json.loads(capsys.readouterr().out)["findings"]
    assert {finding["candidate"][side]["path"] for side in ["new", "existing"]} == {"First.lean", "Second.lean"}


def test_within_file_scan_finds_local_proof_pairs_without_cross_file_matches(tmp_path, lean, capsys):
    repo = Repo(tmp_path / "project")
    repo.write(".dry-lint/config.toml", 'extractors = ["lean"]\ncomparer = { use = "tfidf", max_df = 1.0 }')
    proof = "theorem {name} (n : Nat) : n + 0 = n := by\n  exact Nat.add_zero n\n"
    repo.write("Local.lean", proof.format(name="first") + proof.format(name="second"))
    repo.write("Elsewhere.lean", proof.format(name="external"))
    repo.commit()

    command = ["scan", "--root", str(repo.root), "--judge", "none", "--format", "json"]
    assert main(command) == 0
    [finding] = json.loads(capsys.readouterr().out)["findings"]
    pair = finding["candidate"]
    assert {pair["new"]["path"], pair["existing"]["path"]} == {"Local.lean", "Elsewhere.lean"}

    assert main([*command, "--within-file"]) == 0
    [finding] = json.loads(capsys.readouterr().out)["findings"]
    pair = finding["candidate"]
    assert pair["new"]["path"] == pair["existing"]["path"] == "Local.lean"
    assert {pair["new"]["name"], pair["existing"]["name"]} == {"first", "second"}

    assert main([*command, "--within-file", "--repo", f"example/project={repo.root}"]) == 2
    assert "--within-file scans a single repository" in capsys.readouterr().err


def test_lean_proof_blocks_include_same_file_and_preserve_indentation(tmp_path, lean, capsys):
    repo = Repo(tmp_path / "project")
    demo = """lemma {name} (p : Prop) (hp : p) : {goal} := by
{indent}have h : p := hp
{indent}have h' : p := h
{indent}exact h'
"""
    a = demo.format(name="first", goal="p", indent="  ")
    b = demo.format(name="second", goal="p ∨ False", indent="    ").replace(
        "    have h : p := hp", "    left\n    have h : p := hp"
    )
    repo.write("A.lean", a + b)
    repo.write("B.lean", demo.format(name="third", goal="p", indent="  "))
    repo.write("Ignored.lean", demo.format(name="fourth", goal="p", indent="  "))
    repo.write(".dry-lint.toml", 'exclude = ["Ignored.lean"]\n')
    repo.commit()
    repo.write("Untracked.lean", a)
    command = ["lean-proof-blocks", "--root", str(repo.root), "--min-shared-chars", "25"]
    assert main(command) == 0
    assert capsys.readouterr().out == (
        "Found 1 repeated Lean proof blocks.\n\n"
        "A.lean:2\nA.lean:7\nB.lean:2\n  have h : p := hp\n  have h' : p := h\n  exact h'\n"
    )
    assert main([*command, "--limit", "0"]) == 0
    assert capsys.readouterr().out == "Found 1 repeated Lean proof blocks.\n"


@pytest.mark.parametrize("override", [None, "utf-16"])
def test_redirected_cli_keeps_lean_symbols(tmp_path, lean, monkeypatch, override):
    repo = Repo(tmp_path / "project")
    proof = "theorem {name} (h : True) : True := by\n  have h₁ := h\n  have h₂ := h₁\n  exact h₂\n"
    repo.write("A.lean", proof.format(name="one") + proof.format(name="two"))
    repo.commit()
    data = io.BytesIO()
    output = io.TextIOWrapper(data, encoding=override or "cp1252")
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    if override:
        monkeypatch.setenv("PYTHONIOENCODING", override)
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(
        sys, "argv", ["dry-lint", "lean-proof-blocks", "--root", str(repo.root), "--min-shared-chars", "1"]
    )
    assert main() == 0
    output.flush()
    assert "have h₂ := h₁" in data.getvalue().decode(override or "utf-8")


def test_lean_proof_blocks_compare_real_source_in_recovered_tactic_ranges(tmp_path, lean, capsys):
    repo = Repo(tmp_path / "project")
    # The static grammar recovers inside these induction tactics. The proof
    # scanner must keep the source binders instead of losing them as error tokens.
    proof = """theorem {name} {params} : 0 + r + {term} = r + {term} := by
  have h : ∀ x : Nat, 0 + x = x := Nat.zero_add
  induction r generalizing {vars} with
  | zero => simp only [h]
  | succ r ih => simp only [h]
"""
    repo.write("A.lean", proof.format(name="one", params="(r n : Nat)", term="n", vars="n"))
    repo.write("B.lean", proof.format(name="two", params="(r n m : Nat)", term="n + m", vars="n m"))
    repo.commit()
    command = ["lean-proof-blocks", "--root", str(repo.root), "--min-shared-chars", "60"]
    assert main(command) == 0
    assert capsys.readouterr().out == "Found 0 repeated Lean proof blocks.\n"

    assert main([*command, "--allow-one-line-difference"]) == 0
    output = capsys.readouterr().out
    assert "Found 1 repeated Lean proof blocks." in output
    assert "A.lean:2\n" in output and "B.lean:2\n" in output
    assert "induction r generalizing n with" in output
    assert "induction r generalizing n m with" in output


def test_lean_proof_blocks_skip_comments_and_outside_proofs(tmp_path, lean, capsys):
    repo = Repo(tmp_path / "project")
    comment = """  /-
  have something : Nat := 0 + 1 + 2 + 3 + 4
  have other : Nat := 30 + 31 + 32 + 33 + 34
  exact something + other
  -/"""
    source = """def outside : Nat :=
  1 + 200000000000000000000000000 +
  2 + 300000000000000000000000000 +
  3 + 400000000000000000000000000
def inside : Nat := by
{comment}
  exact 0
"""
    repo.write("A.lean", source.format(comment=comment))
    repo.write("B.lean", source.format(comment=comment))
    repo.write("Inline.lean", "def inline : Nat := by exact 0\n")
    repo.commit()
    assert main(["lean-proof-blocks", "--root", str(repo.root)]) == 0
    assert capsys.readouterr().out == "Found 0 repeated Lean proof blocks.\n"


@pytest.mark.parametrize(
    ("option", "value", "error"),
    [("--lines", "2", "--lines must be at least 3"), ("--limit", "-1", "--limit must be nonnegative")],
)
def test_lean_proof_blocks_validate_options(tmp_path, capsys, option, value, error):
    repo = Repo(tmp_path / "project")
    assert main(["lean-proof-blocks", "--root", str(repo.root), option, value]) == 2
    assert error in capsys.readouterr().err


def test_lean_proof_blocks_without_extra(tmp_path, capsys, monkeypatch):
    repo = Repo(tmp_path / "project")
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    assert main(["lean-proof-blocks", "--root", str(repo.root)]) == 2
    assert "dry-lint[lean]" in capsys.readouterr().err


def test_lean_proof_blocks_stop_recovery_at_the_next_declaration(tmp_path, lean, capsys):
    repo = Repo(tmp_path / "project")
    # Reduced from a recovered by node that consumed the next theorem's binders.
    source = """lemma interrupted (hS : ∀ v ∈ D.localPrimes, ↑q ∈ v.asIdeal)
  have h_coset : (s.φ 1 : Gal(Ω/K) ⧸ O.toSubgroup) = ↑(s.φ 1 * (1 * s.φ 1 * 1⁻¹)) := by
lemma following (hS : ∀ v ∈ D.localPrimes, ↑q ∈ v.asIdeal)
    (hO : ∀ g h : Gal(Ω/K), (g : Gal(Ω/K) ⧸ O.toSubgroup) = h →
      ∀ y : DiscreteUnits Ω, m • y ∈ fixedSUnits q D.subgroup → unitsRep h y = unitsRep g y)
    {I : Set Gal(Ω/K)} {s : SplitPlaces m q I D.subgroup (Gal(Ω/K) ⧸ O.toSubgroup)}
    (φ_coset : ∀ g ∈ D.subgroup, (s.φ g : Gal(Ω/K) ⧸ O.toSubgroup) = g)
    {γ : Gal(Ω/K) ⧸ O.toSubgroup → Gal(Ω/K)}
"""
    repo.write("A.lean", source)
    repo.write("B.lean", source)
    repo.commit()
    assert main(["lean-proof-blocks", "--root", str(repo.root), "--max-lines", "5"]) == 0
    assert capsys.readouterr().out == "Found 0 repeated Lean proof blocks.\n"


def test_lean_proof_blocks_rank_reuse_and_hide_contained_windows(tmp_path, lean, capsys):
    repo = Repo(tmp_path / "project")
    longer = """theorem {name} (h : True) : True := by
  have h1 : True := h
  have h2 : True := h1
  have h3 : True := h2
  have h4 : True := h3
  exact h4
"""
    shorter = """theorem {name} (longArgumentNameAlreadyInScope : True) : True := by
  have unrelatedHypothesis : True := longArgumentNameAlreadyInScope
  have anotherUnrelatedHypothesis : True := unrelatedHypothesis
  exact anotherUnrelatedHypothesis
"""
    repo.write("LongA.lean", longer.format(name="longA"))
    repo.write("LongB.lean", longer.format(name="longB"))
    repo.write("ShortA.lean", shorter.format(name="shortA"))
    repo.write("ShortB.lean", shorter.format(name="shortB"))
    repo.write("Overlap.lean", "theorem overlap : True := by\n  skip\n  skip\n  skip\n  skip\n  trivial\n")
    repo.commit()
    command = ["lean-proof-blocks", "--root", str(repo.root), "--min-shared-chars", "1"]
    assert main(command) == 0
    before = capsys.readouterr().out
    assert before.index("ShortA.lean:2") < before.index("LongA.lean:2")
    assert "Overlap.lean:3" in before

    assert main([*command, "--max-lines", "5"]) == 0
    after = capsys.readouterr().out
    assert after.startswith("Found 2 repeated Lean proof blocks.\n\nLongA.lean:2\nLongB.lean:2")
    assert "  have h4 : True := h3\n  exact h4\n" in after
    assert "Overlap.lean" not in after

    assert main([*command, "--max-lines", "2"]) == 2
    assert "--max-lines must be at least --lines" in capsys.readouterr().err


def test_lean_proof_blocks_match_anchors_across_unequal_gaps(tmp_path, lean, capsys):
    repo = Repo(tmp_path / "project")
    prefix = """  have first : True := proof
  have second : True := first
"""
    suffix = """  have third : True := second
  exact third
"""
    repo.write("A.lean", "theorem a (proof : True) : True := by\n" + prefix + suffix)
    repo.write(
        "B.lean",
        "theorem b (proof : True) : True := by\n" + prefix + "  have extra : True := proof\n  clear extra\n" + suffix,
    )
    repo.commit()
    command = ["lean-proof-blocks", "--root", str(repo.root), "--lines", "4"]
    assert main([*command, "--allow-one-line-difference"]) == 0
    assert capsys.readouterr().out == "Found 0 repeated Lean proof blocks.\n"

    assert main([*command, "--max-gap-lines", "1"]) == 0
    assert capsys.readouterr().out == "Found 0 repeated Lean proof blocks.\n"

    assert main([*command, "--max-gap-lines", "2", "--max-lines", "5"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("Found 1 repeated Lean proof blocks.\n\nA.lean:2\n")
    assert "B.lean:2\n" in output and "  clear extra\n" in output

    assert main([*command, "--max-gap-lines", "2", "--allow-one-line-difference"]) == 0
    assert capsys.readouterr().out == output

    assert main([*command, "--max-gap-lines", "-1"]) == 2
    assert "--max-gap-lines must be nonnegative" in capsys.readouterr().err


def test_lean_proof_blocks_gap_cannot_match_overlapping_windows(tmp_path, lean, capsys):
    repo = Repo(tmp_path / "project")
    repo.write("One.lean", "theorem one : True := by\n" + "  skip\n" * 6 + "  trivial\n")
    repo.commit()
    assert (
        main(
            [
                "lean-proof-blocks",
                "--root",
                str(repo.root),
                "--lines",
                "4",
                "--max-gap-lines",
                "2",
                "--min-shared-chars",
                "1",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == "Found 0 repeated Lean proof blocks.\n"
