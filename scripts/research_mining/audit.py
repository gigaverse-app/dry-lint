"""Prepare source audits from explicit expected requests and existing observations only."""

from collections import Counter

from dry_lint.models import Candidate, evidence

from .exact_cache import canonical, sha
from .source import lexical_hints, validate_sources

SCHEMA = 1  # independent research format, not the production report/store schema
LABELS = {"separate", "duplicate", "drifted"}


def source_binding(packet: dict, candidate: Candidate, checks: list[dict]) -> dict:
    return dict(
        repository=packet["repository"],
        revision=packet["revision"],
        candidate_sha256=sha(canonical(candidate.model_dump(mode="json"))),
        source_evidence=evidence(candidate),
        context_hash=candidate.context_hash,
        source_files=checks,
    )


def valid_identity(identity: dict, binding: dict, reviewer: str) -> bool:
    if not isinstance(identity, dict):
        return False
    if type(identity.get("schema")) is not int or identity["schema"] != SCHEMA or identity.get("kind") != reviewer:
        return False
    if any(identity.get(key) != value for key, value in binding.items()):
        return False
    if any(
        not isinstance(identity.get(key), str) or not identity[key].strip()
        for key in ("judge", "version", "model", "prompt_version", "rendered_input")
    ):
        return False
    cap = identity.get("max_output_tokens", "missing")
    if cap is not None and (type(cap) is not int or cap <= 0):
        return False
    return isinstance(identity.get("request_options"), dict)


def join_observation(packet, binding, reviewer, requests, observations):
    plans = [
        (i, r)
        for i, r in enumerate(requests)
        if isinstance(r, dict)
        and r.get("id") == packet["id"]
        and isinstance(r.get("identity"), dict)
        and r["identity"].get("kind") == reviewer
    ]
    result = dict(
        reviewer=reviewer,
        state="unknown",
        reason="missing_or_ambiguous_request",
        request_indices=[i for i, _ in plans],
        observation_indices=[],
        verdict=None,
    )
    if len(plans) != 1:
        return result
    plan = plans[0][1]
    identity = plan["identity"]
    key = sha(canonical(identity))
    if not valid_identity(identity, binding, reviewer) or plan.get("request_key") != key:
        return dict(result, reason="request_contract_mismatch")
    # Exact request identity, including orientation, source files, prompt, versions, options and cap.
    matches = [(i, o) for i, o in enumerate(observations) if isinstance(o, dict) and o.get("request_key") == key]
    result.update(request_key=key, observation_indices=[i for i, _ in matches])
    if len(matches) != 1:
        return dict(result, reason="missing_or_ambiguous_observation")
    observation = matches[0][1]
    if canonical(observation.get("identity")) != canonical(identity):
        return dict(result, reason="observation_identity_mismatch")
    verdict = observation.get("verdict")
    unknown_states = {
        "unknown",
        "pending",
        "deferred",
        "disputed",
        "error",
        "unknown_no_retry",
        "unknown_usage_no_retry",
    }
    if (
        observation.get("error")
        or observation.get("state") in unknown_states
        or observation.get("status") in unknown_states
        or not isinstance(verdict, dict)
        or verdict.get("label") not in LABELS
        or not isinstance(verdict.get("why"), str)
    ):
        return dict(result, reason="recorded_error_or_missing_assessment")
    return dict(result, state="model_assessment_not_gold", reason=None, verdict=verdict)


def audit_queue(packets, repositories, cache, requests=(), observations=(), reviewers=(), hints=False):
    if not reviewers or len(set(reviewers)) != len(reviewers) or any(not r.strip() for r in reviewers):
        raise ValueError("Name distinct expected reviewers explicitly")
    ids = Counter(p["id"] for p in packets if isinstance(p, dict) and isinstance(p.get("id"), str))
    rows = []
    for index, packet in enumerate(packets):
        row = dict(
            schema=SCHEMA,
            packet_index=index,
            packet=packet,
            source_validation="unknown",
            source_checks=[],
            source_error=None,
            observations=[],
            audit_status="unknown",
            accepted_gold=False,
            gold_label=None,
            priority=3,
            disagreement_kind=None,
            navigation_hints=[],
            operation_regions=[],
            audit_tasks=[
                "Audit exact shared operation or separate contracts in source",
                "Resolve common owner, existing delegation and reachable caller contracts",
                "Record an explicit source decision elsewhere; retain dissent and related pairs",
            ],
        )
        try:
            if not isinstance(packet, dict):
                raise ValueError("Packet must be a JSON object")
            if not isinstance(packet.get("id"), str) or not packet["id"] or ids[packet["id"]] != 1:
                raise ValueError("Missing or ambiguous packet ID")
            candidate = Candidate.model_validate(packet["candidate"])
            checks = validate_sources(packet, candidate, repositories[packet["repository"]], cache)
            binding = source_binding(packet, candidate, checks)
            row.update(source_validation="passed", source_checks=checks, source_binding=binding)
            row["observations"] = [
                join_observation(packet, binding, reviewer, requests, observations) for reviewer in reviewers
            ]
            if hints:
                row["navigation_hints"] = lexical_hints(candidate)
            row["operation_regions"] = [
                dict(
                    proof,
                    operation_start=None,
                    operation_end=None,
                    operation_contract=None,
                    owner_resolution=None,
                    caller_resolution=None,
                )
                for proof in checks
            ]
        except (ValueError, KeyError, TypeError, OSError) as error:
            row.update(source_validation="failed", source_error=str(error))
        labels = {o["verdict"]["label"] for o in row["observations"] if o["verdict"] is not None}
        complete = len(row["observations"]) == len(reviewers) and all(
            o["state"] == "model_assessment_not_gold" for o in row["observations"]
        )
        row["observations_complete"] = complete
        if len(labels) > 1:
            row["disagreement_kind"] = "separate_vs_positive" if "separate" in labels else "positive_subtype"
            row["audit_tasks"].insert(0, "Resolve reviewer disagreement at operation scope")
        if complete:
            row["priority"] = (
                0 if row["disagreement_kind"] == "separate_vs_positive" else (1 if labels - {"separate"} else 2)
            )
        else:
            row["audit_tasks"].insert(0, "Resolve missing/ambiguous/error observations; unknown is not separate")
        if labels == {"separate"}:
            row["audit_tasks"].append("Verify separate contracts in source; agreement cannot accept negative gold")
        rows.append(row)
    return dict(
        schema=SCHEMA,
        provider_calls=0,
        accepted_gold=0,
        rows=rows,
        request_manifest=list(requests),
        observation_records=list(observations),
        cache=dict(hits=cache.hits, parses=cache.parses, corruptions=cache.corruptions, contract=cache.contract),
        limitations="Endpoint/source checks and explicit research request matching only; not canonical judge-cache validation. "
        "Context dependency closure, request rendering truth, semantic operations, ownership and gold require separate audits. "
        "Priorities and lexical hints never accept or exclude candidates; every input state is retained in packet.",
    )
