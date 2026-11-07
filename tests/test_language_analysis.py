"""Both language frontends must supply facts to the same conservative pair policy."""

import pytest

from dry_lint.detector import why_skipped
from dry_lint.extractors import PythonExtractor
from dry_lint.function_index import FunctionIndex, build_index, extraction_contract
from dry_lint.models import Candidate, Function, Run, Verdict
from dry_lint.plugins import Extractor
from dry_lint.settings import Settings
from dry_lint.store import VerdictStore
from dry_lint.typescript import TypeScriptExtractor


@pytest.fixture(params=[PythonExtractor(), TypeScriptExtractor()], ids=["python", "typescript"])
def language(request: pytest.FixtureRequest) -> Extractor:
    return request.param


def extract(language: Extractor, python: str, typescript: str) -> list[Function]:
    path, source = ("source.py", python) if language.name == "python" else ("source.ts", typescript)
    return language.functions(path, source)


@pytest.mark.parametrize("extra", [False, True], ids=["forwarder", "additional-policy"])
def test_resolved_direct_calls_settle_call_pairs(language: Extractor, extra: bool) -> None:
    python_extra = "        key = key.strip().lower()\n" if extra else ""
    ts_extra = "key = key.trim().toLowerCase();" if extra else ""
    target, wrapper = extract(
        language,
        "class Store:\n    def normalize(self, key):\n        return key.strip().lower()\n"
        f"    def read(self, key):\n{python_extra}        return self.normalize(key)\n",
        "class Store { normalize(key: string) { return key.trim().toLowerCase(); }"
        f"read(key: string) {{ {ts_extra} return this.normalize(key); }} }}",
    )
    # A caller that adds policy before delegating is still "one calls the other": both judges label that SEPARATE,
    # so every route settles it before spending judge budget or a discovery slot.
    expected = "one calls the other" if extra else "forwarding wrapper"
    assert why_skipped(wrapper, target, Settings()) == expected
    assert why_skipped(target, wrapper, Settings()) == expected


def test_overrides_with_executable_policy_remain_candidates(language: Extractor) -> None:
    base, child = extract(
        language,
        "class Base:\n    def normalize(self, key):\n        return key.strip().lower()\n"
        "class Child(Base):\n    def normalize(self, key):\n        return key.strip().lower()\n",
        "class Base { normalize(key: string) { return key.trim().toLowerCase(); } }"
        "class Child extends Base { override normalize(key: string) { return key.trim().toLowerCase(); } }",
    )
    assert why_skipped(base, child, Settings()) is None


def test_special_method_conventions_belong_to_the_language(language: Extractor) -> None:
    first, second = extract(
        language,
        "class First:\n    def __len__(self):\n        return len(self.rows)\n"
        "class Second:\n    def __len__(self):\n        return len(self.rows)\n",
        "class First { __len__() { return this.rows.length; } }class Second { __len__() { return this.rows.length; } }",
    )
    expected = "language convention: python-special-method" if language.name == "python" else None
    assert why_skipped(first, second, Settings()) == expected


def test_unknown_analysis_never_guesses_relationships_from_source() -> None:
    def legacy(name: str, code: str) -> Function:
        return Function(path="plugin.lang", name=name, owner="Store", code=code, line=1, end_line=2)

    assert (
        why_skipped(
            legacy("read", "read() {\nreturn this.normalize();}"),
            legacy("normalize", "normalize() {\nreturn 1;}"),
            Settings(),
        )
        is None
    )


def test_analysis_survives_wire_round_trip_and_invalidates_context(language: Extractor) -> None:
    target, wrapper = extract(
        language,
        "class Store:\n    def normalize(self, key):\n        return key.strip().lower()\n"
        "    def read(self, key):\n        return self.normalize(key)\n",
        "class Store { normalize(key: string) { return key.trim().toLowerCase(); }"
        "read(key: string) { return this.normalize(key); } }",
    )
    pair = Candidate(new=wrapper, existing=target, similarity=1)
    restored = Candidate.model_validate_json(pair.model_dump_json())
    assert why_skipped(restored.new, restored.existing, Settings()) == "forwarding wrapper"
    assert restored.context_hash == pair.context_hash
    assert wrapper.analysis is not None
    changed = wrapper.model_copy(update={"analysis": wrapper.analysis.model_copy(update={"version": "next"})})
    assert pair.model_copy(update={"new": changed}).context_hash != pair.context_hash


def test_function_indexes_preserve_language_analysis(language: Extractor) -> None:
    path, source = (
        (
            "source.py",
            "from base import Base\nclass Store(Base):\n    def read(self, key):\n        return key.strip()\n",
        )
        if language.name == "python"
        else (
            "source.ts",
            "import { Base } from './base'; class Store extends Base { read(key: string) { return key.trim(); } }",
        )
    )
    settings = Settings()
    index = build_index({path: source.encode()}, "example/project", "a" * 40, settings)
    restored = FunctionIndex.decode(index.encode(), "example/project", "a" * 40, extraction_contract(settings))
    function = restored.extracted()[0]
    assert function.analysis is not None
    assert function.analysis.language == language.name
    assert function.bases == ["base::Base"]


def store_pair(
    language: Extractor, python_body: str, ts_body: str, python_params: str = "key", ts_params: str = "key: string"
) -> list[Function]:
    return extract(
        language,
        "class Store:\n    def normalize(self, key):\n        return key.strip()\n"
        f"    def read(self, {python_params}):\n        {python_body}\n",
        f"class Store {{ normalize(key: string) {{ return key.trim(); }} read({ts_params}) {{ {ts_body} }} }}",
    )


@pytest.mark.parametrize(
    "python_body, ts_body",
    [
        ("return other.normalize(key)", "return other.normalize(key);"),
        ("return normalize(key)", "return normalize(key);"),
        ("return getattr(self, 'normalize')(key)", "return this['normalize'](key);"),
        ("return 1", "return 1;"),
    ],
)
def test_unresolved_calls_remain_candidates(language: Extractor, python_body: str, ts_body: str) -> None:
    target, wrapper = store_pair(language, python_body, ts_body)
    assert wrapper.analysis is not None and wrapper.analysis.local_calls == ()
    assert why_skipped(wrapper, target, Settings()) is None


@pytest.mark.parametrize(
    "python_body, ts_body",
    [
        ("return self.normalize(key.strip())", "return this.normalize(key.trim());"),
        ("return self.normalize(key).lower()", "return this.normalize(key).toLowerCase();"),
        ("return lambda: self.normalize(key)", "return () => this.normalize(key);"),
        ("return self.normalize(*key)", "return this.normalize(...key);"),
    ],
)
def test_resolved_calls_with_extra_work_settle(language: Extractor, python_body: str, ts_body: str) -> None:
    target, wrapper = store_pair(language, python_body, ts_body)
    assert wrapper.analysis is not None and wrapper.analysis.forward_target is None
    assert why_skipped(wrapper, target, Settings()) == "one calls the other"
    assert why_skipped(target, wrapper, Settings()) == "one calls the other"


def test_parameter_initializers_do_not_hide_the_call(language: Extractor) -> None:
    target, wrapper = store_pair(
        language, "return self.normalize(key)", "return this.normalize(key);",
        "key=normalize_default()", "key = normalizeDefault()",
    )  # fmt: skip
    assert wrapper.analysis is not None and wrapper.analysis.forward_target is None
    assert why_skipped(wrapper, target, Settings()) == "one calls the other"


def test_python_bare_calls_resolve_only_to_unshadowed_module_functions() -> None:
    source = (
        "def normalize(key):\n    return key.strip()\n"
        "def read(key):\n    return normalize(key)\n"
        "def shadowed(key, normalize):\n    return normalize(key)\n"
        "def rebound(key):\n    from text import normalize\n    return normalize(key)\n"
        "def nested(key):\n    def normalize(value):\n        return value\n    return normalize(key)\n"
        "def declared(key):\n    global normalize\n    normalize = normalize\n    return normalize(key)\n"
        "class Store:\n    def normalize(self, key):\n        return key\n"
        "    def bare(self, key):\n        return normalize(key)\n"
    )
    found = {f.qualname: f for f in PythonExtractor().functions("source.py", source)}
    calls = {name: f.analysis.local_calls for name, f in found.items() if f.analysis}
    assert calls["source.py::read"] == ("source.py::normalize",)
    assert calls["source.py::shadowed"] == calls["source.py::rebound"] == calls["source.py::nested"] == ()
    # `global` names the module binding even when the body assigns it.
    assert calls["source.py::declared"] == ("source.py::normalize",)
    # A bare name inside a method still means the module function, never the method.
    assert calls["source.py::Store.bare"] == ("source.py::normalize",)


def test_local_calls_never_change_the_context_hash() -> None:
    target, wrapper = store_pair(PythonExtractor(), "return self.normalize(key.strip())", "")
    assert wrapper.analysis is not None and wrapper.analysis.local_calls
    pair = Candidate(new=wrapper, existing=target, similarity=1)
    without = wrapper.model_copy(update={"analysis": wrapper.analysis.model_copy(update={"local_calls": ()})})
    assert pair.context_hash == Candidate(new=without, existing=target, similarity=1).context_hash


def test_typescript_static_arrow_fields_do_not_resolve_to_instance_members() -> None:
    functions = TypeScriptExtractor().functions(
        "source.ts",
        """
class Store {
  normalize(key: string) { return key.trim(); }
  static normalize(key: string) { return key.toLowerCase(); }
  static read = (key: string) => this.normalize(key);
}
""",
    )
    instance, static, wrapper = functions
    assert wrapper.owner == "Store.static"
    assert why_skipped(wrapper, instance, Settings()) is None
    assert why_skipped(wrapper, static, Settings()) == "forwarding wrapper"


def test_adopter_search_source_shapes_preserve_overrides_and_additional_work() -> None:
    # Reduced synthetic shape from web/mobile search adapters; no private implementation is embedded.
    found = TypeScriptExtractor().functions(
        "source.ts",
        """
import { SearchSource } from 'search-sdk';
class LocalSearch extends SearchSource {
  override get ready() { return this.loaded || super.ready; }
  override candidates = () => this.items.filter(item => item.visible);
  override async query(query: string) {
    await this.hydrate();
    return super.query(query);
  }
}
""",
    )
    assert [f.name for f in found] == ["get ready", "candidates", "query"]
    assert all(f.analysis and f.analysis.declared_override and f.analysis.forward_target is None for f in found)


def test_language_evidence_reopens_a_cached_verdict(language: Extractor, store: VerdictStore) -> None:
    first, second = extract(
        language,
        "class Base:\n    def normalize(self, key):\n        return key.strip()\n"
        "class Child(Base):\n    def normalize(self, key):\n        return key.strip()\n",
        "class Base { normalize(key: string) { return key.trim(); } }"
        "class Child extends Base { normalize(key: string) { return key.trim(); } }",
    )
    first.hash = second.hash = "unchanged-body"
    pair = Candidate(new=second, existing=first, similarity=1)
    verdict = Verdict(label="separate", score=0.1, judge="offline", judge_version="1")
    store.remember(pair, verdict)
    assert store.lookup(pair, "offline", reopen_margin=0.05).verdict == verdict
    changed = second.model_copy(update={"bases": ["another::Base"]})
    assert store.lookup(pair.model_copy(update={"new": changed}), "offline", reopen_margin=0.05).verdict is None


def test_forwarding_never_crosses_repository_identity(language: Extractor) -> None:
    target, wrapper = extract(
        language,
        "class Store:\n    def normalize(self, key):\n        return key.strip()\n"
        "    def read(self, key):\n        return self.normalize(key)\n",
        "class Store { normalize(key: string) { return key.trim(); } read(key: string) { return this.normalize(key); } }",
    )
    assert why_skipped(wrapper, target, Settings()) == "forwarding wrapper"
    target.origin = Run(repository="another/project", head="a" * 40)
    assert why_skipped(wrapper, target, Settings()) is None


@pytest.mark.parametrize(
    "python, typescript",
    [
        (
            "class Store:\n    async def read(self, key):\n        return await self.normalize(key)\n",
            "class Store { async read(key: string) { return await this.normalize(key); } }",
        ),
        (
            "class Store:\n    def read(receiver, key):\n        receiver.normalize(key)\n",
            "class Store { read(key: string) { this.normalize(key); } }",
        ),
        (
            'class Store:\n    def read(self, key):\n        "Forward the request."\n        return self.normalize(key=key)\n',
            "class Store { read = (key: string) => this.normalize(key); }",
        ),
    ],
)
def test_forwarder_variants_have_an_exact_local_target(language: Extractor, python: str, typescript: str) -> None:
    [wrapper] = extract(language, python, typescript)
    assert wrapper.analysis is not None
    assert wrapper.analysis.forward_target == f"{wrapper.path}::Store.normalize"


@pytest.mark.parametrize(
    "source",
    [
        "class Store { @decorate /* binding may change */ read(key: string) { return this.normalize(key); } }",
        "class Store { read = function(key: string) { return this.normalize(key); }; }",
        "class Store { read = debounce((key: string) => this.normalize(key), 200); }",
        "class Store { constructor(private key: string) { this.normalize(key); } }",
        "class Store { read() { return; } }",
        "class Store { read(key: string) { return this.normalize?.(key); } }",
        "class Store { read(key: string) { return this?.normalize(key); } }",
        "const Store = { read(key: string) { return this.normalize(key); } };",
    ],
)
def test_typescript_uncertain_binding_or_conditional_calls_are_not_forwarders(source: str) -> None:
    [function] = TypeScriptExtractor().functions("source.ts", source)
    assert function.analysis is not None
    assert function.analysis.forward_target is None


@pytest.mark.parametrize(
    "source",
    [
        "class Store:\n    @decorate\n    def read(self, key):\n        return self.normalize(key)\n",
        "class Store:\n    def read():\n        return self.normalize(key)\n",
        "class Store:\n    def read(self, key):\n        return other.normalize(key)\n",
        "class Store:\n    def read(self, *, key=prepare()):\n        return self.normalize(key)\n",
    ],
)
def test_python_uncertain_binding_or_extra_policy_is_not_forwarding(source: str) -> None:
    [function] = PythonExtractor().functions("source.py", source)
    assert function.analysis is not None
    assert function.analysis.forward_target is None
