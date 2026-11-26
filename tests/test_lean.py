import json
import sys

import pytest
from tree_sitter_language_pack import downloaded_languages

from dry_lint.cli import main
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


def test_missing_lean_extra_has_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    with pytest.raises(ImportError, match=r"dry-lint\[lean\]"):
        LeanExtractor()


def test_detect_reports_a_changed_lean_proof_against_an_existing_file(tmp_path, lean):
    repo = Repo(tmp_path / "project")
    repo.write(".dry-lint/config.toml", 'extractors = ["lean"]\ncomparer = { use = "tfidf", max_df = 1.0 }')
    proof = "theorem {name} (n : Nat) : n + 0 = n := by\n  exact Nat.add_zero n\n"
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
