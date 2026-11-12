# Frozen research implementation: retain original semantics; see PROVENANCE.json.
# ruff: noqa: F403, F405, I001
"""Question-level new/retained outcomes, exact costs, and adoption decision for frozen core."""

from policy import *
from collections import Counter
import argparse

ap = argparse.ArgumentParser()
ap.add_argument("--run", type=Path, required=True)
ap.add_argument("--require-complete", action="store_true")
a = ap.parse_args()
out = a.run.resolve()
results = jl(out / "results.jsonl")
review_path = ROOT / "jobs/refactor-discovery-bundles/.lab-results/ADAPTIVE-BLIND-REVIEW.jsonl"
reviews = jl(review_path)
questions = {}
report_cases = []
for r in results:
    payload = json.loads((out / r["cohort_id"] / str(r["query"]) / "candidates.json").read_text())
    cs = {Candidate.model_validate(c).key: Candidate.model_validate(c) for c in payload["current"] + payload["extra"]}
    fixed = {e["key"] for e in r["arms"]["fixed"]["normal"]["events"] if e["admitted"]}
    for arm, v in r["arms"].items():
        if a.require_complete:
            assert v["native"]["censored"] is None and v["normal"]["unknown_funded"] == 0
        for e in v["normal"]["events"]:
            if not e["admitted"]:
                continue
            c = cs[e["key"]]
            cached = e["recording"]
            ident = cached["identity"] if cached else None
            req = canonical(ident) if ident else canonical(c.model_dump(mode="json"))
            if req not in questions:
                endpoints = {(f.qualname, digest(f.code)) for f in [c.new, c.existing]}
                matching = [
                    rv
                    for rv in reviews
                    if rv["repository"] == v["native"]["run"]["repository"]
                    and rv["revision"] == v["native"]["run"]["revision"]
                    and {(e["fullname"], e["source_proof"]["body_sha256"]) for e in rv["source_endpoints"]} == endpoints
                ]
                questions[req] = dict(
                    id="AB-" + canonical(c.model_dump(mode="json"))[:20],
                    cohort_id=r["cohort_id"],
                    query=r["query"],
                    request_key=req,
                    role="retained" if e["key"] in fixed else "additional",
                    new=c.new.qualname,
                    existing=c.existing.qualname,
                    source_review=(
                        [
                            dict(
                                id=rv["id"],
                                category=rv["category"],
                                accepted_gold=rv["accepted_gold"],
                                rationale=rv["rationale"],
                            )
                            for rv in matching
                        ]
                        or None
                    ),
                    candidate=c.model_dump(mode="json"),
                    normal_recording=cached,
                    arms={},
                )
            questions[req]["arms"][arm] = dict(
                normal_reported=e["reported"],
                native_reported=e["key"] in v["native"]["reports"],
                normal_charge_usd=e["charge_usd"],
            )
write(out / "question-outcomes.jsonl", list(questions.values()))
role_counts = {
    role: dict(
        questions=sum(q["role"] == role for q in questions.values()),
        observed_reported=sum(
            q["role"] == role and any(v["normal_reported"] is True for v in q["arms"].values())
            for q in questions.values()
        ),
        unknown=sum(
            q["role"] == role
            and (
                not q["normal_recording"]
                or not q["normal_recording"]["verdict"]
                or bool(q["normal_recording"]["error"])
            )
            for q in questions.values()
        ),
        independent_source_review_pending=sum(
            q["role"] == role and q["source_review"] is None for q in questions.values()
        ),
    )
    for role in ["retained", "additional"]
}
normal_costs = {
    arm: sum(r["arms"][arm]["normal"]["estimated_usd"] for r in results)
    for arm in ["fixed", "uniform", "cost", "adaptive"]
}
native_costs = {arm: sum(r["arms"][arm]["native"]["actual_settled_usd"] for r in results) for arm in normal_costs}
summary = dict(
    frozen_core_sha256=sha(HERE / "returned-wave-v1/COMPLETION-CORE.json"),
    campaigns=4,
    arms=16,
    all_native_complete=all(v["native"]["censored"] is None for r in results for v in r["arms"].values()),
    all_normal_outcomes_known=all(v["normal"]["unknown_funded"] == 0 for r in results for v in r["arms"].values()),
    distinct_questions=len(questions),
    roles=role_counts,
    normal_costs=normal_costs,
    native_settled_costs=native_costs,
    native_declines=dict(
        Counter(
            e["reason"] for r in results for v in r["arms"].values() for e in v["native"]["events"] if not e["admitted"]
        )
    ),
    report_identity_preserved=all(
        set(r["arms"][arm]["native"]["reports"]) == set(r["arms"]["fixed"]["native"]["reports"])
        for r in results
        for arm in ["uniform", "cost", "adaptive"]
    ),
    normal_extra_cost_vs_fixed=normal_costs["adaptive"] - normal_costs["fixed"],
    native_extra_cost_vs_fixed=native_costs["adaptive"] - native_costs["fixed"],
    adoption_contract=dict(
        path=str(ROOT / "reports/utility-recovery/ADOPTION-CONTRACT.md"),
        sha256=sha(ROOT / "reports/utility-recovery/ADOPTION-CONTRACT.md"),
    ),
    decision="Keep current policy: no additional emitted report, hence no demonstrated two-family/two-repository useful gain; no recipe revision in this ownership scope.",
    limits="Cost-selected four single-query counterfactuals; matched historical captured stack baseline, not new raw/deeper-raw acceptance suite. Source assessments are evidence, not automatic accepted gold. Zero novel emitted reports is an outcome, not proof all unreported pairs are truly separate.",
)
write(out / "FINAL-OUTCOMES.json", summary)
print(json.dumps(summary, indent=2))
