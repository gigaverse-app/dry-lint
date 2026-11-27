import json

from dry_lint.cli import main
from dry_lint.lean_constructors import constructors


def test_constructor_families(tmp_path, capsys):
    for i, name in enumerate(["north", "south", "west", "east"]):
        fields = [
            "  map' := 0",
            "  inverse := by\n    simp -- explanation",
            f"  value := {i}",
            f'  label := "{name}"',
        ]
        if i == 2:
            fields.reverse()
        if i == 3:
            fields[0] = "  map' := 1"
        (tmp_path / f"{name}.lean").write_text(f"def {name} : R where\n" + "\n".join(fields), encoding="utf-8")
    # A different record shares both assignments but has an extra field.
    (tmp_path / "other.lean").write_text(
        "def other : Larger where\n  map' := 0\n  inverse := by simp\n  extra := 1\n", encoding="utf-8"
    )
    args = ["lean-constructors", "--source-root", str(tmp_path)]
    assert main(args) == 0
    (group,) = json.loads(capsys.readouterr().out)
    assert group["shared_fields"] == ["inverse", "map'"]
    assert group["repeated_assignments"] == 4
    assert [m["name"] for m in group["members"]] == ["north", "south", "west"]
    assert all(m["path"] == m["name"] + ".lean" and m["line"] == 1 for m in group["members"])
    assert main([*args, "--min-sites", "1"]) == 2


def test_parse_only_complete_explicit_where_records():
    source = """namespace Demo
def good : R where
  inner := {
    value := 22 }
  /- filler := 7 -/
  name := "where"
  proof := by
    have local := 22
    exact local

def ordinary : Nat := 0
def missing : R where
  value := 22
  value := 23
def method : R where
  f x := x
  name := 0
  proof := by simp
def mixed : R where
  f := 0
  g := 1
 deriving Repr
end Demo
"""
    ((site, fields),) = list(constructors("Demo.lean", source))
    assert site == {"path": "Demo.lean", "line": 2, "name": "good"}
    assert set(fields) == {"inner", "name", "proof"}
    assert "value" in fields["inner"]
