import json

import httpx

from dry_lint.detector import Detector
from dry_lint.judges.jev import JevJudge
from dry_lint.models import Candidate, Run, Verdict
from dry_lint.report import Finding
from dry_lint.settings import Settings
from dry_lint.typescript import TypeScriptExtractor

from conftest import Repo


def test_context_follows_local_helpers_and_preserves_imports_constants_and_policy():
    source = '''import { useFeedContext as sdkContext } from "native-sdk";
const allowed = new Set(["active"]);
const maybeContext = () => sdkContext();
// Only active accounts can use this context.
export function useContext(status: string) {
  return allowed.has(status) ? maybeContext() : undefined;
}
'''
    function = TypeScriptExtractor().functions("src/context.ts", source)[1]
    assert "native-sdk" in function.context
    assert 'new Set(["active"])' in function.context
    assert "Only active accounts" in function.context
    assert "maybeContext = () => sdkContext()" in function.context


def test_destinations_work_within_one_repository_and_reach_judge_and_advice(tmp_path):
    repo = Repo(tmp_path / "app")
    repo.write("web/normalize.ts", 'export function normalize(x: number) { return x > 0 ? x : 0; }')
    repo.write("native/normalize.ts", 'export function normalize(x: number) { return x > 0 ? x : 0; }')
    repo.commit()
    settings = Settings.model_validate({"consolidation": [{
        "sources": ["web/*", "native/*"], "path": "shared/domain", "guidance": "Portable rules only",
    }]})
    detector = Detector.for_repository(repo.root, settings)
    pair = detector.pair(detector.functions[0], detector.functions[1], 1.0)
    assert pair.consolidation[0].path == "shared/domain"
    bodies = []

    def answer(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"answers": {
            "same_concept": {"noul": 0.95}, "behaves_differently": {"noul": 0.1},
            "owner": {"choice": "shared", "probabilities": {"shared": 1}},
            "shareable": {"noul": 1}, "reason": {"choice": "portable"},
        }})

    judge = JevJudge(api_key="test", context=True, transport=httpx.MockTransport(answer))
    verdict = judge.judge([pair], settings)[0]
    assert bodies[0]["state"]["consolidation"][0]["path"] == "shared/domain"
    assert "shared/domain" in Finding(candidate=pair, verdict=verdict).advice()


def test_context_and_destination_changes_invalidate_even_separate_cached_verdicts(store):
    extractor = TypeScriptExtractor()
    a, b = [extractor.functions(path, 'export function x() { return sdk(); }')[0]
            for path in ["web/a.ts", "native/a.ts"]]
    pair = Candidate(new=a.model_copy(update={"hash": "same", "context": "import sdk from 'web-sdk'"}),
                     existing=b.model_copy(update={"hash": "same"}), similarity=.8, similarity_reusable=True)
    store.remember(pair, Verdict(label="separate", score=.1, judge="jev"))
    changed = pair.model_copy(update={"new": pair.new.model_copy(update={"context": "import sdk from 'shared-sdk'"})})
    assert store.lookup(changed, "jev", .05).verdict is None
    destination = Candidate.model_validate({**pair.model_dump(), "consolidation": [{"path": "shared"}]})
    assert store.lookup(destination, "jev", .05).verdict is None
    moved = pair.model_copy(update={"new": pair.new.model_copy(update={"origin": Run(head="b" * 40)})})
    assert moved.context_hash == pair.context_hash
