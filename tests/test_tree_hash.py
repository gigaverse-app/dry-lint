"""The shared hash envelope preserves existing verdict identities across language adapters."""

import pytest

from dry_lint.luau import LuauExtractor
from dry_lint.luau_models import LuauModelExtractor
from dry_lint.typescript import TypeScriptExtractor


@pytest.mark.parametrize(
    "extractor, path, source, expected",
    [
        (LuauExtractor, "a.luau", "local t = {run = function(value)\nreturn value + 1\nend}\n", "01011c957cfba488"),
        (LuauModelExtractor, "a.luau", "type Record = {id: string, amount: number}\n", "70a9dd9d752e6673"),
        (TypeScriptExtractor, "a.ts", "class Box { run(value: number) {\nreturn value + 1;\n} }\n", "8f216748f08044b1"),
    ],
)
def test_parser_hash_envelope_preserves_existing_identifiers(extractor, path, source, expected):
    if path.endswith(".luau"):
        pytest.importorskip("tree_sitter_luau")
    plugin = extractor()
    function = plugin.functions(path, source)[0]
    assert plugin.structure_hash(function) == expected
