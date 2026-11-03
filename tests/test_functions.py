import pytest

from dry_lint.extractors import PythonExtractor
from dry_lint.functions import (
    behaviour_tokens,
    extractor_for,
    function_calls,
    repository_functions,
    structure_hash,
    tracked_files,
    words,
)
from dry_lint.models import Function

from conftest import Repo, function

ORIGINAL = '''
def shorten(text: str, limit: int) -> str:
    """Shorten text."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    return cut + "…"
'''


@pytest.mark.parametrize("cosmetic", [
    # comments and formatting
    'def shorten(text: str, limit: int) -> str:\n    # short enough?\n    if len(text) <= limit:\n        return text\n'
    '    cut = text[:limit - 1]  # keep room\n\n    return cut + "…"',
    # no docstring, no annotations
    'def shorten(text, limit):\n    if len(text) <= limit:\n        return text\n    cut = text[: limit - 1]\n    return cut + "…"',
    # renamed function, parameters and locals
    'def clip(s, n):\n    """Clip."""\n    if len(s) <= n:\n        return s\n    head = s[: n - 1]\n    return head + "…"',
])  # fmt: skip
def test_structure_hash_ignores_comments_docstrings_annotations_and_renames(cosmetic: str) -> None:
    assert structure_hash(function("a.py", cosmetic)) == structure_hash(function("a.py", ORIGINAL))


@pytest.mark.parametrize("logic", [
    ORIGINAL.replace("limit - 1", "limit - 3"),
    ORIGINAL.replace("<=", "<"),
    ORIGINAL.replace('"…"', '"..."'),
    ORIGINAL.replace("len(text)", "width(text)"),
])  # fmt: skip
def test_structure_hash_changes_when_logic_changes(logic: str) -> None:
    assert structure_hash(function("a.py", logic)) != structure_hash(function("a.py", ORIGINAL))


def test_structure_hash_of_unparsable_code_is_still_stable() -> None:
    broken = function("a.py", "def broken(:\n    pass", name="broken")
    assert structure_hash(broken) == structure_hash(broken.model_copy())
    assert len(structure_hash(broken)) == 16


def test_the_extractor_lists_functions_and_methods_by_qualified_name() -> None:
    source = (
        "def top(a):\n    return a\n\n"
        "class Box:\n    def open(self):\n        def helper():\n            return 1\n        return helper()\n\n"
        "def one_liner(): pass\n"
    )
    found = PythonExtractor().functions("pkg/box.py", source)
    assert [f.qualname for f in found] == ["pkg/box.py::top", "pkg/box.py::Box.open"]
    assert found[1].lines == 4 and "helper" in found[1].code


def test_the_extractor_skips_files_that_do_not_parse() -> None:
    assert PythonExtractor().functions("x.py", "def broken(:\n") == []


def test_behaviour_tokens_capture_calls_attributes_names_and_control_flow() -> None:
    source = '''
    async def fetch_rows(client, query):
        rows = []
        for page in client.pages(query):
            try:
                rows += await page.load()
            except KeyError:
                pass
        return rows
    '''
    tokens = behaviour_tokens(function("a.py", source))
    assert tokens.count("fn:fetch") == 2 and tokens.count("fn:rows") == 2
    assert {"call:pages", "call:load", "attr:pages", "w:client", "w:query", "ctl:loop", "ctl:try", "ctl:await"} <= set(tokens)


def test_behaviour_tokens_of_unparsable_code_fall_back_to_the_name() -> None:
    assert behaviour_tokens(function("a.py", "def parse_header(:", name="parse_header")) == ["fn:parse", "fn:header"] * 2


def test_words_split_identifiers_and_drop_generic_ones() -> None:
    assert words("parseHTTPHeader_value") == ["parse", "httpheader"]
    assert words("get_user_id") == ["user"]


def test_tracked_files_respect_include_and_exclude(repo: Repo) -> None:
    repo.write("tests/test_text.py", "def test_x():\n    assert True\n")
    repo.write("docs/notes with space.md", "notes\n")
    repo.commit("tests")
    files = tracked_files(repo.root, ["*.py"], ["tests/*"])
    assert sorted(files) == ["src/filler.py", "src/text.py", "src/widgets/caption.py"]
    assert tracked_files(repo.root, ["src/widgets/*"], []) == ["src/widgets/caption.py"]
    assert "docs/notes with space.md" in tracked_files(repo.root, ["*"], [])


def test_repository_functions_skip_files_that_cannot_be_read(repo: Repo) -> None:
    (repo.root / "src" / "binary.py").write_bytes(b"\xff\xfe\x00def")
    repo.commit("binary")
    names = {f.name for f in repository_functions(repo.root, ["*"], [], [PythonExtractor()])}
    assert {"shorten_text", "preview_caption_text", "sync_invoice"} <= names


class Lines:
    """A second extractor, for another language: every non-blank line of a .txt file is a function."""

    name, version, files = "lines", "1", ("*.txt",)

    def functions(self, path: str, source: str) -> list[Function]:
        return [Function(path=path, name=f"line{i}", line=i, end_line=i, code=text)
                for i, text in enumerate(source.splitlines(), 1) if text.strip()]

    def structure_hash(self, function: Function) -> str:
        return function.code


def test_each_file_is_read_by_the_first_extractor_whose_globs_match_it(repo: Repo) -> None:
    repo.write("notes/todo.txt", "buy milk\n\ncall home\n")
    repo.write("README.md", "# not read\n")
    repo.commit("text")
    found = repository_functions(repo.root, ["*"], [], [PythonExtractor(), Lines()])
    assert [f.qualname for f in found if f.path == "notes/todo.txt"] == ["notes/todo.txt::line1", "notes/todo.txt::line3"]
    assert not any(f.path == "README.md" for f in found)
    assert extractor_for("a/b.py", [Lines(), PythonExtractor()]).name == "python"
    assert extractor_for("a/b.md", [Lines(), PythonExtractor()]) is None


def test_the_python_extractor_gives_tokens_and_leaves_hashing_to_whoever_needs_it() -> None:
    source = "@cache\ndef shorten(text, limit):\n    return text[:limit]\n\ndef tiny(): pass\n"
    [found] = PythonExtractor().functions("a.py", source)
    assert found.hash == "" and found.tokens == behaviour_tokens(found)
    assert PythonExtractor().structure_hash(found) == structure_hash(found)
    assert [f.name for f in PythonExtractor(min_lines=1).functions("a.py", source)] == ["shorten", "tiny"]


def test_the_extractor_lists_calls_from_the_body_not_the_name_or_decorators() -> None:
    source = "@retry(times=3)\ndef connect(self, timeout=default_timeout()):\n    return self.client.connect(timeout)\n"
    [found] = PythonExtractor().functions("a.py", source)
    assert sorted(found.calls) == ["connect", "default_timeout"]
    assert PythonExtractor().functions("a.py", "def connect(self):\n    return 1\n")[0].calls == []
    assert function_calls(function("a.py", "def broken(:", name="broken")) is None


def test_decorators_change_neither_tokens_nor_hash() -> None:
    plain = "def shorten(text, limit):\n    return text[:limit]\n"
    [bare] = PythonExtractor().functions("a.py", plain)
    [decorated] = PythonExtractor().functions("a.py", "@functools.cache\n" + plain)
    assert bare.tokens == decorated.tokens
    assert structure_hash(bare) == structure_hash(decorated.model_copy(update={"code": "@functools.cache\n" + plain}))


def test_structure_hash_treats_async_functions_like_functions() -> None:
    a = function("a.py", "async def fetch(client, key):\n    '''Fetch.'''\n    return await client.get(key)\n")
    b = function("b.py", "async def load(api, name):\n    return await api.get(name)\n")
    c = function("c.py", "def load(api, name):\n    return api.get(name)\n")
    assert structure_hash(a) == structure_hash(b) != structure_hash(c)
