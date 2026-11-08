#!/usr/bin/env python3
"""Provider-free replay of source truth, .04 admissions and recorded report decisions.

Python stdlib only. Recomputes normal charges from complete functions and the exact
concept template, replays ordered admission, binds exact rendered questions to full
native bodies, and joins source assessments to observed scores. It does not call a
model or re-fit retrieval without the separately held complete backgrounds.
"""
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def rows(name):
    return [json.loads(line) for line in gzip.decompress((HERE / name).read_bytes()).splitlines() if line]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()


def qualified(function):
    owner = function.get("owner")
    return function["path"] + "::" + (owner + "." if owner else "") + function["name"]


def render(candidate, template):
    text = template
    for side in ("new", "existing"):
        function = candidate[side]
        text = text.replace("<<" + side + "_name>>", qualified(function))
        text = text.replace("<<" + side + "_code>>", function["code"])
        text = text.replace("<<" + side + "_context>>", function["context"])
    assert not candidate.get("policies"), "This frozen cohort has no configured adopter policy"
    return text


def reports(verdict):
    """73709fd report rule for this no-escalation, nondeferred diagnostic.

    Settings.duplicate_at requires label != separate plus score >= report_at.
    Report also excludes model assessments. There are no second opinions here.
    """
    if verdict is None:
        return False
    assert verdict.get("second_opinion") is None, "Unexpected escalation in frozen diagnostic"
    return (verdict.get("model_assessment") is None
            and verdict["label"] != "separate" and verdict["score"] >= 0.8)


def main():
    cases = {r["id"]: r for r in rows("cases.jsonl.gz")}
    truth = {r["id"]: r for r in rows("source-decisions.jsonl.gz")}
    answers = {(r["id"], r["kind"]): r for r in rows("answers.jsonl.gz")}
    admissions = rows("admissions.jsonl.gz")
    by_campaign = defaultdict(list)
    for admission in admissions:
        by_campaign[admission["arm"], admission["campaign"], admission["repository"], admission["revision"]].append(admission)
    template = (HERE / "concept-prompt.txt").read_text()
    admitted = {}
    for campaign in by_campaign.values():
        total = 0.0
        for ordinal, admission in enumerate(campaign, 1):
            assert admission["ordinal"] == ordinal
            cost = len(render(admission["candidate"], template)) / 2.8 * 2 / 1_000_000 + 150 * 10 / 1_000_000
            assert abs(cost - admission["normal_charge_usd"]) < 1e-10
            decision = total + cost <= 0.04
            if decision:
                total += cost
            assert decision == admission["admitted"]
            assert abs(total - admission["cumulative_usd"]) < 1e-10
            admitted[admission["id"]] = decision
    input_complete = {}
    for question in rows("questions.jsonl.gz"):
        identity = question["identity"]
        assert digest(canonical(identity)) == question["request_key"]
        case = cases[question["id"]]
        candidate = case["candidate"]
        assert digest(canonical(candidate)) == identity["candidate_sha256"]
        answer = answers[question["id"], identity["kind"]]
        assert answer["request_key"] == question["request_key"]
        complete = True
        if identity["kind"] == "claude":
            expected = render(candidate, (HERE / "shared-operations-prompt.txt").read_text())
            assert identity["rendered_input"] == expected
        else:
            state = json.loads(identity["rendered_input"])["state"]
            for side in ("new", "existing"):
                supplied = state[side + "_function"]
                native = candidate[side]["code"]
                if supplied["code_truncated"]:
                    # Preserve the actual historical contract; never call this full-body evidence.
                    assert len(native) > 8000 and supplied["code"] == native[:8000]
                    complete = False
                else:
                    assert supplied["code"] == native
        input_complete[question["id"], identity["kind"]] = complete
        source = truth[question["id"]]
        assert source["coordinator_disposition"] == "accept_scoped_review"
        for function, endpoint in zip((candidate["new"], candidate["existing"]), source["endpoints"]):
            assert digest(function["code"].encode()) == endpoint["body_sha256"]
            assert function["code"] == endpoint["exact_body"]
        assert any(admitted[reference] for reference in case["admission_ids"])
    counts, source_counts = Counter(), Counter()
    report_union, bounded_union = set(), set()
    total_usd = 0.0
    for case_id, case in cases.items():
        source = truth[case_id]
        source_counts[case["role"] + "/" + source["label"] + "/" + source["utility"]] += 1
        for kind in ("jev", "claude"):
            answer = answers[case_id, kind]
            verdict = answer.get("verdict")
            counts[case["role"] + "/" + kind + "/unknown"] += verdict is None
            if reports(verdict):
                counts[case["role"] + "/" + kind + "/reports"] += 1
                scope = "full_input_reports" if input_complete[case_id, kind] else "truncated_input_reports"
                counts[case["role"] + "/" + kind + "/" + scope] += 1
                if case["role"] == "candidate":
                    report_union.add(case_id)
                    if source["label"] == "useful-extractable" and source["utility"] == "bounded":
                        bounded_union.add(case_id)
            if answer["newly_paid"]:
                total_usd += answer["new_usd"]
    result = dict(
        cases=len(cases), questions=len(answers), campaigns=len(by_campaign), admissions=len(admissions),
        source_counts=dict(source_counts), reports=dict(counts),
        candidate_report_union=len(report_union), bounded_useful_candidate_report_union=len(bounded_union),
        full_native_questions=sum(input_complete.values()), truncated_native_questions=sum(not v for v in input_complete.values()),
        full_native_candidates=len(cases),
        input_limitation="Seven Jev questions truncate one body at 8,000 characters; all 53 Claude inputs and all 53 Candidates preserve full native functions. Raw historical observations retained; no claim all 106 questions meet full-function requirement.",
        fresh_physical_usd=round(total_usd, 8),
        semantics="Original .04 concept admission; paired Jev/context and Sonnet/operations/.80 diagnostic reports, not Haiku or actual PR emissions.",
        family_scope="3 development/34 regression candidate pairs; no fresh confirmation candidate family",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
