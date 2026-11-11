# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: E401, E402, F401, F403, F405, I001
from policy_common import *
import collections, time
import numpy as np

sys.path[:0] = [str(B), str(R)]
from bank_loader import BankLoader
import native_harness as nh
from dry_lint.models import Run
from transport_controls_v3 import add_retained, canonical
import importlib.util

# Source-based nominations made before any judge outcomes; rank is only an index into a frozen deterministic file.
REASONS = {
    3: "Both branch on a registered custom model prompt, render its template, otherwise invoke prompt_factory. Preserve provider-specific fallback parameters and return coercion; candidate operation is prompt selection, not whole completion equivalence.",
    11: "Both obtain an existing logging object or construct an empty nonstreaming file-operation logger with call identity and timestamps. Preserve type validation, absent/falsey call-id handling and the operation-specific call_type.",
    27: "Both normalize timeout objects for providers that cannot accept httpx.Timeout, using read timeout/default 600, and coerce scalar timeouts. Preserve falsey-input and provider-support behavior.",
    40: "Both ignore successful/interrupted atom commands, squash a failure, and emit a stacked error toast. Preserve browser-specific error handling and caller-specific titles; inspect whether only the generic failure branch is repeated.",
    101: "Both load the credential owner without upsert, tolerate lookup failure, inspect metadata.scim_active and reject explicitly deactivated users. Preserve each external error representation and intentional fail-open lookup behavior.",
    150: "Both obtain a community from a lookup, handle unavailable community and run async object permissions before membership mutation. Review the exact authorization boundary: stream unmute and ban removal remain distinct operations.",
    151: "Both accept JSON-like metadata, parse string representations and validate a dictionary before reading tags. Preserve malformed input and accepted shape semantics; independently repeated normalization is the question.",
    152: "Both bridge a synchronous call through an executor while copying contextvars and await a coroutine result when returned. Preserve arguments, context propagation and exception ownership.",
    255: "Both retrieve conversation state and compose ConversationInfo. Preserve search filtering versus startup state transitions; only independently repeated state-to-info assembly is nominated.",
    317: "Both own asynchronously started tasks and perform cancel/gather cleanup. Verify ownership, cancellation ordering and exception handling; shared scheduling APIs alone are insufficient.",
    607: "Both remove a project then clear its draft state and release draft uploads while waiting for observed removal. Preserve ordering, failure handling and selected-project behavior.",
    709: "Both collect uploaded attachments, enforce attachment capability constraints and build message context before submission. Preserve queued-edit versus new-send state and upload cleanup semantics.",
}
COUNTER = {
    24: "Same base64url encoding shape, but one is snapshot-cycle detection and the other a two-line convenience encoder. Tests whether tiny syntax reuse is overvalued.",
    41: "Both call EventTicket.owned_by; the ownership predicate already has a shared owner. Prefetch versus a serializer lookup may be legitimately distinct.",
    98: "Similar dictionary/string API structure spans response-format tool policy and authenticated Vertex request headers; provider contracts should remain distinct.",
}


def main():
    out = H / "campaign-v1"
    assert not out.exists()
    out.mkdir()
    options = jl(H / "ranked-novel-options.jsonl")
    selected = [
        {
            **options[n - 1],
            "shortlist_rank": n,
            "reason": why,
            "role": "novel_question" if n in REASONS else "structural_counterexample",
        }
        for n, why in {**REASONS, **COUNTER}.items()
    ]
    frozen = {
        "schema": 1,
        "status": "frozen_before_judge_outcomes",
        "selection": "Merit-ranked full-bank model admissions, source-operation review, both-cap residuals prioritized; 12 novel questions plus 3 structural counterexamples. Native-only cases explicitly marked. No pair-hash lottery.",
        "questions": selected,
        "recipe_sha256": sha(H / "POLICY-CONTRACT.json"),
        "scores_sha256": sha(H / "FIT-RESULTS.json"),
        "options_sha256": sha(H / "ranked-novel-options.jsonl"),
        "physical_research_cap_usd": 1.25,
        "provider_calls": 0,
    }
    write(H / "FROZEN-CAMPAIGN-V1.json", frozen)
    by = collections.defaultdict(list)
    for r in selected:
        by[r["cohort_id"]].append(r)
    selections = {(r["cohort_id"], r["query"]): r for r in jl(H / "selections.jsonl")}
    exports = []
    questions = []
    normals = []
    exporter_path = ROOT / ".lab-results/encoder-ensemble/export_queue.py"
    spec = importlib.util.spec_from_file_location("existing_canonical_exporter", exporter_path)
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    for cid, rs in by.items():
        folder = out / cid
        folder.mkdir()
        loader = BankLoader(cid)
        panel = loader.panel
        rows = jl(H / "arrays" / cid / "rows.jsonl")
        bank = {r["candidate_id"]: r for r in jl(D / "bank" / cid / "candidates.jsonl")}
        campaigns = []
        packets = []
        for q in sorted({r["query"] for r in rs}):
            plan = selections[cid, q]
            bound = sum(r["query"] == q and not r["filtered"] for r in rows)
            s = loader.settings.model_copy(
                update={
                    "discovery": loader.settings.discovery.model_copy(
                        update={
                            "baseline_fraction": 0.0,
                            "exploration_per_revision": 0.04,
                            "calls": max(1, bound),
                            "calls_per_revision": max(1, bound),
                            "exploration_calls_per_revision": bound,
                        }
                    )
                }
            )
            cap = {
                "cohort_id": cid,
                "repository": panel["repository"],
                "revision": panel["revision"],
                "query_positions": [q],
                "arms": {},
                "native": {},
                "arm_aliases": {
                    "minilm_stack": "raw_native_no_floor_dollar_only",
                    "fusion_combined": "combined_native_v1_dollar_only",
                },
            }
            for alias, arm in [("minilm_stack", "raw_native"), ("fusion_combined", "combined_native")]:
                ii = plan["indices"][arm]
                cs = [
                    loader.candidate(bank[rows[i]["candidate_id"]]).model_copy(update={"priority": len(ii) - n})
                    for n, i in enumerate(ii)
                ]
                run = Run(
                    repository=panel["repository"],
                    revision=panel["revision"],
                    session=f"learned-budget-v1:{cid}:{q}:{arm}",
                )
                cap["arms"][alias] = [c.model_dump(mode="json") for c in cs]
                cap["native"][alias] = nh.native(
                    cs, s, run, folder / "native" / str(q) / alias, functions=len(loader.functions)
                )
                assert all(e["admitted"] for e in cap["native"][alias]["events"])
            campaigns.append(cap)
            for arm in ["raw_dollar", "combined", "raw_count", "raw_source"]:
                ii = plan["indices"][arm]
                cs = [
                    loader.candidate(bank[rows[i]["candidate_id"]]).model_copy(update={"priority": len(ii) - n})
                    for n, i in enumerate(ii)
                ]
                normals.append(
                    {
                        "cohort_id": cid,
                        "query_positions": [q],
                        "arm": arm,
                        "settings": s.model_dump(mode="json"),
                        "candidates": [c.model_dump(mode="json") for c in cs],
                        "normal_estimate_usd": sum(nh.estimate(nh.JUDGE, [c], s) for c in cs),
                        "answers": "unknown pending root; normal-only candidate answers may require separate funding",
                    }
                )
            for r in [r for r in rs if r["query"] == q]:
                candidate = next(
                    c
                    for c in cap["arms"]["fusion_combined"]
                    if c["existing"]["path"]
                    + "::"
                    + ((c["existing"].get("owner") + ".") if c["existing"].get("owner") else "")
                    + c["existing"]["name"]
                    == r["target_source"]
                )
                c = nh.Candidate.model_validate(candidate)
                packet = {
                    **r,
                    "id": "POLICY-" + r["candidate_id"][:20],
                    "candidate": candidate,
                    "rendered_prompt": nh.JUDGE.input_text(c),
                    "rendered_prompt_sha256": digest(nh.JUDGE.input_text(c)),
                    "normal_cap": 0.04,
                    "native_cap": 0.04,
                    "funding": next(e for e in cap["native"]["fusion_combined"]["events"] if e["key"] == c.key),
                    "native_run": cap["native"]["fusion_combined"]["run"],
                    "native_settings": s.model_dump(mode="json"),
                    "database": cap["native"]["fusion_combined"]["database"],
                    "source_proof_path": panel["source_proof_path"],
                    "canonical_queue_id": "ENC-" + canonical(c)[:20],
                }
                packets.append(packet)
                questions.append(packet)
        write(
            folder / "RUN.json",
            {
                "panel": panel,
                "product_commit": REF,
                "provider_calls": 0,
                "arm_aliases": {
                    "minilm_stack": "raw_native_no_floor_dollar_only",
                    "fusion_combined": "combined_native_v1_dollar_only",
                },
                "warning": "Exporter base slot name is an adapter alias, NOT a MiniLM/deployed stack claim.",
            },
        )
        write(folder / "campaigns.jsonl", campaigns)
        sys.argv = [str(exporter_path), str(folder)]
        exporter.main()
        controls = add_retained(folder, campaigns, panel, packets)
        handoff = folder / "handoff/HANDOFF.json"
        m = json.loads(handoff.read_text())
        m.update(
            round_cap_usd=1.25,
            research_direction="learned-budget-policy",
            source_blind=False,
            selection="Frozen source-operation nominations, before provider outcomes. Complete native raw versus learned paired deltas plus retained control. Original exporter minilm_stack slot explicitly aliases raw_native_no_floor_dollar_only.",
            question="Does variable-depth learned utility allocation add useful operations versus deeper no-floor raw TFIDF at .04 normal and native caps? Normal plans separately frozen; missing answers remain unknown.",
        )
        write(handoff, m)
        exports.append(
            {
                "cohort_id": cid,
                "handoff": str(handoff),
                "sha256": sha(handoff),
                "retained_controls": controls,
                "nominated_questions": len(rs),
            }
        )
    write(H / "funded-questions.jsonl", questions)
    write(H / "normal-campaigns.jsonl", normals)
    write(
        H / "HANDOFF.json",
        {
            "schema": 1,
            "status": "READY_FOR_ROOT",
            "exports": exports,
            "ranked_source_complete_questions": str(H / "funded-questions.jsonl"),
            "frozen_campaign": str(H / "FROZEN-CAMPAIGN-V1.json"),
            "normal_campaigns": str(H / "normal-campaigns.jsonl"),
            "physical_research_cap_usd": 1.25,
            "normal_change_cap_usd": 0.04,
            "native_change_cap_usd": 0.04,
            "provider_calls": 0,
            "physical_spend_usd": 0,
            "root_transport": str(ROOT / ".lab-results/encoder-judging/wave_v4.py"),
            "important": "All export round caps share ONE aggregate physical 1.25 allowance. Canonical producer base alias is raw TFIDF, not deployed. Root may adapt existing exporter. Complete normal-policy evaluation needs all normal admitted answers; native-only paid coverage is insufficient.",
        },
    )
    print("READY", len(questions), "questions", len(exports), "exports")


if __name__ == "__main__":
    main()
