"""Exercise family questions through real SDK mock transport and exact source contracts, without providers."""

import json
from types import SimpleNamespace

import pytest

from dry_lint.family_judging import (
    FamilyFinding,
    FamilyJudging,
    FamilyVerdictStore,
    family_key,
    family_reservation_cost,
    record_family_response,
)
from dry_lint.family_models import (
    BoundClaim,
    CommonOperation,
    FamilyAnswer,
    FamilyMember,
    FamilyRequest,
    FamilyResponse,
    HelperInterface,
    MemberAssessment,
    SourceAnchor,
    request_from_nomination,
    validate_answer,
)
from dry_lint.family_report import FamilyReport
from dry_lint.judges.anthropic_family import PROMPT, AnthropicFamilyJudge, family_prompt
from dry_lint.models import Function
from dry_lint.operation_families import OperationRegion
from dry_lint.plugins import load
from dry_lint.settings import PluginChoice
from dry_lint.store import DirectoryStore

from conftest import claude

MODEL = "claude-sonnet-5-5"
RATES = (2.0, 10.0)


def family_request() -> FamilyRequest:
    members = []
    for index, name in enumerate(("save", "send", "display")):
        function = Function(
            path=f"{name}.py",
            name=name,
            line=10 * index + 1,
            end_line=10 * index + 6,
            code=f'def {name}(payload):\n    """Caller contract."""\n    value = normalize(payload)\n'
            '    if value is None:\n        raise ValueError("empty")\n    return encode(value)',
            context="normalize is an existing helper; cross-file callers are unresolved.",
            context_digest="full-file-digest",
        )
        anchor = SourceAnchor(
            owner_id=function.qualname,
            start_line=function.line + 2,
            end_line=function.end_line,
            source="\n".join(function.code.splitlines()[2:]),
        )
        members.append(FamilyMember(owner_id=function.qualname, function=function, operations=[anchor]))
    return FamilyRequest(nomination_version="test-native-v1", members=members)


def family_answer(request: FamilyRequest) -> FamilyAnswer:
    members = []
    for native in request.members[:2]:
        claim = BoundClaim(text="Preserve the empty-value exception before encoding.", evidence=native.operations)
        members.append(
            MemberAssessment(
                owner_id=native.owner_id,
                status="confirmed",
                reason="Independent normalization and encoding contract.",
                anchors=native.operations,
                caller_differences=claim,
                ordering=claim,
                exceptions=claim,
                existing_reuse=BoundClaim(
                    text="normalize is called; caller graph remains unknown.", evidence=native.operations
                ),
                migration=BoundClaim(
                    text="Replace this region with the proposed shared helper.", evidence=native.operations
                ),
            )
        )
    for native in request.members[2:]:
        members.append(
            MemberAssessment(owner_id=native.owner_id, status="unknown", reason="Caller policy not established.")
        )
    common = BoundClaim(
        text="Normalize, reject empty, then encode.", evidence=[m.operations[0] for m in request.members[:2]]
    )
    return FamilyAnswer(
        decision="consolidate",
        reason="One extractable operation in two independent owners.",
        members=members,
        common=CommonOperation(
            operation=common,
            shared_contract=common,
            helper=HelperInterface(
                signature=BoundClaim(text="normalize_and_encode(payload) -> bytes", evidence=common.evidence),
                inputs=common,
                outputs=common,
                side_effects=common,
            ),
        ),
    )


class Admission:
    """Test boundary only; production orchestration injects the existing shared CampaignStore adapter."""

    def __init__(self, result=0):
        self.result = result
        self.reservations = []
        self.settlements = []

    def reserve(self, request, judge, usd):
        self.reservations.append((family_key(request, judge), usd))
        return self.result

    def settle(self, reservation, usd, success):
        self.settlements.append((reservation, usd, success))
        return self.reservations[reservation][1] if usd is None else usd


def runner(tmp_path, reply=None, *, status=200, admission=None):
    request = family_request()
    if reply is None:
        reply = {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": family_answer(request).model_dump_json()}],
        }
    requests = []
    judge = load(
        "judges",
        PluginChoice(use="anthropic-family", model=MODEL),
        api_key="test",
        http_client=claude(reply, requests, status=status),
    )
    admission = admission or Admission()
    store = FamilyVerdictStore(DirectoryStore(tmp_path / "families"))
    return FamilyJudging(judge, store, admission, RATES), request, requests, admission


def test_mock_transport_to_cache_and_one_useful_report(tmp_path):
    judging, request, requests, admission = runner(tmp_path)
    finding = judging.finding(request)
    assert finding.status == "answered" and finding.reported
    assert finding.record.actual_usd == pytest.approx(0.003)
    assert admission.settlements == [(0, pytest.approx(0.003), True)]
    assert finding.charged_usd <= admission.reservations[0][1]
    payload = json.loads(requests[0].content)
    assert payload["max_tokens"] == 8192
    assert "fallbacks" not in payload
    assert len(requests) == 1
    assert judging.finding(request).status == "cached"
    assert len(requests) == len(admission.reservations) == 1
    report = FamilyReport(findings=[finding])
    assert report.consolidations == 1
    markdown = report.markdown()
    assert "Proposed helper" in markdown and "normalize\\_and\\_encode" in markdown
    assert "save.py::save:3-6" in markdown and "send.py::send:13-16" in markdown
    assert "Additional unconfirmed siblings" in markdown and "display.py::display — unknown" in markdown
    for detail in (
        "Caller differences",
        "Ordering",
        "Exceptions",
        "Existing helper/delegate",
        "Migration",
        "Shared contract",
    ):
        assert detail in markdown
    assert "normalize_and_encode" in report.text()
    assert FamilyReport.model_validate_json(report.model_dump_json()) == report
    judging.judge.close()


def test_prompt_keeps_complete_native_evidence():
    request = family_request()
    prompt = family_prompt(request)
    payload = json.loads(prompt.split("UNTRUSTED FAMILY SOURCE JSON:\n")[1])
    for native, rendered in zip(request.members, payload["members"], strict=True):
        assert rendered["function"]["code"] == native.function.code
        assert rendered["function"]["context"] == native.function.context
        assert rendered["operations"] == [a.model_dump(exclude={"source"}) for a in native.operations]
    assert "not a clique" in prompt and "EVERY supplied owner" in prompt and "untrusted" in prompt


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_owner",
        "missing_owner",
        "duplicate_owner",
        "unknown_anchor_owner",
        "wrong_text",
        "out_of_bounds",
        "subregion",
        "unbound_contract",
        "wrong_caller",
        "score_only",
    ],
)
def test_parser_rejects_unbound_or_incomplete_positive(mutation):
    request = family_request()
    answer = family_answer(request).model_dump()
    first = answer["members"][0]
    if mutation == "unknown_owner":
        first["owner_id"] = "invented"
    elif mutation == "missing_owner":
        answer["members"].pop()
    elif mutation == "duplicate_owner":
        answer["members"][1]["owner_id"] = first["owner_id"]
    elif mutation == "unknown_anchor_owner":
        first["anchors"][0]["owner_id"] = "invented"
    elif mutation == "wrong_text":
        first["anchors"][0]["source"] = "invented()"
    elif mutation == "out_of_bounds":
        first["anchors"][0]["end_line"] = 999
    elif mutation == "subregion":
        first["anchors"][0]["end_line"] -= 1
        first["anchors"][0]["source"] = "\n".join(first["anchors"][0]["source"].splitlines()[:-1])
    elif mutation == "unbound_contract":
        answer["common"]["shared_contract"]["evidence"].pop()
    elif mutation == "wrong_caller":
        first["ordering"]["evidence"] = answer["members"][1]["anchors"]
    else:
        answer = {"score": 1, "decision": "consolidate", "members": [m.owner_id for m in request.members]}
    with pytest.raises(ValueError):
        record_family_response(
            request, AnthropicFamilyJudge(model=MODEL), FamilyResponse(text=json.dumps(answer), stop_reason="end_turn")
        )


@pytest.mark.parametrize(
    "field",
    [
        "source",
        "docs",
        "context",
        "context_digest",
        "membership",
        "order",
        "operation",
        "nomination",
        "model",
        "output",
    ],
)
def test_exact_cache_misses_every_changed_question(tmp_path, field):
    judging, request, requests, _ = runner(tmp_path)
    assert judging.finding(request).reported
    changed = request.model_dump()
    first = changed["members"][0]
    judge = judging.judge
    if field == "source":
        first["function"]["code"] = first["function"]["code"].replace("payload):", "payload, strict=True):")
    elif field == "docs":
        first["function"]["code"] = first["function"]["code"].replace("Caller contract.", "Different contract.")
    elif field in {"context", "context_digest"}:
        first["function"][field] += " changed"
    elif field == "membership":
        changed["members"].pop()
    elif field == "order":
        changed["members"].reverse()
    elif field == "operation":
        first["operations"][0]["start_line"] += 1
        first["operations"][0]["source"] = "\n".join(first["operations"][0]["source"].splitlines()[1:])
    elif field == "nomination":
        changed["nomination_version"] += "-v2"
    elif field == "model":
        judge = AnthropicFamilyJudge(model="different-model")
    else:
        judge = AnthropicFamilyJudge(model=MODEL, max_tokens=4096)
    assert judging.store.lookup(FamilyRequest.model_validate(changed), judge) is None
    assert len(requests) == 1
    judging.judge.close()


@pytest.mark.parametrize("result,status", [("budget", "budget"), ("limit", "budget"), (None, "deferred")])
def test_admission_denial_never_calls_provider(tmp_path, result, status):
    judging, request, requests, admission = runner(tmp_path, admission=Admission(result))
    assert judging.finding(request).status == status
    assert not requests and not admission.settlements


def test_no_adopter_key_means_no_client_no_reservation_or_cached_positive(tmp_path):
    judging, request, requests, admission = runner(tmp_path)
    assert judging.finding(request).reported
    judge = AnthropicFamilyJudge(model=MODEL)
    result = FamilyJudging(judge, judging.store, admission, RATES).finding(request)
    assert result.status == "no_key" and not result.reported and judge._client is None
    assert len(requests) == len(admission.reservations) == 1
    assert "Family unconfirmed — no key" in FamilyReport(findings=[result]).text()
    with pytest.raises(ValueError, match="adopter"):
        judge.judge_family(request)
    judge.close()
    judging.judge.close()


@pytest.mark.parametrize(
    "reply,status,actual",
    [
        ({"stop_reason": "end_turn", "content": [{"type": "text", "text": "invalid JSON"}]}, 200, 0.003),
        ({"stop_reason": "max_tokens", "content": [{"type": "text", "text": "{}"}]}, 200, 0.003),
        ({"stop_reason": "refusal", "content": []}, 200, 0.003),
        ({"error": {"type": "overloaded_error", "message": "do not leak test credentials"}}, 529, None),
        ({"stop_reason": "end_turn", "usage": None, "content": []}, 200, None),
    ],
)
def test_failed_attempt_has_no_retries_and_retains_charge_and_response(tmp_path, reply, status, actual):
    judging, request, requests, admission = runner(tmp_path, reply, status=status)
    finding = judging.finding(request)
    assert finding.status == "failed" and not finding.reported
    assert len(requests) == 1
    assert admission.settlements == [(0, actual, False)]
    assert finding.charged_usd == (actual if actual is not None else admission.reservations[0][1])
    assert judging.store.lookup(request, judging.judge) is None
    assert "credentials" not in finding.error
    if status == 200:
        assert finding.response is not None
    judging.judge.close()


def test_provider_free_response_recording_and_safe_report(tmp_path):
    request = family_request()
    answer = family_answer(request)
    answer.common.operation.text = "<script>alert(1)</script> [link](https://evil)\n# heading"
    judge = AnthropicFamilyJudge(model=MODEL)
    response = FamilyResponse(text=answer.model_dump_json(), stop_reason="end_turn")
    record = record_family_response(request, judge, response)
    assert judge._client is None and record.actual_usd is None
    store = FamilyVerdictStore(DirectoryStore(tmp_path))
    store.remember(request, judge, record)
    assert store.lookup(request, judge) == record
    report = FamilyReport(findings=[FamilyFinding(request=request, record=record, status="answered")])
    assert "<script>" not in report.markdown() and "\\[link\\]" in report.markdown()
    assert "Response cost: unknown" in report.text()


def test_nomination_adapter_retains_utf8_columns_and_deliberate_whole_lines():
    request = family_request()
    owners = []
    for member in request.members:
        function = member.function.model_copy(deep=True)
        lines = function.code.splitlines()
        lines[2] = '    label = "é"; value = normalize(payload)'
        function.code = "\n".join(lines)
        region = OperationRegion(
            span={
                "line": function.line + 2,
                "end_line": function.line + 2,
                "column": len('    label = "é"; '.encode()),
                "end_column": len(lines[2].encode()),
            },
            code="value = normalize(payload)",
            kind="straight_run",
            statements=1,
            bindings={"v0": "value"},
        )
        owners.append(
            SimpleNamespace(
                owner_id=member.owner_id,
                function=function,
                source_id="exact-source",
                regions=[region],
                local_callers=["caller.py::caller"],
            )
        )
    nomination = SimpleNamespace(
        owners=owners, nomination_id="nomination", operation_id="operation", canonical_operation="canonical AST"
    )
    adapted = request_from_nomination(nomination)
    assert adapted.members[0].operations[0].source == '    label = "é"; value = normalize(payload)'
    assert adapted.members[0].regions[0].code == "value = normalize(payload)"
    assert adapted.members[0].local_callers == ["caller.py::caller"]
    assert adapted.canonical_operation == "canonical AST"
    assert "caller.py::caller" in family_prompt(adapted)


@pytest.mark.parametrize("rates", [(-1, 1), (float("nan"), 1), (1, float("inf"))])
def test_unbounded_pricing_is_rejected(rates):
    with pytest.raises(ValueError, match="prices"):
        family_reservation_cost(family_request(), AnthropicFamilyJudge(model=MODEL), rates)


def test_nonconsolidation_classifies_all_members_without_promoting_membership():
    request = family_request()
    answer = FamilyAnswer(
        decision="separate",
        reason="Different policies.",
        members=[
            MemberAssessment(owner_id=m.owner_id, status="rejected", reason="Independent policy.")
            for m in request.members
        ],
    )
    assert validate_answer(request, answer) == answer
    judge = AnthropicFamilyJudge(model=MODEL)
    record = record_family_response(
        request, judge, FamilyResponse(text=answer.model_dump_json(), stop_reason="end_turn")
    )
    report = FamilyReport(findings=[FamilyFinding(request=request, record=record, status="answered")])
    assert report.consolidations == 0
    assert "No confirmed consolidation" in report.text()


def test_multiline_nomination_slice_retains_original_line_endings():
    member = family_request().members[0]
    function = member.function.model_copy(update={"code": member.function.code.replace("\n", "\r\n")})
    region = OperationRegion(
        span={"line": 3, "end_line": 6, "column": 4, "end_column": 24},
        code='value = normalize(payload)\r\n    if value is None:\r\n        raise ValueError("empty")\r\n    return encode(value)',
        kind="straight_run",
        statements=4,
    )
    region.check(function)


@pytest.mark.parametrize(
    "mutation", ["coordinates", "large_owner", "large_context", "duplicate_id", "duplicate_native", "large_question"]
)
def test_invalid_or_oversized_questions_are_rejected_whole(mutation):
    payload = family_request().model_dump()
    first = payload["members"][0]
    if mutation == "coordinates":
        first["function"]["end_line"] += 1
    elif mutation == "large_owner":
        first["function"]["code"] += " " * 33000
    elif mutation == "large_context":
        first["function"]["context"] = "x" * 16001
    elif mutation == "duplicate_id":
        payload["members"][1]["owner_id"] = first["owner_id"]
        payload["members"][1]["operations"][0]["owner_id"] = first["owner_id"]
    elif mutation == "duplicate_native":
        payload["members"][1]["function"]["path"] = first["function"]["path"]
        payload["members"][1]["function"]["name"] = first["function"]["name"]
    else:
        payload["canonical_operation"] = "x" * 1_048_576
    with pytest.raises(ValueError):
        FamilyRequest.model_validate(payload)


@pytest.mark.parametrize("mutation", ["outside", "column", "source", "highlight"])
def test_operation_slice_cannot_misstate_its_owner_source(mutation):
    member = family_request().members[0]
    region = OperationRegion(
        span={"line": 3, "end_line": 3, "column": 4, "end_column": 30},
        code="value = normalize(payload)",
        kind="straight_run",
        statements=1,
    )
    if mutation == "outside":
        region.span.end_line = 99
    elif mutation == "column":
        region.span.column = 999
    elif mutation == "source":
        region.code = "invented()"
    # A valid single-line slice still needs a corresponding complete-line highlight.
    with pytest.raises(ValueError):
        FamilyMember.model_validate({**member.model_dump(), "regions": [region.model_dump()]})


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_details",
        "nonconfirmed_claims",
        "one_confirmed",
        "missing_common",
        "separate_with_common",
        "unconfirmed_common_evidence",
        "nonoperation_common_evidence",
    ],
)
def test_positive_requires_explicit_complete_extraction_contract(mutation):
    request = family_request()
    payload = family_answer(request).model_dump()
    if mutation == "missing_details":
        payload["members"][0]["exceptions"] = None
    elif mutation == "nonconfirmed_claims":
        payload["members"][0]["status"] = "unknown"
    elif mutation == "one_confirmed":
        payload["members"][1] = MemberAssessment(
            owner_id=request.members[1].owner_id, status="rejected", reason="Different policy."
        ).model_dump()
    elif mutation == "missing_common":
        payload["common"] = None
    elif mutation == "separate_with_common":
        payload["decision"] = "separate"
    elif mutation == "unconfirmed_common_evidence":
        payload["common"]["helper"]["inputs"]["evidence"].append(
            request.members[2].operations[0].model_dump(exclude={"source"})
        )
    else:
        anchor = payload["common"]["operation"]["evidence"][0]
        anchor["end_line"] -= 1
    with pytest.raises(ValueError):
        validate_answer(request, FamilyAnswer.model_validate(payload))


def test_reversed_anchor_is_rejected():
    with pytest.raises(ValueError, match="ordered"):
        SourceAnchor(owner_id="owner", start_line=3, end_line=2, source="x")


@pytest.mark.parametrize(
    "options", [{"model": ""}, {"max_tokens": 0}, {"max_tokens": 16001}, {"timeout": 0}, {"timeout": float("nan")}]
)
def test_plugin_rejects_unbounded_configuration(options):
    with pytest.raises(ValueError):
        AnthropicFamilyJudge(**{"model": MODEL, **options})


def test_executor_rejects_plugin_without_finite_output_bound():
    judge = AnthropicFamilyJudge(model=MODEL)
    judge.max_tokens = None
    with pytest.raises(ValueError, match="ceiling"):
        family_reservation_cost(family_request(), judge, RATES)


def test_cache_revalidates_stored_response_and_identity(tmp_path):
    judging, request, _, _ = runner(tmp_path)
    record = judging.finding(request).record
    backend = judging.store.backend
    for corrupted in (b"{", record.model_copy(update={"judge_version": "different"}).model_dump_json().encode()):
        backend.put(record.key, corrupted)
        assert judging.store.lookup(request, judging.judge) is None
    changed = record.model_copy(update={"request_key": "different"})
    with pytest.raises(ValueError, match="bound"):
        judging.store.remember(request, judging.judge, changed)
    with pytest.raises(ValueError, match="source-bound"):
        FamilyFinding(request=request, record=changed, status="answered")
    with pytest.raises(ValueError, match="cannot carry"):
        FamilyFinding(request=request, record=record, status="no_key")
    judging.judge.close()


def test_usage_cache_tiers_and_unknown_usage_are_accounted(tmp_path):
    request = family_request()
    reply = {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": family_answer(request).model_dump_json()}],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_creation_input_tokens": 200,
            "cache_read_input_tokens": 300,
        },
    }
    judging, request, _, admission = runner(tmp_path, reply)
    finding = judging.finding(request)
    assert finding.record.actual_usd == pytest.approx((100 * 2 + 20 * 10 + 200 * 2 * 1.25 + 300 * 2 * 0.1) / 1_000_000)
    assert FamilyReport(findings=[finding]).charged_usd == admission.settlements[0][1]
    judging.judge.close()
    reply["usage"] = None
    judging, request, _, admission = runner(tmp_path / "unknown", reply)
    finding = judging.finding(request)
    assert finding.record.actual_usd is None
    assert finding.charged_usd == admission.reservations[0][1]
    assert admission.settlements == [(0, None, True)]
    judging.judge.close()


def test_failed_family_is_unconfirmed_and_reports_charge(tmp_path):
    judging, request, _, _ = runner(tmp_path, {"stop_reason": "end_turn", "content": []})
    finding = judging.finding(request)
    text = FamilyReport(findings=[finding]).text()
    assert "Failure: ValidationError" in text and "Family unconfirmed" in text
    assert "Confirmed members" not in text
    assert finding.charged_usd > 0
    judging.judge.close()


def test_explicit_none_is_unjudged_without_claiming_missing_key():
    finding = FamilyFinding(request=family_request(), status="unjudged")
    report = FamilyReport(findings=[finding])
    assert not finding.reported and report.charged_usd == 0
    assert "Family unconfirmed — unjudged" in report.text()
    assert "no key" not in report.text()


def test_storage_metadata_is_not_paid_prompt_and_does_not_clip_full_functions():
    request = family_request()
    original_prompt = family_prompt(request)
    payload = request.model_dump()
    payload["canonical_operation"] = "canonical AST " * 20000
    revised = FamilyRequest.model_validate(payload)
    assert len(revised.model_dump_json().encode()) > 120000
    assert family_prompt(revised) == original_prompt
    assert revised.key != request.key
    judge = AnthropicFamilyJudge(model=MODEL)
    assert family_key(revised, judge) != family_key(request, judge)
    assert family_reservation_cost(revised, judge, RATES) == family_reservation_cost(request, judge, RATES)


def test_actual_prompt_byte_ceiling_rejects_whole_source_before_client(tmp_path):
    request = family_request()
    exact = len(family_prompt(request).encode("utf-8"))
    judge = AnthropicFamilyJudge(model=MODEL, api_key="test", max_input_bytes=exact)
    assert len(judge.input_text(request).encode("utf-8")) == exact
    judge.max_input_bytes -= 1
    with pytest.raises(ValueError, match="not clipped"):
        family_reservation_cost(request, judge, RATES)
    with pytest.raises(ValueError, match="not clipped"):
        judge.judge_family(request)
    assert judge._client is None
    with pytest.raises(ValueError, match="max_input_bytes"):
        AnthropicFamilyJudge(model=MODEL, max_input_bytes=1_048_577)


def test_the_prompt_names_every_detail_a_confirmed_member_must_carry():
    # The validator rejects a confirmed member missing any detail; a model only fills the keys it is told about.
    details = [name for name, field in MemberAssessment.model_fields.items() if field.annotation == BoundClaim | None]
    assert len(details) == 5
    assert all(name in PROMPT for name in details)
