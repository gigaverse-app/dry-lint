import json

import httpx
import pytest

from dry_lint.detector import Detector
from dry_lint.judges.jev import JevJudge
from dry_lint.models import Candidate, Run, Verdict
from dry_lint.ranking import rank_candidates
from dry_lint.report import Finding, Report, as_markdown, as_text
from dry_lint.settings import Settings
from dry_lint.typescript import TypeScriptExtractor

from conftest import Repo


def test_context_follows_local_helpers_and_preserves_imports_constants_and_policy():
    source = """import { useFeedContext as sdkContext } from "native-sdk";
const allowed = new Set(["active"]);
const maybeContext = () => sdkContext();
// Only active accounts can use this context.
export function useContext(status: string) {
  return allowed.has(status) ? maybeContext() : undefined;
}
"""
    function = TypeScriptExtractor().functions("src/context.ts", source)[1]
    assert "native-sdk" in function.context
    assert 'new Set(["active"])' in function.context
    assert "Only active accounts" in function.context
    assert "maybeContext = () => sdkContext()" in function.context


@pytest.mark.parametrize(
    "boundary,reason,probability,reported",
    [
        (0, "portable", 0.9, True),
        (0.95, "platform", 0.9, False),
        (0.1, "contract", 0.35, True),
        (0.1, "boilerplate", 0.8, False),
    ],
)
def test_destinations_work_within_one_repository_and_reach_judge_and_advice(
    tmp_path,
    boundary,
    reason,
    probability,
    reported,
):
    repo = Repo(tmp_path / "app")
    repo.write("web/normalize.ts", "export function normalize(x: number) { return x > 0 ? x : 0; }")
    repo.write("native/normalize.ts", "export function normalize(x: number) { return x > 0 ? x : 0; }")
    repo.commit()
    settings = Settings.model_validate(
        {
            "consolidation": [
                {
                    "sources": ["web/*", "native/*"],
                    "path": "shared/domain",
                    "guidance": "Portable rules only",
                }
            ]
        }
    )
    detector = Detector.for_repository(repo.root, settings)
    pair = detector.pair(detector.functions[0], detector.functions[1], 1.0)
    assert pair.consolidation[0].path == "shared/domain"
    bodies = []

    def answer(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "answers": {
                    "same_concept": {"noul": 0.95},
                    "behaves_differently": {"noul": 0.1},
                    "owner": {"choice": "shared", "probabilities": {"shared": 0.6, "none": 0.4}},
                    "separate_boundary": {"noul": boundary},
                    "reason": {"choice": reason, "probabilities": {reason: probability}},
                }
            },
        )

    judge = JevJudge(api_key="test", context=True, transport=httpx.MockTransport(answer))
    verdict = judge.judge([pair], settings)[0]
    assert bodies[0]["state"]["consolidation"][0]["path"] == "shared/domain"
    assert ("shared/domain" in Finding(candidate=pair, verdict=verdict).advice()) == reported
    report = Report.build([Finding(candidate=pair, verdict=verdict)], settings, judge="jev")
    assert ("shared/domain" in as_markdown(report)) == reported


def test_context_and_destination_changes_invalidate_even_separate_cached_verdicts(store):
    extractor = TypeScriptExtractor()
    a, b = [
        extractor.functions(path, "export function x() { return sdk(); }")[0] for path in ["web/a.ts", "native/a.ts"]
    ]
    pair = Candidate(
        new=a.model_copy(update={"hash": "same", "context": "import sdk from 'web-sdk'"}),
        existing=b.model_copy(update={"hash": "same"}),
        similarity=0.8,
        similarity_reusable=True,
    )
    store.remember(pair, Verdict(label="separate", score=0.1, judge="jev"))
    changed = pair.model_copy(update={"new": pair.new.model_copy(update={"context": "import sdk from 'shared-sdk'"})})
    assert store.lookup(changed, "jev", 0.05).verdict is None
    destination = Candidate.model_validate({**pair.model_dump(), "consolidation": [{"path": "shared"}]})
    assert store.lookup(destination, "jev", 0.05).verdict is None
    moved = pair.model_copy(update={"new": pair.new.model_copy(update={"origin": Run(head="b" * 40)})})
    assert moved.context_hash == pair.context_hash


def test_ranking_reserves_shared_repository_slots_and_diversifies_file_families():
    extractor = TypeScriptExtractor()

    def pair(a, b, name, similarity):
        sides = [
            extractor.functions("src/a.ts", f"function {name}(x: number) {{ return x + 1; }}")[0].model_copy(
                update={"origin": Run(repository=repo)}
            )
            for repo in (a, b)
        ]
        return Candidate.model_validate(
            {
                "new": sides[0],
                "existing": sides[1],
                "similarity": similarity,
                "consolidation": [{"repository": "org/common", "path": "src"}],
            }
        )

    copies = [pair("org/web", "org/mobile", f"copy{i}", 1) for i in range(20)]
    common = pair("org/web", "org/common", "normalize", 0.74)
    assert common in rank_candidates([*copies, common])[:2]
    different_file = copies[0].model_copy(
        update={"new": copies[0].new.model_copy(update={"path": "src/b.ts"}), "similarity": 0.7}
    )
    assert different_file in rank_candidates([*copies, different_file])[:2]


def test_consolidation_scopes_require_both_sides_and_preserve_multiple_valid_destinations(tmp_path):
    repo = Repo(tmp_path / "app")
    for path in ["web/a.ts", "native/a.ts", "server/a.ts"]:
        repo.write(path, "export const normalize = (x: number) => Math.max(0, x);")
    repo.commit()
    settings = Settings.model_validate(
        {
            "consolidation": [
                {"sources": ["web/*", "native/*"], "path": "shared/domain"},
                {"sources": ["web/*", "native/*"], "path": "shared/utils"},
            ]
        }
    )
    detector = Detector.for_repository(repo.root, settings)
    web, native, server = [detector.find(f"{tree}/a.ts::normalize") for tree in ["web", "native", "server"]]
    assert len(detector.pair(web, native, 1).consolidation) == 2
    assert not detector.pair(web, server, 1).consolidation


def test_judge_budget_defers_uncached_pairs_without_claiming_they_are_clear(store):
    from test_judging import ScoringJudge, pair

    from dry_lint.judging import Judging
    from dry_lint.report import Report, as_markdown

    settings = Settings(max_judgements=1)
    judge = ScoringJudge("test", {"a": 0.1, "b": 0.1})
    judging = Judging(settings, judge, None, store)
    first = judging.findings([pair("a"), pair("b")])
    assert first[1].deferred and first[1].verdict is None and judge.asked == ["a"]
    report = Report.build(first, settings, judge="test", changed=2)
    assert not report.visible
    assert "deferred" in as_markdown(report)
    assert "Every changed function is the only" not in as_markdown(report)
    assert "1 deferred" in as_text(report)
    second = judging.findings([pair("a"), pair("b")])
    assert second[0].cached and not second[1].deferred


@pytest.mark.parametrize("path", ["../shared", "/shared", "C:/shared", "shared\\domain"])
def test_consolidation_destination_cannot_escape_its_repository(path):
    with pytest.raises(ValueError, match="repository-relative"):
        Settings.model_validate({"consolidation": [{"path": path}]})


def test_context_includes_variable_policy_and_marks_bounded_dependency_text():
    source = "const catalogue = " + json.dumps(list(range(4000))) + ";\n"
    source += "// Includes every configured identifier.\nexport const lookup = (x: number) => catalogue.includes(x);"
    [function] = TypeScriptExtractor().functions("src/catalogue.ts", source)
    assert "Includes every configured identifier" in function.context
    assert function.context.endswith("[context truncated]")
    assert len(function.context) < 8050


def test_changes_beyond_context_limit_invalidate_cached_verdicts(store):
    extractor = TypeScriptExtractor()
    source = "const catalogue = " + json.dumps(list(range(4000))) + ";\n"
    source += "export const lookup = (x: number) => catalogue.includes(x);"
    before = extractor.functions("src/catalogue.ts", source)[0]
    after = extractor.functions("src/catalogue.ts", source.replace("3999", "9999"))[0]
    assert before.context == after.context
    other = before.model_copy(update={"path": "src/other.ts"})
    pair = Candidate(new=before, existing=other, similarity=1)
    store.remember(pair, Verdict(label="separate", score=0.1, judge="jev"))
    assert store.lookup(pair.model_copy(update={"new": after}), "jev", 0.05).verdict is None


@pytest.mark.parametrize("homes", [["shared/<unsafe>"], ["shared/<unsafe>", "shared/domain"]])
def test_destination_text_cannot_inject_markup_into_summary_or_table(homes):
    from test_judging import pair

    findings = [
        Finding(
            candidate=Candidate.model_validate({**pair(str(i)).model_dump(), "consolidation": [{"path": home}]}),
            verdict=Verdict(label="duplicate", score=0.9, judge="jev"),
        )
        for i, home in enumerate(homes)
    ]
    markdown = as_markdown(Report.build(findings, Settings(), judge="jev"))
    assert "<unsafe>" not in markdown
    assert r"\<unsafe\>" in markdown


def test_architecture_guidance_applies_without_a_matching_destination_and_invalidates_cache(store):
    from test_judging import pair

    from dry_lint.judging import Judging

    bodies = []

    def answer(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "answers": {
                    "same_concept": {"noul": 0.95},
                    "behaves_differently": {"noul": 0.1},
                    "owner": {"choice": "shared"},
                    "separate_boundary": {"noul": 0.1},
                    "reason": {"choice": "portable"},
                }
            },
        )

    candidate = pair("adapter")
    settings = Settings()
    for guidance in ["Keep platform adapters in their app.", "Providers have independent lifetimes."]:
        judge = JevJudge(api_key="test", context=True, guidance=guidance, transport=httpx.MockTransport(answer))
        judging = Judging(settings, judge, None, store)
        assert not judging.findings([candidate])[0].cached
        assert judging.findings([candidate])[0].cached
    assert len(bodies) == 2
    assert bodies[0]["state"]["guidance"] == "Keep platform adapters in their app."
    assert bodies[0]["state"]["consolidation"] == []
