"""`dry-lint blocks`: lines repeated inside functions, whatever the functions around them do."""

import sys

import pytest

from dry_lint.blocks import function_lines
from dry_lint.cli import main
from dry_lint.models import Function

from conftest import Repo

FETCH = '''
def fetch_{name}(client, key):
    """Read {name}."""
    {before}
    response = client.get(key, timeout=30, retries=3)

    # Servers answer 202 while the object is being built.
    if response.status == 202:
        response = client.poll(response.headers["location"], timeout=30)
    payload = response.json()["{name}"]
    return {after}
'''


def fetch(name: str, before: str, after: str) -> str:
    return FETCH.format(name=name, before=before, after=after)


def test_blocks_reports_source_lines_across_blank_lines_and_comments(tmp_path, capsys):
    repo = Repo(tmp_path / "project")
    repo.write("a.py", fetch("user", "audit(key)", "User(**payload)"))
    repo.write("b.py", "import os\n\n" + fetch("order", "key = key.strip()", "payload"))
    repo.commit()
    assert main(["blocks", "--root", str(repo.root), "--lines", "3", "--min-shared-chars", "40"]) == 0
    assert capsys.readouterr().out == (
        "Found 1 repeated blocks.\n\n"
        "a.py:4-8\n"
        "b.py:7-11\n"
        "  response = client.get(key, timeout=30, retries=3)\n"
        "  if response.status == 202:\n"
        '      response = client.poll(response.headers["location"], timeout=30)\n'
    )


def test_blocks_ignores_docstrings_and_text_outside_functions(tmp_path, capsys):
    repo = Repo(tmp_path / "project")
    shared = '''
    def {name}(value):
        """
        Convert the value the caller supplied into the form the store keeps,
        rejecting anything the store cannot round-trip without losing data.
        Callers handle the error themselves.
        """
        return {name}_impl(value)
    '''
    table = "TABLE = [\n" + "".join(f'    "a fairly long constant number {i}",\n' for i in range(6)) + "]\n"
    repo.write("a.py", table + "\n" + shared.format(name="first"))
    repo.write("b.py", table + "\n" + shared.format(name="second"))
    repo.commit()
    assert main(["blocks", "--root", str(repo.root), "--lines", "3", "--min-shared-chars", "10"]) == 0
    assert capsys.readouterr().out == "Found 0 repeated blocks.\n"


def test_blocks_reports_the_longest_match_once(tmp_path, capsys):
    repo = Repo(tmp_path / "project")
    steps = "".join(f"    total = combine(total, measure(rows, column={i}))\n" for i in range(9))
    repo.write("a.py", f"def first(rows):\n    total = 0\n{steps}    return total\n")
    repo.write("b.py", f"def second(rows):\n    total = 1\n{steps}    return -total\n")
    # A nested function's lines belong to the function around it and are compared once.
    repo.write(
        "c.py",
        f"def third(rows):\n    def inner():\n        total = 2\n    {steps.replace(chr(10), chr(10) + '    ')[:-4]}",
    )
    repo.commit()
    assert main(["blocks", "--root", str(repo.root)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Found 1 repeated blocks.\n\na.py:3-11\nb.py:3-11\nc.py:4-12\n  total = combine(")
    assert main(["blocks", "--root", str(repo.root), "--max-lines", "6", "--limit", "1"]) == 0
    assert "a.py:3-8\n" in capsys.readouterr().out
    assert main(["blocks", "--root", str(repo.root), "--include", "a.py"]) == 0
    assert capsys.readouterr().out == "Found 0 repeated blocks.\n"


def test_blocks_allows_one_differing_line_and_gaps(tmp_path, capsys):
    repo = Repo(tmp_path / "project")
    body = """
    def {name}(session, record):
        session.begin(isolation="serializable", read_only=False)
        session.lock(record.table, record.key, wait_seconds=5)
        {middle}
        session.write(record.table, record.key, record.payload)
        session.commit(wait_for_replicas=True, timeout_seconds=30)
    """
    repo.write("a.py", body.format(name="first", middle="record.validate()"))
    repo.write("b.py", body.format(name="second", middle="record.normalise()\n        record.stamp()"))
    repo.commit()
    command = ["blocks", "--root", str(repo.root), "--lines", "4", "--min-shared-chars", "40"]
    assert main(command) == 0
    assert capsys.readouterr().out == "Found 0 repeated blocks.\n"
    assert main([*command, "--max-gap-lines", "2"]) == 0
    out = capsys.readouterr().out
    assert "a.py:1-5\n  def first(session, record):" not in out
    assert "a.py:2-6\n" in out and "b.py:2-7\n" in out and "record.stamp()" in out


def test_blocks_reads_typescript_and_selected_extractors(tmp_path, capsys):
    repo = Repo(tmp_path / "project")
    body = """
    export function {name}(items: Item[]): number {{
      // {name} totals differ only in the last step.
      const open = items.filter((item) => item.state === "open" && !item.archived);
      const weights = open.map((item) => item.weight * item.quantity);

      const total = weights.reduce((sum, weight) => sum + weight, 0);
      return {result};
    }}
    """
    repo.write("a.ts", body.format(name="gross", result="total"))
    repo.write("b.ts", body.format(name="net", result="total * 0.8"))
    repo.write("c.py", "def unrelated():\n    return 1\n")
    repo.commit()
    command = ["blocks", "--root", str(repo.root), "--lines", "3", "--extractor", "typescript"]
    assert main(command) == 0
    out = capsys.readouterr().out
    assert out.startswith("Found 1 repeated blocks.\n\na.ts:3-6\nb.ts:3-6\n  const open = items.filter(")
    assert main(["blocks", "--root", str(repo.root), "--lines", "3"]) == 0
    assert capsys.readouterr().out == out  # The default configuration reads TypeScript as well.
    assert main(["blocks", "--root", str(repo.root), "--lines", "3", "--extractor", "python"]) == 0
    assert capsys.readouterr().out == "Found 0 repeated blocks.\n"


@pytest.mark.parametrize(
    ("option", "value", "error"),
    [
        ("--lines", "2", "--lines must be at least 3"),
        ("--limit", "-1", "--limit must be nonnegative"),
        ("--max-lines", "4", "--max-lines must be at least --lines"),
        ("--extractor", "cobol", "cobol"),
    ],
)
def test_blocks_validates_options(tmp_path, capsys, option, value, error):
    repo = Repo(tmp_path / "project")
    assert main(["blocks", "--root", str(repo.root), option, value]) == 2
    assert error in capsys.readouterr().err


def test_blocks_keeps_a_long_match_whose_shorter_windows_are_too_small(tmp_path, capsys):
    repo = Repo(tmp_path / "project")
    steps = "".join(f"    step_{i}(state)\n" for i in range(6))
    repo.write("a.py", f"def first(state):\n{steps}    return state\n")
    repo.write("b.py", f"def second(state):\n{steps}    return None\n")
    repo.commit()
    # Six shared lines hold 78 characters; no window of three, four or five lines holds 70.
    assert main(["blocks", "--root", str(repo.root), "--lines", "3", "--min-shared-chars", "70"]) == 0
    assert capsys.readouterr().out.startswith("Found 1 repeated blocks.\n\na.py:2-7\nb.py:2-7\n  step_0(state)\n")


@pytest.mark.parametrize("command", [["blocks"], ["scan", "--judge", "none"]])
def test_a_missing_extra_is_named_without_a_traceback(tmp_path, capsys, monkeypatch, command):
    repo = Repo(tmp_path / "project")
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    assert main([*command, "--root", str(repo.root), "--extractor", "lean"]) == 2
    assert "dry-lint[lean]" in capsys.readouterr().err


def test_blocks_compares_an_inner_function_once_and_skips_unreadable_files(tmp_path, capsys):
    repo = Repo(tmp_path / "project")
    body = """
    export function {name}(items: Item[]): number {{
      function weigh(open: Item[]): number {{
        const weights = open.map((item) => item.weight * item.quantity * {factor});
        const total = weights.reduce((sum, weight) => sum + weight, 0);
        const rounded = Math.round(total * 100) / 100;
        return rounded;
      }}
      return weigh(items.filter((item) => item.state === "open"));
    }}
    """
    repo.write("a.ts", body.format(name="gross", factor="1") + body.format(name="net", factor="0.8"))
    (repo.root / "latin1.py").write_bytes("def caf\xe9():\n    return 1\n".encode("latin-1"))
    repo.commit()
    assert main(["blocks", "--root", str(repo.root), "--lines", "3", "--min-shared-chars", "40"]) == 0
    assert capsys.readouterr().out.startswith("Found 1 repeated blocks.\n\na.ts:4-9\na.ts:14-19\n")


def test_function_lines_reads_a_nested_function_as_part_of_the_one_around_it():
    class Nested:
        line_comment = ";"

        def functions(self, path, source):
            return [
                Function(path=path, name="inner", line=2, end_line=3, code=""),
                Function(path=path, name="outer", line=1, end_line=4, code=""),
                Function(path=path, name="next", line=6, end_line=9, code=""),
            ]

    source = "outer:\n  inner:\n    one\n  two\n\nnext:\n  ; note\n  three\n"
    assert list(function_lines(Nested(), "a.x", source)) == [
        [(1, "outer:"), (2, "  inner:"), (3, "    one"), (4, "  two")],
        [(6, "next:"), (8, "  three")],
    ]
