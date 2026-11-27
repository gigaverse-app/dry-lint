import json

import pytest

from dry_lint.cli import main
from dry_lint.lean_upstream import local_site


def test_rank_upstream_mentions(tmp_path, capsys):
    src = tmp_path / "src"
    dep = tmp_path / "dep"
    build = tmp_path / "build"
    for root in (src, dep, build):
        root.mkdir()
    (src / "Local.lean").write_text(
        "namespace Local\ntheorem small : True := trivial\nlemma big : True := by\n  trivial\nend Local\n",
        encoding="utf-8",
    )
    (src / "Unbuilt.lean").touch()
    (build / "Local.ilean").write_text(
        json.dumps(
            {
                "version": 6,
                "decls": {
                    "Local.small": [1, 0, 1, 29, 1, 8, 1, 13],
                    "Local.big": [2, 0, 3, 9, 2, 6, 2, 9],
                    "Local.stale": [2, 0, 3, 9, 2, 6, 2, 9],
                },
            }
        ),
        encoding="utf-8",
    )
    (dep / "Port.lean").write_text(
        "/-! From `Local.small`.\nAdapted from `Local.big` and `Local.big`. -/\n"
        "/-- Compare `Local.stale` and `Local.big`. -/\n"
        'def exampleString := "`Local.small`"\n-- `Local.small`\n',
        encoding="utf-8",
    )
    args = ["lean-upstream", "--source-root", str(src), "--artifact-root", str(build), "--dependency", str(dep)]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert (result["built_modules"], result["unbuilt_modules"]) == (1, 1)
    big, small = result["declarations"]
    assert (big["name"], big["lines"], big["line"]) == ("Local.big", 2, 3)
    assert big["citations"] == [{"path": "Port.lean", "line": i} for i in (2, 3)]
    assert small["citations"] == [{"path": "Port.lean", "line": 1}]
    assert main(args + ["--min-lines", "3"]) == 0
    assert json.loads(capsys.readouterr().out)["declarations"] == []
    (build / "Local.ilean").unlink()
    assert main(args) == 2


@pytest.mark.parametrize("coords", [[0, 0, 0, 36, 0, 16, 0, 24], [0, 0, 8, 36, 0, 16, 0, 24]])
def test_unicode_selection_and_stale_end(coords):
    line = "/- 😀 -/ lemma Local.αβ : True := trivial"
    col = len(line[: line.index("Local.")].encode("utf-16-le")) // 2
    coords[5], coords[7] = col, col + len("Local.αβ")
    expected = (1, 1) if coords[2] == 0 else None
    assert local_site("Local.αβ", coords, [line]) == expected
