import textwrap

import pytest

from dry_lint.detector import Detector, changed_lines, touched, why_skipped
from dry_lint.models import Run
from dry_lint.plugins import load
from dry_lint.report import function_link
from dry_lint.settings import PluginChoice, Settings

from conftest import Repo


@pytest.fixture
def extractor():
    return load("extractors", PluginChoice(use="typescript"))


def test_extracts_named_implementations_and_preserves_locations(extractor):
    source = textwrap.dedent('''\
        interface Shape { render(): string }
        declare function external(): void;
        export function truncate(text: string) {
          function nested() { return text.trim(); }
          return nested();
        }
        export const shorten = (text: string): string => text.trim();
        class Formatter {
          format(text: string) { return text.trim(); }
          clean = (text: string) => text.trim();
        }
        const tools = { clean(text: string) { return text.trim(); } };
        export default function(text: string) { return text.trim(); }
    ''')
    found = extractor.functions("src/text.ts", source)
    assert [f.qualname for f in found] == [
        "src/text.ts::truncate", "src/text.ts::shorten", "src/text.ts::Formatter.format",
        "src/text.ts::Formatter.clean", "src/text.ts::tools.clean", "src/text.ts::default",
    ]
    assert (found[0].line, found[0].end_line) == (3, 6)
    assert "function nested" in found[0].code
    assert all(f.tokens for f in found)


@pytest.mark.parametrize("path", ["src/text.ts", "src/text.mts", "src/text.cts"])
def test_tokens_describe_runtime_behavior_not_types_or_comments(extractor, path):
    source = '''export const loadInvoice = async (client: SecretClient): Promise<SecretInvoice> => {
      // fictionalCall() and SecretAnnotation are not behavior
      const message = "otherCall() SecretProse";
      try { return await client.fetchInvoice({ invoiceId: client.invoiceId }); }
      catch (error) { return client.cachedInvoice; }
    };'''
    function = extractor.functions(path, source)[0]
    assert function.calls == []  # client.fetchInvoice is another object's method: a token, not a direct call
    assert {"call:fetchinvoice", "attr:cachedinvoice", "key:invoiceId", "ctl:await", "ctl:try"} <= set(function.tokens)
    assert not any("secret" in token or "fictional" in token or "othercall" in token for token in function.tokens)


def test_functions_that_both_call_a_builtin_method_are_judged_not_taken_as_delegating(extractor):
    """INVARIANT: two functions are "one calls the other" only when one provably calls the other, not a shared method."""
    [trim] = extractor.functions("src/a.ts", "export function trim(value: string) {\n  return value.trim().toLowerCase();\n}")
    [normalize] = extractor.functions("src/b.ts", "export function normalize(value: string) {\n  return value.trim().toLowerCase();\n}")
    assert trim.calls == normalize.calls == []
    assert why_skipped(trim, normalize, Settings()) is None
    [method] = extractor.functions("src/d.ts", "class Text {\n  clean(value: string) {\n    return this.trim(value);\n  }\n}")
    assert method.calls == ["this.trim"]


def test_an_imported_function_of_the_same_name_is_judged_not_taken_as_delegation(extractor):
    """INVARIANT: a bare call is not resolved to a symbol, so calling an imported `normalize` proves nothing."""
    [normalize] = extractor.functions("src/a.ts", "export function normalize(value: string) {\n  return value.trim().toLowerCase();\n}")
    [clean] = extractor.functions("src/b.ts", 'import { normalize } from "third-party";\n'
                                  "export function clean(value: string) {\n  return normalize(value).trim().toLowerCase();\n}")
    assert clean.calls == ["normalize"]
    assert why_skipped(clean, normalize, Settings()) is None
    [shadowing] = extractor.functions("src/c.ts", "export function clean(value: string, normalize: (v: string) => string) {\n"
                                      "  return normalize(value).trim();\n}")
    assert why_skipped(shadowing, normalize, Settings()) is None


def test_tsx_wrapped_components_keep_their_exported_identity(extractor):
    source = '''export const InvoiceCard = memo(({ invoice }: Props) => {
      return <article title={invoice.title}><Price cents={invoice.cents} /></article>;
    });'''
    function = extractor.functions("src/card.tsx", source)[0]
    assert function.name == "InvoiceCard"
    assert {"attr:title", "attr:cents", "jsx:article", "jsx:Price"} <= set(function.tokens)
    assert "memo" in function.code


def test_structure_hash_ignores_cosmetics_but_preserves_runtime_meaning(extractor):
    def fingerprint(source):
        return extractor.structure_hash(extractor.functions("text.ts", source)[0])

    original = "const clean = (text: string) => { return text.trim(); };"
    cosmetic = "const clean=(text: SomeOtherType)=>{ /* comment */ return text.trim() }"
    assert fingerprint(original) == fingerprint(cosmetic)
    for changed in [
        original.replace("trim()", "trimStart()"),
        original.replace("return text.trim()", 'return text.trim() + "!"'),
        original.replace("text.trim()", "other.trim()"),
        original.replace("(text:", "async (text:"),
    ]:
        assert fingerprint(original) != fingerprint(changed)


def test_declarations_are_skipped_and_valid_siblings_survive_syntax_errors(extractor):
    source = '''declare const clean: (text: string) => string;
    function broken( {
    }
    function valid(text: string) { return text.trim(); }
    '''
    assert [f.name for f in extractor.functions("text.ts", source)] == ["valid"]
    assert extractor.functions("types.d.ts", "declare function clean(): void;") == []


def test_callbacks_and_empty_bodies_do_not_masquerade_as_helpers(extractor):
    source = '''const schema = z.string().refine(value => value.length > 0);
    const records = clients.map(client => client.fetch());
    const noop = () => { /* deliberately empty */ };
    function empty() {}
    const actual = debounce((value: string) => value.trim(), 100);
    const cast = ((value: string) => value.trim()) as Formatter;
    '''
    assert [f.name for f in extractor.functions("source.ts", source)] == ["actual", "cast"]


def test_class_members_and_accessors_have_distinct_identity_and_hashes(extractor):
    source = '''class Invoice {
      static format(value: string) { return value.trim(); }
      format(value: string) { return value.trim(); }
      get title() { return this.name; }
      set title(value: string) { this.name = value; }
      calculate() { return this.factory()(); }
    }'''
    found = extractor.functions("invoice.ts", source)
    assert [f.qualname for f in found] == ["invoice.ts::Invoice.static.format", "invoice.ts::Invoice.format",
                                          "invoice.ts::Invoice.get title", "invoice.ts::Invoice.set title",
                                          "invoice.ts::Invoice.calculate"]
    assert len({extractor.structure_hash(f) for f in found}) == len(found)


BASE_TS = '''export class Operation {
  entries(work: Work) { return attemptsFor(work).filter(a => a.revision === work.revision); }
  static of(work: Work) { return new Operation(work.id); }
}'''


@pytest.mark.parametrize("path, source", [
    ("src/ops.ts", BASE_TS + "\nclass Bulk extends Operation {\n  entries(work: Work) { return work.attempts(); }\n}"),
    ("src/bulk.ts", "import { Operation } from './ops';\nclass Bulk extends Operation<Work> {\n"
                    "  entries(work: Work) { return work.attempts(); }\n}"),
    ("src/bulk/index.ts", "import { Operation as Base } from '../ops.js';\nexport class Bulk extends Base {\n"
                          "  entries = (work: Work) => work.attempts();\n}"),
    ("src/bulk.ts", "import * as ops from './ops';\nconst Bulk = class extends ops.Operation {\n"
                    "  entries(work: Work) { return work.attempts(); }\n};"),
    ("src/bulk.ts", "import Operation from './ops';\nexport default class Bulk extends Operation {\n"
                    "  entries(work: Work) { return work.attempts(); }\n}"),
])  # fmt: skip
def test_a_method_overriding_its_extended_class_method_is_settled_by_rule(extractor, path, source):
    """INVARIANT: `class X extends Y` resolves Y from the file alone, so X's override of Y's method is settled."""
    [base] = [f for f in extractor.functions("src/ops.ts", BASE_TS) if f.name == "entries"]
    [override] = [f for f in extractor.functions(path, source) if f.name == "entries" and f.owner != "Operation"]
    assert why_skipped(override, base, Settings()) == why_skipped(base, override, Settings()) == "subclass override"


@pytest.mark.parametrize("source", [
    "import { Operation } from 'third-party';\nclass Bulk extends Operation {\n  entries(work: Work) { return work.attempts(); }\n}",
    "import { Operation } from './ops';\nclass Bulk extends mixin(Operation) {\n  entries(work: Work) { return work.attempts(); }\n}",
    "import { Operation } from './ops';\nclass Bulk extends Operation.Inner {\n  entries(work: Work) { return work.attempts(); }\n}",
    "import { Operation } from '../../../ops';\nclass Bulk extends Operation {\n  entries(work: Work) { return work.attempts(); }\n}",
    "import './ops';\nclass Bulk extends Operation {\n  entries(work: Work) { return work.attempts(); }\n}",
    "import { Operation } from './ops';\nclass Bulk extends Operation {\n  helpers = { entries(work: Work) { return work.attempts(); } };\n}",
    "import { Operation } from './ops';\nclass Bulk {\n  entries(work: Work) { return work.attempts(); }\n}",
])  # fmt: skip
def test_same_named_typescript_methods_without_a_resolved_base_go_to_the_judge(extractor, source):
    """INVARIANT: a package import, a mixin or an unrelated class leaves the pair to the judge."""
    [base] = [f for f in extractor.functions("src/ops.ts", BASE_TS) if f.name == "entries"]
    [method] = [f for f in extractor.functions("src/bulk.ts", source) if f.name == "entries"]
    assert why_skipped(method, base, Settings()) is None


def test_a_static_method_overrides_only_the_extended_class_static_method(extractor):
    [instance, static] = extractor.functions("src/ops.ts", BASE_TS)
    found = extractor.functions("src/bulk.ts", "import { Operation } from './ops';\nclass Bulk extends Operation {\n"
                                               "  static of(work: Work) { return new Bulk(work.id); }\n"
                                               "  of(work: Work) { return new Bulk(work.id); }\n}")
    assert [f.qualname for f in found] == ["src/bulk.ts::Bulk.static.of", "src/bulk.ts::Bulk.of"]
    assert why_skipped(found[0], static, Settings()) == "subclass override"
    assert why_skipped(found[1], static, Settings()) is None
    assert instance.name == "entries"


CALLER_TS = '''export class Operation {
  attempt(work: Work) { return this.entries(work).find(a => a.outcome !== NOT_APPLIED); }
  entries(work: Work) { return attemptsFor(work); }
  static load(id: string) { return this.create(id).fetch(); }
  static create(id: string) { return new Operation(id); }
}'''


@pytest.mark.parametrize("subclass, a, b", [
    ("class Bulk extends Operation {\n  entries(work: Work) { return work.attempts(); }\n}",
     "Bulk.entries", "Operation.attempt"),  # the base method calls the subclass's override through this
    ("class Bulk extends Operation {\n  latest(work: Work) { return this.entries(work).at(-1); }\n}",
     "Bulk.latest", "Operation.entries"),  # the subclass method calls an inherited one through this
    ("class Bulk extends Operation {\n  static create(id: string) { return new Bulk(id); }\n}",
     "Bulk.static.create", "Operation.static.load"),
    ("class Bulk extends Operation {\n  static reload(id: string) { return this.create(id).refresh(); }\n}",
     "Bulk.static.reload", "Operation.static.create"),
])  # fmt: skip
def test_a_this_call_between_a_class_and_its_extended_class_is_settled_by_rule(extractor, subclass, a, b):
    """INVARIANT: `this.name()` reaches the extended class's method, or a direct subclass's override of it."""
    found = {f.qualname.split("::")[1]: f for path, source in (
        ("src/ops.ts", CALLER_TS), ("src/bulk.ts", "import { Operation } from './ops';\n" + subclass))
        for f in extractor.functions(path, source)}  # fmt: skip
    assert why_skipped(found[a], found[b], Settings()) == why_skipped(found[b], found[a], Settings()) == "one calls the other"


@pytest.mark.parametrize("source", [
    "import { Operation } from 'third-party';\nclass Bulk extends Operation {\n  entries(work: Work) { return work.attempts(); }\n}",
    "import { Operation } from './ops';\nclass Bulk extends mixin(Operation) {\n  entries(work: Work) { return work.attempts(); }\n}",
    "import { Operation } from './ops';\nclass Middle extends Operation {}\n"
    "class Bulk extends Middle {\n  entries(work: Work) { return work.attempts(); }\n}",
    "import { Operation } from './ops';\nclass Bulk extends Operation {\n  static entries(work: Work) { return work.attempts(); }\n}",
])  # fmt: skip
def test_a_this_call_without_a_resolved_extended_class_goes_to_the_judge(extractor, source):
    """INVARIANT: a package import, a mixin, a grandparent's caller, or a static method of the name is left to the judge."""
    [caller] = [f for f in extractor.functions("src/ops.ts", CALLER_TS) if f.name == "attempt"]
    [entries] = [f for f in extractor.functions("src/bulk.ts", source) if f.name == "entries"]
    assert why_skipped(entries, caller, Settings()) is None


def test_minimum_lines_and_invalid_functions_do_not_hide_valid_neighbors():
    extractor = load("extractors", PluginChoice(use="typescript", min_lines=3))
    source = '''const short = () => 1;
    function broken() { const x = ; }
    function long() {
      return 2;
    }'''
    assert [f.name for f in extractor.functions("source.ts", source)] == ["long"]


def test_sticky_source_links_point_to_exact_commit_and_encode_paths(extractor):
    function = extractor.functions("src/price [$id].tsx", "const Price = () => <span />;")[0]
    link = function_link(function, Run(repository="acme/web", head="a" * 40))
    assert f"https://github.com/acme/web/blob/{'a' * 40}/src/price%20%5B%24id%5D.tsx#L1-L1" in link
    assert function_link(function, Run()) == r"src/price \[$id\].tsx::Price"
    assert "](" not in function_link(function, Run(repository="bad/repo)attack", head="a" * 40))
    assert "](" not in function_link(function, Run(repository="acme/web", head="main"))


def test_typescript_change_finds_existing_helper_without_python_configuration(tmp_path, extractor):
    repo = Repo(tmp_path / "bun-project")
    repo.write("package.json", '{"scripts":{"test":"bun test"}}')
    repo.write("src/original.ts", '''export function shortenText(text: string, limit: number) {
      if (text.length <= limit) return text;
      return text.slice(0, limit - 1).trimEnd() + "…";
    }''')
    for index in range(10):
        repo.write(f"src/filler{index}.ts", f"export const helper{index} = () => service.operation{index}();")
    repo.commit("main")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("src/preview.ts", '''export const previewText = (caption: string, limit: number) => {
      if (caption.length <= limit) return caption;
      return caption.slice(0, limit - 1).trimEnd() + "…";
    };''')
    repo.commit("feature")
    detector = Detector.for_repository(repo.root, Settings.load(repo.root))
    changed = touched(detector.functions, changed_lines(repo.root, "main"))
    assert [f.name for f in changed] == ["previewText"]
    pairs = detector.candidates(changed)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.existing.name == "shortenText"
    assert pair.new.hash and pair.existing.hash and pair.filtered is None
    suppressed = extractor.functions("src/preview.ts", pair.new.code.replace(
        "if (", "// dry-lint: distinct-from src/original.ts::shortenText\nif (", 1))[0]
    assert why_skipped(suppressed, pair.existing, Settings()) == "inline distinct-from"


def test_mixed_language_repository_does_not_recommend_python_as_typescript_reuse(tmp_path):
    repo = Repo(tmp_path / "mixed-project")
    repo.write("web.ts", "export const trimInvoice = (invoice: string) => invoice.trim();")
    repo.write("server.py", "def trimInvoice(invoice):\n    return invoice.trim()\n")
    repo.commit()
    settings = Settings(comparer={"use": "tfidf", "max_df": 1.0, "min_similarity_small": 0.0})
    detector = Detector.for_repository(repo.root, settings)
    assert len(detector.functions) == 2
    assert detector.neighbours(detector.find("web.ts::trimInvoice")) == []
