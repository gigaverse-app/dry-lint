# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E741, F403, F405, I001
"""User-authorized prior-exposed inspection quest, separate from confirmed-seed expansion."""

from bundles import *
from run_study import load_cohort, write, HERE


class InspectionQuest(Strict):
    schema_version: Literal[1] = Field(default=1, alias="schema")
    source: Source
    anchor: Candidate
    items: list[Lead] = Field(min_length=1, max_length=4)
    prior_exposed: Literal[True] = True
    confirmed_seed: Literal[False] = False
    automatic_expansion: Literal[False] = False
    authorization: str
    provider_calls: Literal[0] = 0

    @model_validator(mode="after")
    def preserve_uncertainty(self):
        fs = {}
        for l in self.items:
            if l.source != self.source or l.path[0] not in {self.anchor.new.qualname, self.anchor.existing.qualname}:
                raise ValueError("Quest lost original evidence identity")
            for f in (l.candidate.new, l.candidate.existing):
                fs[(f.qualname, digest(f.code))] = f
        if sum(token_proxy(f.code + f.context) for f in fs.values()) > 6000:
            raise ValueError("Quest exceeds source budget")
        return self


def main():
    source, fs, detector = load_cohort("bg-b6a0a81cac2732a1")
    audit = ROOT / "jobs/cross-repo-recall-audit/.lab-results"
    manifest = json.loads((audit / "disputed-source/MANIFEST.json").read_text())
    for r in manifest:
        assert sha(audit / "disputed-source" / r["path"]) == r["sha256"]
    stop = detector.find("scripts/kafka_delivery_probe.py::FaultProxy.stop")
    running = detector.find("src/backend_common/testing/kafka/contracts.py::running_consumer")
    relay = detector.find("scripts/kafka_delivery_probe.py::FaultProxy.relay")
    c = detector.pair(stop, running, detector.comparer.similarity(stop, running))
    related = detector.pair(stop, relay, detector.comparer.similarity(stop, relay))
    review_path = audit / "prior-exposed-reviews.jsonl"
    evidence = "Prior-exposed disputed extraction. running_consumer already owns shared context-manager lifetime for one task, with WAIT_SECONDS=2 and only CancelledError suppressed. FaultProxy.stop closes its listener, snapshots multiple tasks, cancels all, then gathers all with return_exceptions=True and no timeout. Different cardinality, deadlines and failure policy; no new gold or proven-false designation."
    rev = Review(
        authority="independent Codex source assessment; prior exposure disclosed",
        artifact=str(review_path),
        artifact_sha256=sha(review_path),
        row_id="60b93e8b5dddde988422d0b347e24288c19600c0475fbafa36709760761037da",
        category="disputed",
        scope="operation",
        evidence=evidence,
        inspected=[Boundary.of(f) for f in (stop, running)],
    )

    def edge(a, b, text):
        return Edge(
            left=a.qualname,
            right=b.qualname,
            kind="source-adjacent",
            artifact=str(audit / "disputed-source/MANIFEST.json"),
            artifact_sha256=sha(audit / "disputed-source/MANIFEST.json"),
            evidence=text,
        )

    first = Lead(
        candidate=c,
        source=source,
        boundaries=rev.inspected,
        path=[stop.qualname, running.qualname],
        edges=[edge(stop, running, evidence)],
        state="disputed",
        review=rev,
        uncertainty="Optional inspection only. Existing disagreement is preserved. No interchangeability, useful extraction or falsity is established.",
    )
    second = Lead(
        candidate=related,
        source=source,
        boundaries=[Boundary.of(f) for f in (stop, relay)],
        path=[stop.qualname, relay.qualname],
        edges=[
            edge(
                stop,
                relay,
                "Exact adjacent cancel-all/gather operations: FaultProxy.stop lines 67–70; FaultProxy.relay finally lines 135–137. Both cancel all tasks before gather(return_exceptions=True). Different endpoint pair; relay also owns stream closure.",
            )
        ],
        uncertainty="Candidate bounded operation only. Whole relay and stop are different lifecycle functions. No independent source assessment of extraction utility has been supplied. Preserve cancel-before-drain ordering, exception policy and writer/listener ownership.",
    )
    quest = InspectionQuest(
        source=source,
        anchor=c,
        items=[first, second],
        authorization="User explicitly authorized a wider bounded prior-exposed source inspection quest; this is not confirmation-conditioned propagation.",
    )
    write("samples/prior-exposed-quest.json", quest.model_dump(mode="json", by_alias=True))
    write("quest.schema.json", InspectionQuest.model_json_schema(by_alias=True))
    parts = [
        "# Optional prior-exposed cancellation inspection quest",
        "",
        "This is not a confirmed duplicate issue. No new gold, report, CI failure or automatic refactor is created. User-authorized inspection is separate from expansion conditioned on a confirmed seed.",
        "",
        "## Disputed pair",
        "",
        evidence,
        "",
        "## Supported but unjudged adjacent operation",
        "",
        second.edges[0].evidence,
        "",
        second.uncertainty,
        "",
        "## Already-shared context",
        "",
        "The policy adapters already delegate consumer lifetime to running_consumer. Their calls are not additional duplicate implementations. Prior source assessment locates tests/kafka/test_policy_contract.py:47 and tests/kafka/test_real_broker_policy.py:43. No historical before/after claim is made for this demonstration.",
        "",
        "## Exact evidence and source",
        "",
        f"Repository `{source.repository}`, revision `{source.revision}`, cohort `{source.cohort_id}`. Review evidence: `{review_path}`, SHA256 `{sha(review_path)}`. Full signatures and docstrings follow.",
    ]
    for f in (stop, running, relay):
        parts += [
            "",
            f"### {escaped(f.qualname)}",
            "",
            f"[Exact source]({source_url(source, f)}), body `{digest(f.code)}`.",
            "",
            "````python",
            f.code,
            "````",
        ]
    parts += [
        "",
        "Review burden is nonzero despite zero extra provider calls. A rejection of stop/running_consumer does not suppress the separate stop/relay boundary question. No recursive expansion is enabled in this quest.",
        "",
    ]
    text = "\n".join(parts)
    (HERE / "samples/prior-exposed-quest.md").write_text(text)
    unique = sum(token_proxy(f.code + f.context) for f in (stop, running, relay))
    repeated = sum(token_proxy(f.code + f.context) for f in (stop, running, stop, relay))
    write(
        "quest-metrics.json",
        {
            "kind": "prior-exposed user-authorized demonstration, not fresh blind validation",
            "items": 2,
            "disputed_pairs": 1,
            "unjudged_pairs": 1,
            "already_shared_callsite_controls": 2,
            "new_gold": 0,
            "confirmed_operations": 0,
            "source_token_proxy": unique,
            "separate_pair_source_token_proxy": repeated,
            "source_token_reuse": repeated - unique,
            "rendered_token_proxy": token_proxy(text),
            "provider_calls": 0,
            "actual_agent_minutes": None,
            "actual_tokenizer_tokens": None,
            "source": source.model_dump(),
        },
    )


if __name__ == "__main__":
    main()
