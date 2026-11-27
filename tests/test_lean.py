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
    with pytest.raises(ValueError, match="Cannot completely scan A.lean: brackets do not balance .* line 5"):
        lean.validate_source("A.lean", source)


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("def a := 1\n/- never /- closed -/\ndef b := 2\n", "the comment that starts on line 2 is never closed"),
        ('def a := 1\ndef b : String :=\n  "open\n', "the string on line 3 is never closed"),
        ("theorem a : True := by\n  exact (trivial\n", "brackets do not balance in the command on line 1"),
    ],
)
def test_strict_validation_names_what_keeps_a_command_from_being_bounded(lean, source, reason):
    with pytest.raises(ValueError) as error:
        lean.validate_source("A.lean", source)
    assert str(error.value) == f"Cannot completely scan A.lean: {reason}"


def test_strict_validation_accepts_notation_that_only_lean_can_parse(lean):
    source = """postfix:max "ᴴ" => id
namespace Example
theorem first (n : Nat) : nᴴ = n := by
  rfl
/-- A later declaration. -/
theorem second : True := by
  trivial
end Example
"""
    lean.validate_source("A.lean", source)

    first, second = lean.functions("A.lean", source)
    assert (first.qualname, first.line, first.end_line) == ("A.lean::Example.first", 3, 4)
    assert first.code == "theorem first (n : Nat) : nᴴ = n := by\n  rfl"
    assert first.tokens == ["by", "rfl", "type:n", "type:ᴴ", "type:=", "type:n"]
    assert (second.qualname, second.line, second.end_line) == ("A.lean::Example.second", 6, 7)


def test_a_declaration_never_consumes_another_command(lean):
    # An unbalanced declaration is not reported, and the command after it is read on its own.
    unbalanced = "theorem first : True := by\n  have := (\ntheorem second : True := by\n  trivial\n"
    (second,) = lean.functions("A.lean", unbalanced)
    assert (second.name, second.line, second.end_line) == ("second", 3, 4)
    (first,) = lean.functions("A.lean", "theorem first : True := by\n  trivial ?\n#check True\n")
    assert first.code == "theorem first : True := by\n  trivial ?"


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


# Lean 4.37.0-rc1 accepts this module. `lean -i` reports the ranges asserted below, except that dry-lint
# starts a declaration after its doc comment and includes the commands that wrap it.
CORE_SYNTAX = r"""/-! Module text with a keyword: theorem phantom : True := trivial -/
namespace Outer.Inner
universe u
variable {α : Type u}

/-- A doc comment is not part of the declaration it introduces.
theorem inDoc : True := trivial -/
@[simp]
protected theorem first (a : Nat) : a + 0 = a := by
  -- a comment that opens /- nothing
  simp

set_option maxRecDepth 600 in
open Nat in
/-- Wrapped twice. -/
theorem second (a : Nat) : succ a = a + 1 := by
  open Classical in
  set_option maxRecDepth 700 in
  rfl -- trailing words

end Inner

/-- Fields carry their own doc comments. -/
structure Point where
  /-- The first coordinate. -/
  x : Nat
  y : Nat
  deriving Repr

instance (priority := low) pointInhabited : Inhabited Point where
  default := ⟨0, 0⟩

private noncomputable def «odd name» : Point → Nat
  | ⟨x, _⟩ => x

mutual
  def isEven : Nat → Bool
    | 0 => true
    | n + 1 => isOdd n
  def isOdd : Nat → Bool
    | 0 => false
    | n + 1 => isEven n
end

def countdown (n : Nat) : List Nat :=
  if h : n = 0 then [] else n :: countdown (n - 1)
termination_by n
decreasing_by omega

#check countdown

def quoted : List String := ["theorem \"fake\" : True := by",
  r#"
def raw : Nat := "1"
"#, "--", "/-"]

def character : Char :=
  '"'

abbrev Ωμ' : Nat :=
  3

theorem absLike (x : Nat) :
    x ∣ x := by
  exact Nat.dvd_refl x

def helper (n : Nat) : Nat := go n
where
  /-- A local doc comment. -/
  @[inline]
  go : Nat → Nat
    | 0 => 0
    | k + 1 => go k

end Outer
theorem _root_.Outer.rooted : True := by
  trivial
"""


def test_declaration_ranges_agree_with_the_compiler(lean):
    found = LeanExtractor(min_lines=1).functions("Core.lean", CORE_SYNTAX)
    assert [(f.qualname.removeprefix("Core.lean::"), f.line, f.end_line) for f in found] == [
        ("Outer.Inner.first", 8, 11),
        ("Outer.Inner.second", 13, 19),
        ("Outer.pointInhabited", 30, 31),
        ("Outer.«odd name»", 33, 34),
        ("Outer.isEven", 37, 39),
        ("Outer.isOdd", 40, 42),
        ("Outer.countdown", 45, 48),
        ("Outer.quoted", 52, 55),
        ("Outer.character", 57, 58),
        ("Outer.Ωμ'", 60, 61),
        ("Outer.absLike", 63, 65),
        ("Outer.helper", 67, 73),
        ("Outer.rooted", 76, 77),
    ]
    by_name = {f.name: f for f in found}
    assert by_name["second"].code.startswith("set_option maxRecDepth 600 in\nopen Nat in\n/-- Wrapped twice. -/\n")
    # A comment after the last code is not part of the declaration.
    assert by_name["second"].code.endswith("  set_option maxRecDepth 700 in\n  rfl")
    assert by_name["second"].tokens[:8] == ["by", "open", "Classical", "in", "set_option", "maxRecDepth", "700", "in"]
    assert by_name["isOdd"].code.endswith("| n + 1 => isEven n")
    assert by_name["countdown"].tokens[-6:] == [
        "termination_by",
        "n",
        "decreasing_by",
        "omega",
        "type:List",
        "type:Nat",
    ]
    assert by_name["helper"].tokens[:6] == ["go", "n", "where", "@", "[", "inline"]
    assert by_name["«odd name»"].tokens == ["|", "⟨", "x", ",", "_", "⟩", "=>", "x", "type:Point", "type:→", "type:Nat"]
    assert by_name["absLike"].tokens == ["by", "exact", "Nat.dvd_refl", "x", "type:x", "type:∣", "type:x"]
    literals = [token for token in by_name["quoted"].tokens if token.startswith("str:")]
    assert len(literals) == len(set(literals)) == 4
    assert by_name["character"].tokens[0].startswith("str:")


@pytest.mark.parametrize(
    "proof",
    [
        "theorem a (A : Matrix n n ℂ) : Aᴴᴴ = A := by\n  simp",
        "theorem a (x : G ⧸ N) : x = x := by\n  rfl",
        "theorem a (h : ∃ x : Nat, x = 1 ∧ True) : True := by\n  obtain ⟨x, -, h⟩ := h\n  exact h",
        "theorem a : ∀ᶠ x in Filter.atTop, (0 : Nat) ≤ x := by\n  simp",
        "theorem a (x : ℤ) :\n    |x| = |x| := by\n  rfl",
        "theorem a (s t : Finset ℕ) (h : #s = #t) :\n    #t =\n    #s := by\n  exact h.symm",
    ],
)
def test_notation_from_imports_does_not_hide_a_declaration(lean, proof):
    # The Riemann Hypothesis project uses each of these. A grammar without the imported notation lost them.
    source = f"{proof}\n\nomit [Fintype n] in\ntheorem b : True := by\n  trivial\n"
    first, second = lean.functions("A.lean", source)
    assert (first.name, first.code) == ("a", proof)
    assert (second.name, second.line, second.end_line) == ("b", first.end_line + 2, first.end_line + 4)
    assert second.tokens == ["by", "trivial", "type:True"]


def test_scopes_close_by_component_and_other_commands_end_a_declaration(lean):
    source = """@[expose] public section
noncomputable section
namespace New.Cohomology
variable (h : ∑ i in s, f i = 1)
def kept : Nat :=
  1
  deriving Inhabited

grind_pattern kept => kept
end Cohomology
namespace «GL»
class abbrev Both (α : Type) :=
  Inhabited α, Nonempty α
scoped[GL] notation "𝔤" => kept
local instance localOne : Inhabited Nat :=
  ⟨1⟩
deriving instance Repr for Both
def last : Nat :=
  2
end «GL»
end New
theorem outside : True := by
  trivial
"""
    found = lean.functions("A.lean", source)
    assert [(f.qualname.removeprefix("A.lean::"), f.line, f.end_line) for f in found] == [
        ("New.Cohomology.kept", 5, 7),
        ("New.GL.localOne", 15, 16),
        ("New.GL.last", 18, 19),
        ("outside", 22, 23),
    ]
    assert found[0].tokens == ["1", "deriving", "Inhabited", "type:Nat"]


def test_term_keywords_and_one_line_alternatives_stay_inside_their_declaration(lean):
    # Each shape is reduced from a Mathlib declaration whose compiler range the scan first got wrong.
    source = """def cast (model : Nat) : Nat :=
  unsafe unsafeCast model

lemma eq {p : Walk v w} : p.Nil → v = w | .nil => rfl
  -- a remark

scoped [Pointwise] attribute [instance] cast
local grind_pattern eq => p.Nil
unsafe def last : Nat :=
  1
"""
    cast, eq, last = LeanExtractor(min_lines=1).functions("A.lean", source)
    assert (cast.line, cast.end_line, cast.tokens[:2]) == (1, 2, ["unsafe", "unsafeCast"])
    assert (eq.line, eq.end_line) == (4, 4)
    assert eq.tokens == ["|", ".", "nil", "=>", "rfl", "type:p.Nil", "type:→", "type:v", "type:=", "type:w"]
    assert (last.line, last.end_line) == (9, 10)


def test_an_unfinished_comment_or_attribute_ends_the_scan(lean):
    proof = "theorem {name} : True := by\n  trivial\n"
    (only,) = lean.functions("A.lean", proof.format(name="a") + "/- unfinished\n" + proof.format(name="b"))
    assert (only.name, only.end_line) == ("a", 2)
    (only,) = lean.functions("A.lean", proof.format(name="a") + "@[simp\n" + proof.format(name="b"))
    assert (only.name, only.end_line) == ("a", 2)


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


def test_focused_lean_scan_and_explanation_share_the_same_sources(tmp_path, lean, capsys):
    repo = Repo(tmp_path / "project")
    repo.write(
        ".dry-lint/config.toml",
        'include = ["Other.lean"]\nexclude = ["Ignored.lean"]\ncomparer = { use = "tfidf", max_df = 1.0 }',
    )
    proof = "theorem {name} (n : Nat) : n + 0 = n := by\n  exact Nat.add_zero n\n"
    for path in ("Local.lean", "Other.lean", "Ignored.lean"):
        repo.write(path, proof.format(name="first") + proof.format(name="second"))
    repo.commit()
    focus = [
        "--root",
        str(repo.root),
        "--extractor",
        "lean",
        "--within-file",
        "--include",
        "Local.lean",
        "--include",
        "Ignored.lean",
    ]
    assert main(["scan", *focus, "--judge", "none", "--format", "json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["functions"] == 2
    [finding] = output["findings"]
    assert finding["candidate"]["existing"]["path"] == finding["candidate"]["new"]["path"] == "Local.lean"

    assert main(["explain", *focus, "first", "second"]) == 0
    explanation = capsys.readouterr().out
    assert "Local.lean::first ~ Local.lean::second" in explanation
    assert "Nat.add_zero" in explanation
    for name in ("first", "second"):
        assert f"#1 of the 1 look-alike(s) of {name}" in explanation

    assert main(["scan", *focus, "--repo", f"example/project={repo.root}"]) == 2
    assert "--include scopes one checkout" in capsys.readouterr().err


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
    assert main([*command, "--include", "B.lean"]) == 0
    assert capsys.readouterr().out == "Found 0 repeated Lean proof blocks.\n"


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


def test_lean_proof_blocks_follow_layout_where_the_grammar_loses_the_proof(tmp_path, lean, capsys):
    repo = Repo(tmp_path / "project")
    # Reduced from the Riemann Hypothesis project. The grammar does not read the unbracketed `if` in the
    # statement, and a scan of its `by` nodes found none of these steps.
    proof = """lemma {name} (σ : Φ) : (weight σ : ℝ) = a / if σ ∈ bPlaces then x else x₁ := by
  rw [weight_eq_ite]
  split
  · rw [cast_natB, cast_a, mul_div_cancel_left₀ _ (exp_ne_zero _)]
  · exact cast_offWeight

omit [Fintype anIndexTypeWithALongName] [DecidableEq anIndexTypeWithALongName]
  [Fintype anotherIndexTypeWithALongName] [DecidableEq anotherIndexTypeWithALongName]
  [Fintype aThirdIndexTypeWithALongName] [DecidableEq aThirdIndexTypeWithALongName] in
lemma {name}Next (first : Fin (by exact 3))
    (secondArgumentWithALongName : Nat) (thirdArgumentWithALongName : Nat)
    (fourthArgumentWithALongName : Nat) (fifthArgumentWithALongName : Nat)
    (sixthArgumentWithALongName : Nat) : True := by
  trivial
"""
    repo.write("A.lean", proof.format(name="one"))
    repo.write("B.lean", proof.format(name="two"))
    repo.commit()
    assert main(["lean-proof-blocks", "--root", str(repo.root), "--min-shared-chars", "60", "--max-lines", "8"]) == 0
    assert capsys.readouterr().out == (
        "Found 1 repeated Lean proof blocks.\n\nA.lean:2\nB.lean:2\n"
        "  rw [weight_eq_ite]\n  split\n"
        "  · rw [cast_natB, cast_a, mul_div_cancel_left₀ _ (exp_ne_zero _)]\n  · exact cast_offWeight\n"
    )


def test_lean_proof_blocks_skip_literals_and_blocks_without_layout(tmp_path, lean, capsys):
    repo = Repo(tmp_path / "project")
    source = """def message : String := by
  exact "a literal that continues
  on a second line with enough characters to compare
  and on a third line with enough characters to compare
  and on a fourth line with enough characters to compare"
theorem flushLeft : True ∧ True ∧ True := by
refine ⟨?firstGoalWithALongName, ?secondGoalWithALongName, ?thirdGoalWithALongName⟩
case firstGoalWithALongName => exact trivial
case secondGoalWithALongName => exact trivial
case thirdGoalWithALongName => exact trivial
theorem unfinished : True := by
"""
    repo.write("A.lean", source)
    repo.write("B.lean", source)
    repo.commit()
    assert main(["lean-proof-blocks", "--root", str(repo.root), "--min-shared-chars", "60"]) == 0
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
