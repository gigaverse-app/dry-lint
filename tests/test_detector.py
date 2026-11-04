import pytest

from dry_lint import detector as detection
from dry_lint.detector import Detector, base_ref, changed_lines, default_base, touched, why_skipped
from dry_lint.extractors import PythonExtractor
from dry_lint.models import Function
from dry_lint.settings import Pattern, PluginChoice, Settings

from conftest import Repo, function


def changed_functions(repo: Repo, detector: Detector, **where) -> list[str]:
    return [f.qualname for f in touched(detector.functions, changed_lines(repo.root, **where))]


def test_changed_lines_cover_the_lines_a_branch_added(repo: Repo) -> None:
    lines = changed_lines(repo.root, base="main")
    assert set(lines) == {"src/widgets/caption.py"}
    assert lines["src/widgets/caption.py"] == set(range(1, 12))


def test_changed_lines_of_staged_changes_ignore_unstaged_ones_and_deleted_files(repo: Repo) -> None:
    repo.write("src/text.py", (repo.root / "src/text.py").read_text().replace("limit - 1", "limit - 2"))
    repo.git("add", "src/text.py")
    repo.git("rm", "-q", "src/widgets/caption.py")
    repo.write("src/unstaged.py", "def later(x):\n    return x\n")
    assert changed_lines(repo.root, staged=True) == {"src/text.py": {5}}


def test_only_functions_overlapping_changed_lines_count_as_changed(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    assert changed_functions(repo, detector, base="main") == [
        "src/widgets/caption.py::preview_caption_text", "src/widgets/caption.py::register_widget"]


def test_a_reimplementation_of_an_existing_helper_becomes_a_candidate(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    changed = touched(detector.functions, changed_lines(repo.root, base="main"))
    candidates = detector.candidates(changed)
    pairs = {(c.new.qualname, c.existing.qualname) for c in candidates}
    assert ("src/widgets/caption.py::preview_caption_text", "src/text.py::shorten_text") in pairs
    assert not any(new.endswith("register_widget") for new, _ in pairs)
    assert all(c.filtered is None and c.comparer == "tfidf:2" for c in candidates)


def test_candidates_carry_both_structure_hashes_for_the_store(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    [twin] = [c for c in detector.candidates(touched(detector.functions, changed_lines(repo.root, base="main")))
              if c.existing.name == "shorten_text"]
    extractor = detector.extractors[0]
    assert twin.new.hash == extractor.structure_hash(twin.new) and twin.existing.hash == extractor.structure_hash(twin.existing)
    assert all(f.hash == "" for f in detector.functions)  # only paired functions are hashed


def tfidf(**options) -> Settings:
    return Settings(comparer=PluginChoice(use="tfidf", **options))


def test_neighbours_come_from_other_files_and_respect_the_floor(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    for f in detector.functions:
        floor = detector.comparer.floor(f)
        for other, similarity in detector.neighbours(f):
            assert other.path != f.path and similarity >= floor
    strict = Detector.for_repository(repo.root, tfidf(min_similarity=1.01, min_similarity_small=1.01))
    assert all(strict.neighbours(f) == [] for f in strict.functions)


def test_a_pair_is_proposed_once_even_when_both_sides_changed(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    both = [f for f in detector.functions if f.name in {"shorten_text", "preview_caption_text"}]
    candidates = detector.candidates(both)
    keys = [frozenset((c.new.qualname, c.existing.qualname)) for c in candidates]
    assert len(keys) == len(set(keys))


def test_scan_reports_mutual_nearest_neighbours_closest_first(repo: Repo) -> None:
    pairs = Detector.for_repository(repo.root, Settings()).scan()
    assert {(c.new.name, c.existing.name) for c in pairs} >= {("preview_caption_text", "shorten_text")} or \
        {(c.existing.name, c.new.name) for c in pairs} >= {("preview_caption_text", "shorten_text")}
    assert [c.similarity for c in pairs] == sorted((c.similarity for c in pairs), reverse=True)


def test_changed_functions_are_those_check_finds_without_reading_unchanged_files(repo: Repo) -> None:
    """INVARIANT: the cheap pre-check sees exactly the changed functions a full check would compare."""
    repo.write("tests/test_caption.py", "def test_caption(text):\n    assert text\n    return text\n")
    (repo.root / "src/dangling.py").symlink_to("missing.py")
    repo.git("add", "-A")
    repo.git("commit", "-qm", "excluded and unreadable files")
    expected = changed_functions(repo, Detector.for_repository(repo.root, Settings()), base="main")
    assert [f.qualname for f in detection.changed_functions(repo.root, Settings(), "main")] == expected != []
    assert detection.changed_functions(repo.root, Settings(), "HEAD") == []


A = function("a.py", "def load_user(store, key):\n    return store.read(key)\n")
B = function("b.py", "def load_account(store, key):\n    return store.read(key)\n")


@pytest.mark.parametrize("a, b, settings, reason", [
    (function("a.py", "def __init__(self, x):\n    self.x = x"), function("b.py", "def __init__(self, y):\n    self.y = y"),
     Settings(), "constructor or dunder pattern"),
    (function("a.py", "def read(self, key):\n    return self.rows[key]\n", owner="Store"),
     function("a.py", "def get(self, key):\n    return self.read(key)\n", owner="Store"), Settings(), "one calls the other"),
    (A, B, Settings(patterns=[Pattern(members="*::load_*", reason="one loader per resource")]),
     "declared pattern: one loader per resource"),
    (A, function("b.py", "def load_account(store, key):\n    # dry-lint: distinct-from a.py::load_user\n    return store.read(key)\n"),
     Settings(), "inline distinct-from"),
    (A, B, Settings(), None),
])  # fmt: skip
def test_why_skipped_names_the_rule_that_makes_look_alikes_not_duplicates(a, b, settings, reason) -> None:
    assert why_skipped(a, b, settings) == reason
    assert why_skipped(b, a, settings) == reason


@pytest.mark.parametrize("marker", ["# dry-lint: ignore", "// dry-lint: ignore", "#dry-lint:ignore (generated code)"])
def test_an_inline_ignore_settles_every_pair_the_function_is_in(marker: str) -> None:
    ignored = function("b.py", f"def load_account(store, key):\n    {marker}\n    return store.read(key)\n")
    assert why_skipped(A, ignored, Settings()) == why_skipped(ignored, A, Settings()) == "inline ignore"
    assert why_skipped(A, function("b.py", "def load_account(store, key):\n    # dry-lint: ignored? no\n    return store.read(key)\n"),
                       Settings()) is None


def test_same_named_functions_that_do_not_call_each_other_are_judged_not_skipped() -> None:
    connect = "def connect(self):\n    self.session = open_session(BASE_URL)\n    return self.session\n"
    a, b = function("feeds/youredge.py", connect, owner="YourEdge"), function("feeds/polymarket.py", connect, owner="Polymarket")
    assert why_skipped(a, b, Settings()) is None


def test_a_call_on_another_receiver_is_left_to_the_judge_not_taken_as_delegation() -> None:
    """
    INVARIANT: "one calls the other" settles a pair only when the call provably reaches the other function. By name
    alone, `self.inner.connect()` may call any object's `connect`, and `text.strip()` calls str.strip.
    """
    a = function("feeds/youredge.py", "def connect(self):\n    self.session = open_session(BASE_URL)\n    return self.session\n",
                 owner="YourEdge")
    wrapper = function("feeds/retry.py", "def connect(self):\n    return self.inner.connect()\n", owner="Retrying")
    assert why_skipped(wrapper, a, Settings()) is None
    strip = function("a.py", "def strip(text):\n    return text.strip().lower()\n")
    normalize = function("b.py", "def normalize(text):\n    return text.strip().lower()\n")
    assert why_skipped(strip, normalize, Settings()) is None


def test_only_a_call_on_the_class_itself_is_proven_delegation() -> None:
    """
    INVARIANT: "one calls the other" needs the call to resolve to the other function. Names are not resolved to
    symbols, so a bare call proves nothing: it may reach an imported function or a parameter of the same name.
    """
    read = function("a.py", "def read(self, key):\n    return self.rows[key]\n", owner="Store")
    get = function("a.py", "def get(self, key):\n    return self.read(key)\n", owner="Store")
    assert why_skipped(get, read, Settings()) == "one calls the other"
    other_class = function("b.py", "def read(self, key):\n    return self.rows[key]\n", owner="Cache")
    assert why_skipped(get, other_class, Settings()) is None
    imported = function("b.py", "def load_account(store, key):\n    from vendor import load_user\n    return load_user(store, key)\n")
    assert why_skipped(imported, A, Settings()) is None
    shadowing = function("c.py", "def load_account(load_user, key):\n    return load_user(key)\n")
    assert why_skipped(shadowing, A, Settings()) is None
    method_by_bare_name = function("c.py", "def read(key):\n    return ROWS[key]\n", owner="Rows")
    assert why_skipped(function("d.py", "def get(key):\n    return read(key)\n"), method_by_bare_name, Settings()) is None


def test_without_calls_from_the_extractor_the_defining_line_does_not_count_as_a_call() -> None:
    a = function("a.ts", "function load(key) {\n  return cache.get(key)\n}", name="load").model_copy(update={"calls": None})
    b = function("b.ts", "function load(id) {\n  return store.read(id)\n}", name="load").model_copy(update={"calls": None})
    assert why_skipped(a, b, Settings()) is None
    wrapper = function("c.ts", "function fetch(key) {\n  return load(key)\n}", name="fetch").model_copy(update={"calls": None})
    assert why_skipped(wrapper, a, Settings()) is None  # a bare `load` may be any `load` in scope
    method = function("a.ts", "fetch(key) {\n  return this.load(key)\n}", name="fetch", owner="Cache").model_copy(update={"calls": None})
    assert why_skipped(method, a.model_copy(update={"owner": "Cache"}), Settings()) == "one calls the other"
    method_call = function("d.ts", "function fetch(key) {\n  return cache.load(key)\n}", name="fetch").model_copy(update={"calls": None})
    assert why_skipped(method_call, a, Settings()) is None


BASE = "class Operation:\n    def entries(self, work):\n        return attempts_for(work).filter(revision=work.revision)\n"
OVERRIDE = "class Bulk({base}):\n    def entries(self, work):\n        return work.attempts()\n"


def methods(path: str, source: str) -> dict[str, Function]:
    return {f.qualname.split("::")[1]: f for f in PythonExtractor().functions(path, source)}


@pytest.mark.parametrize("path, source", [
    ("pkg/ops.py", BASE + OVERRIDE.format(base="Operation")),
    ("pkg/bulk.py", "from pkg.ops import Operation\n" + OVERRIDE.format(base="Operation")),
    ("src/pkg/bulk.py", "from pkg.ops import Operation\n" + OVERRIDE.format(base="Operation")),
    ("pkg/bulk.py", "from .ops import Operation as Base\n" + OVERRIDE.format(base="Base[int]")),
    ("pkg/sub/bulk.py", "from ..ops import Operation\n" + OVERRIDE.format(base="Operation")),
    ("pkg/bulk.py", "import pkg.ops\n" + OVERRIDE.format(base="pkg.ops.Operation")),
    ("pkg/bulk.py", "import pkg.ops as o\n" + OVERRIDE.format(base="o.Operation")),
    ("pkg/bulk.py", "from . import ops\n" + OVERRIDE.format(base="ops.Operation")),
])  # fmt: skip
def test_a_method_overriding_its_base_class_method_is_settled_by_rule(path: str, source: str) -> None:
    """
    INVARIANT: an override of the same-named method of the class's direct base is the hierarchy's variation point,
    not a copy. The base resolves from the file alone: a class it defines, or a name its imports bind.
    """
    home = "src/pkg/ops.py" if path.startswith("src/") else "pkg/ops.py"
    base = methods(home, BASE)["Operation.entries"]
    override = methods(path, source)["Bulk.entries"]
    assert why_skipped(override, base, Settings()) == why_skipped(base, override, Settings()) == "subclass override"


@pytest.mark.parametrize("source", [
    OVERRIDE.format(base="Operation"),  # neither defined nor imported
    "from other.ops import Operation\n" + OVERRIDE.format(base="Operation"),
    "from pkg.ops import Operation\n" + OVERRIDE.format(base="Operation").replace("entries", "attempts"),
    "from pkg.ops import Operation\n" + OVERRIDE.format(base="mixin(Operation)"),
    "from pkg.ops import Operation\n" + OVERRIDE.format(base="Other.Operation"),
    "from .... import ops\n" + OVERRIDE.format(base="ops.Operation"),
    "from pkg.ops import Operation\nclass Bulk(Operation):\n    class Inner:\n"
    "        def entries(self, work):\n            return work.attempts()\n",
])  # fmt: skip
def test_same_named_methods_without_a_resolved_base_relation_go_to_the_judge(source: str) -> None:
    """INVARIANT: only a base the file itself names settles a pair; an unresolved or unrelated class does not."""
    base = methods("pkg/ops.py", BASE)["Operation.entries"]
    found = methods("pkg/bulk.py", source)
    assert found and all(why_skipped(method, base, Settings()) is None for method in found.values())
    override = methods("pkg/bulk.py", "from pkg.ops import Operation\n" + OVERRIDE.format(base="Operation"))
    unrelated = methods("pkg/other.py", BASE.replace("Operation", "Cache"))["Cache.entries"]
    assert why_skipped(override["Bulk.entries"], unrelated, Settings()) is None


def test_an_override_pair_is_proposed_but_settled_and_left_out_of_the_backlog(repo: Repo) -> None:
    body = "        rows = self.store.read(key)\n        return [row for row in rows if row.revision == key.revision]\n"
    repo.write("src/ops.py", f"class Operation:\n    def possible_entries(self, key):\n{body}")
    repo.write("src/bulk.py", "from src.ops import Operation\n\n\nclass Bulk(Operation):\n"
                              f"    def possible_entries(self, key):\n{body.replace('revision', 'batch')}")
    repo.commit("override")
    detector = Detector.for_repository(repo.root, tfidf(min_similarity=0.0, min_similarity_small=0.0))
    [pair] = [c for c in detector.candidates([detector.find("Bulk.possible_entries")])
              if c.existing.qualname == "src/ops.py::Operation.possible_entries"]
    assert pair.filtered == "subclass override"
    assert {pair.new.qualname, pair.existing.qualname} not in [{c.new.qualname, c.existing.qualname}
                                                               for c in detector.scan()]


def test_skipped_pairs_are_listed_with_their_reason(repo: Repo) -> None:
    repo.write("src/widgets/caption.py", (repo.root / "src/widgets/caption.py").read_text().replace(
        "    if len(caption_text)", "    # dry-lint: distinct-from src/text.py::shorten_text\n    if len(caption_text)"))
    repo.commit("suppress")
    detector = Detector.for_repository(repo.root, Settings())
    candidates = detector.candidates(touched(detector.functions, changed_lines(repo.root, base="main")))
    [settled] = [c for c in candidates if c.existing.name == "shorten_text"]
    assert settled.filtered == "inline distinct-from"
    assert frozenset(("preview_caption_text", "shorten_text")) not in {frozenset((c.new.name, c.existing.name))
                                                                       for c in detector.scan()}


def test_each_function_gets_at_most_the_configured_number_of_neighbours(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, tfidf(min_similarity=0.0, min_similarity_small=0.0).model_copy(
        update={"neighbours": 1}))
    assert all(len(detector.neighbours(f)) <= 1 for f in detector.functions)
    assert any(len(detector.neighbours(f)) == 1 for f in detector.functions)


def test_the_base_defaults_to_the_remote_default_branch(repo: Repo, tmp_path) -> None:
    assert default_base(repo.root) == "origin/main"  # no remote recorded
    remote = tmp_path / "remote.git"
    repo.git("init", "-q", "--bare", "-b", "trunk", str(remote))
    repo.git("push", "-q", str(remote), "main:trunk")
    clone = tmp_path / "clone"
    repo.git("clone", "-q", str(remote), str(clone))
    assert default_base(clone) == "origin/trunk"


def test_an_empty_or_all_zero_base_means_the_default_branch(repo: Repo) -> None:
    assert base_ref(repo.root, "abc123") == "abc123"
    assert base_ref(repo.root, None) == base_ref(repo.root, "") == base_ref(repo.root, "0" * 40) == "origin/main"


def test_find_resolves_a_unique_suffix_and_refuses_ambiguity(repo: Repo) -> None:
    detector = Detector.for_repository(repo.root, Settings())
    assert detector.find("text.py::shorten_text").qualname == "src/text.py::shorten_text"
    assert detector.find("src/text.py::shorten_text").name == "shorten_text"
    with pytest.raises(ValueError, match="functions match"):
        detector.find("::sync_")
    with pytest.raises(ValueError, match="0 functions"):
        detector.find("nowhere")


@pytest.mark.parametrize("declaration", ["def", "async def"])
def test_same_named_implementations_reach_both_check_and_scan(repo: Repo, declaration: str) -> None:
    source = f"{declaration} digest_phone_number(phone_number):\n    return hashlib.sha256(phone_number.encode()).hexdigest()\n"
    repo.write("src/guard.py", source)
    repo.write("src/forensics.py", source)
    repo.commit()
    detector = Detector.for_repository(repo.root, Settings())
    expected = {"src/guard.py::digest_phone_number", "src/forensics.py::digest_phone_number"}
    candidates = detector.candidates(touched(detector.functions, changed_lines(repo.root, base="main")))
    for pairs in (candidates, detector.scan()):
        assert any({pair.new.qualname, pair.existing.qualname} == expected and pair.filtered is None for pair in pairs)


@pytest.mark.parametrize("body", [
    "# load_user(store, key) is a possible alternative\n    return store.read(key)",
    '"""Unlike load_user(store, key), this reads an account."""\n    return store.read(key)',
    'return "load_user(store, key)"',
])  # fmt: skip
def test_mentions_of_another_function_do_not_suppress_a_candidate(body: str) -> None:
    other = function("b.py", f"def load_account(store, key):\n    {body}\n")
    assert why_skipped(A, other, Settings()) is None


def test_same_file_methods_cannot_hide_cross_file_neighbours(repo: Repo) -> None:
    repo.write("src/digests.py", "\n".join(
        f"class Resource{i}:\n"
        "    def phone_digest(self, phone_number):\n"
        "        return hashlib.sha256(phone_number.encode()).hexdigest()\n"
        for i in range(12)
    ))  # fmt: skip
    repo.write("src/forensics.py",
               "def phone_digest(phone_number):\n    return hashlib.sha256(phone_number.strip().encode()).hexdigest()\n")
    repo.commit()
    detector = Detector.for_repository(repo.root, Settings())
    local = next(f for f in detector.functions if f.owner == "Resource0")
    assert any(other.path == "src/forensics.py" for other, _ in detector.neighbours(local))


def test_schema_identity_ranks_the_real_twin_above_unrelated_serializer_glue(repo: Repo) -> None:
    # Different schemas used to receive identical fingerprints: only their field keys differ.
    for name, key in (("a_unrelated", "invoice_id"), ("b_existing", "customer_id"), ("c_new", "customer_id")):
        repo.write(
            f"src/{name}.py", f'def create(validated_data):\n    return dict({key}=validated_data.get("{key}"))\n'
        )
    repo.commit()
    detector = Detector.for_repository(repo.root, Settings(neighbours=1))
    changed = next(f for f in detector.functions if f.path == "src/c_new.py")
    candidates = detector.candidates([changed])
    assert [pair.existing.path for pair in candidates] == ["src/b_existing.py"]
    assert candidates[0].comparer == "tfidf:2"
