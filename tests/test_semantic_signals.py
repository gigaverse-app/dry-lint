"""Safety and meaning of the offline experiment, independent of its retrieval scores."""

import json
import runpy

import pytest

from conftest import SCRIPTS, gold_line, run_main, run_script

Signals = runpy.run_path(str(SCRIPTS / "semantic_signals.py"))["Signals"]


def trial(sources: dict[str, str]):
    return Signals(sources)


def test_import_aliases_resolve_to_the_same_api_without_importing_the_module() -> None:
    signals = trial({
        "a.py": "import nonexistent_sdk as sdk\ndef load(x):\n    return sdk.read(x)\n",
        "b.py": "from nonexistent_sdk import read as fetch\ndef load(x):\n    return fetch(x)\n",
    })
    assert signals.tokens("a.py::load", "api") == signals.tokens("b.py::load", "api") == ["api:nonexistent_sdk.read"]


@pytest.mark.parametrize("source", [
    "import sdk\ndef load(sdk):\n    return sdk.read()\n",
    "import sdk\ndef load():\n    sdk = factory()\n    return sdk.read()\n",
    "import sdk\nsdk = factory()\ndef load():\n    return sdk.read()\n",
    "import sdk\nfrom other import *\ndef load():\n    return sdk.read()\n",
    "import sdk\ndef load():\n    import other as sdk\n    return sdk.read()\n",
    "import sdk\nif enabled:\n    from other import *\ndef load():\n    return sdk.read()\n",
])
def test_uncertain_or_shadowed_imports_produce_no_resolved_api(source: str) -> None:
    assert trial({"a.py": source}).tokens("a.py::load", "api") == []


def test_relative_imports_and_src_layout_resolve_known_signatures() -> None:
    signals = trial({
        "src/pkg/helpers.py": "def persist(user, *, active=True):\n    return user\n",
        "src/pkg/a.py": "from .helpers import persist as save\ndef run(record):\n    return save(record.id, active=True)\n",
        "src/pkg/b.py": "from pkg.helpers import persist\ndef run(record):\n    return persist(user=record.id, active=True)\n",
    })
    assert signals.tokens("src/pkg/a.py::run", "binding") == signals.tokens("src/pkg/b.py::run", "binding")
    assert "bind:pkg.helpers.persist:user<-id" in signals.tokens("src/pkg/a.py::run", "binding")


@pytest.mark.parametrize("call", ["save(*args)", "save(**kwargs)", "save(x, user=x)", "save()", "save(bogus=x)"])
def test_ambiguous_or_invalid_calls_are_not_given_argument_bindings(call: str) -> None:
    source = f"def save(user):\n    return user\ndef run(x, args, kwargs):\n    return {call}\n"
    assert trial({"a.py": source}).tokens("a.py::run", "binding") == []


def test_decorators_and_unknown_methods_do_not_supply_assumed_signatures() -> None:
    source = "@changes_signature\ndef save(user):\n    return user\ndef run(client, x):\n    save(x)\n    return client.save(x)\n"
    assert trial({"a.py": source}).tokens("a.py::run", "binding") == []


def test_positional_only_parameters_cannot_be_bound_by_keyword() -> None:
    source = "def save(user, /):\n    return user\ndef run(x):\n    return save(user=x)\n"
    assert trial({"a.py": source}).tokens("a.py::run", "binding") == []


def test_field_relationships_preserve_direction_and_ignore_call_method_names() -> None:
    source = 'def project(row, output):\n    output.total = row["price"]\n    return transform(row.total)\n'
    assert trial({"a.py": source}).tokens("a.py::project", "flow") == ["flow:price->total", "flow:total->return"]


def test_nested_functions_do_not_leak_returns_or_bindings_into_the_parent() -> None:
    source = "import sdk\ndef outer(row):\n    def inner():\n        return sdk.read(row.secret)\n    return row.public\n"
    signals = trial({"a.py": source})
    assert signals.tokens("a.py::outer", "api") == []
    assert signals.tokens("a.py::outer", "flow") == ["flow:public->return"]


def test_unknown_and_syntactically_invalid_files_are_skipped() -> None:
    signals = trial({"broken.py": "def broken(:", "empty.py": "# empty"})
    assert signals.tokens("broken.py::broken", "api") == []


def test_duplicate_keyword_arguments_are_not_silently_collapsed() -> None:
    source = "def save(user):\n    return user\ndef run(x):\n    return save(user=x, user=x)\n"
    assert trial({"a.py": source}).tokens("a.py::run", "binding") == []


@pytest.mark.parametrize("body", [
    "try:\n        work()\n    except Exception as sdk:\n        sdk.read()",
    "global sdk\n    sdk.read()",
    "match value:\n        case {'sdk': sdk}:\n            sdk.read()",
    "match value:\n        case {**sdk}:\n            sdk.read()",
    "sdk.read = replacement\n    sdk.read()",
    "def sdk():\n        return value\n    sdk.read()",
])
def test_other_lexical_bindings_also_invalidate_aliases(body: str) -> None:
    source = f"import sdk\ndef run(value):\n    {body}\n"
    assert trial({"a.py": source}).tokens("a.py::run", "api") == []


def test_package_imports_and_class_rebinding_are_distinct() -> None:
    signals = trial({
        "pkg/__init__.py": "from . import helper\ndef run():\n    return helper.load()\n",
        "other.py": "import sdk\nclass sdk:\n    pass\ndef run():\n    return sdk.read()\n",
    })
    assert signals.tokens("pkg/__init__.py::run", "api") == ["api:pkg.helper.load"]
    assert signals.tokens("other.py::run", "api") == []


def test_imports_above_the_package_root_are_not_resolved() -> None:
    source = "from ..sdk import read\ndef run():\n    return read()\n"
    assert trial({"pkg/a.py": source}).tokens("pkg/a.py::run", "api") == []


def test_a_module_named_src_is_not_mistaken_for_a_source_directory() -> None:
    source = "import sdk\ndef run():\n    return sdk.read()\n"
    assert trial({"src.py": source}).tokens("src.py::run", "api") == ["api:sdk.read"]


def test_mapping_reads_and_computed_callees_do_not_invent_relationships() -> None:
    source = 'def run(row):\n    factory()()\n    callback = lambda: row.secret\n    return row.get("public")\n'
    signals = trial({"a.py": source})
    assert signals.tokens("a.py::run", "api") == []
    assert signals.tokens("a.py::run", "flow") == ["flow:public->return"]
    source = "def run(row):\n    return lambda: row.secret\n"
    assert trial({"a.py": source}).tokens("a.py::run", "flow") == []


def test_trial_cli_runs_each_variant_with_real_repository_and_gold(repo, tmp_path, monkeypatch) -> None:
    runner = run_script(monkeypatch, "benchmark_semantic_signals.py")["run"]
    gold = tmp_path / "gold.jsonl"
    gold.write_text(gold_line("src/widgets/caption.py::preview_caption_text", "src/text.py::shorten_text", "duplicate"))
    out = tmp_path / "trial"
    run_main(monkeypatch, "benchmark_semantic_signals.py", "--root", str(repo.root), "--out", str(out), "--gold", str(gold))
    results = json.loads((out / "results.json").read_text())
    assert results["schema"] == 1
    assert results["head"] == repo.git("rev-parse", "HEAD").strip() and not results["dirty"]
    assert set(results["variants"]) == {"baseline", "api", "binding", "flow", "combined"}
    assert results["variants"]["baseline"]["gold"][0]["check"]
    assert len(list(out.glob("*-scan.json"))) == 5
    for variant in results["variants"]:
        expected = "tfidf:2" if variant == "baseline" else f"trial-{variant}-tfidf:1"
        assert results["variants"][variant]["comparer"] == expected
        pairs = json.loads((out / f"{variant}-scan.json").read_text())
        assert all(pair["comparer"] == expected for pair in pairs)
        assert all(pair["similarity_reusable"] == (variant == "baseline") for pair in pairs)

    gold.write_text(gold.read_text().replace("src/text.py::shorten_text", "missing.py::gone"))
    with pytest.raises(ValueError, match="missing from corpus"):
        runner(repo.root, out, gold)
