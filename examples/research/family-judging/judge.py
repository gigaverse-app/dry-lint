"""Family judge on the labelled pairs: one request per cluster of six functions, one structured answer of groups.

Usage: judge.py <jobs.jsonl> <answers.jsonl> [limit]

A job is one line: {"id", "slot", "label", "functions": [{"name", "code"}, ...]}. Function 1 is the changed
function and function slot+2 is the other half of the labelled pair. Needs ANTHROPIC_API_KEY and langchain-anthropic.
"""

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf8")
RULES = PROMPT[: PROMPT.index("# Output")].rstrip() + "\n"


class RefactorAction(StrEnum):
    """How the members should come to share one implementation."""

    CALL_EXISTING = "call_existing"
    EXTRACT_HELPER = "extract_helper"
    PARAMETERIZE = "parameterize"


class UngroupedKind(StrEnum):
    """Why a function is in no group."""

    UNRELATED = "unrelated"
    SHAPE_ONLY = "shape_only"
    IS_THE_SHARED_IMPLEMENTATION = "is_the_shared_implementation"
    CALLS_THE_SHARED_IMPLEMENTATION = "calls_the_shared_implementation"


class GroupMemberPromptSchema(BaseModel):
    """One function that carries out the group's operation, in whole or in a segment."""

    function: int = Field(description="The number of the function, as in its heading.")
    region: str = Field(
        description="'whole' if the whole body is the shared operation; otherwise the steps of this "
        "function that are the shared part, in a few words."
    )
    keep_apart: str = Field(
        description="Empty, unless this member carries out the operation but should not share code "
        "with the others (example script, test fixture, generated code, separate "
        "service): then the reason. Never lowers the score."
    )


class DifferenceSidePromptSchema(BaseModel):
    """The members that behave one way."""

    members: list[int] = Field(description="Function numbers that behave this way.")
    does: str = Field(description="What they do, in a few words.")


class UnexplainedDifferencePromptSchema(BaseModel):
    """A behavioural difference between members that nothing in the sources explains. Not necessarily a bug."""

    what: str = Field(description="The decision the members disagree on, in a few words.")
    sides: list[DifferenceSidePromptSchema] = Field(description="Which members do what; two or more sides.")
    consequence: str = Field(
        description="What observably happens differently. If that depends on code you cannot see, say so."
    )
    decide: str = Field(description="What the maintainers have to decide before merging the copies.")


class RefactorGroupPromptSchema(BaseModel):
    """Two or more code regions that carry out the same operation and should have one implementation."""

    operation: str = Field(
        description="One sentence naming the operation by what it does, not by what the code looks like."
    )
    decisions: list[str] = Field(
        description="The domain decisions ALL members make the same way, each as a checkable "
        "statement. These are what must stay in sync. At least one."
    )
    members: list[GroupMemberPromptSchema] = Field(description="Two or more members.")
    parameters: list[str] = Field(
        description="Differences that are a deliberate per-caller policy supported by the "
        "sources, one short line each: what would become a parameter of the "
        "shared implementation, or 'stays in caller: <what>'. May be empty."
    )
    unexplained: list[UnexplainedDifferencePromptSchema] = Field(
        description="Behavioural differences nothing in the sources explains: copies that may already have drifted. "
        "At most the five that matter most. May be empty; identical copies are still a full finding."
    )
    action: RefactorAction = Field(
        description="call_existing: one member already is the implementation and the "
        "others should call it. extract_helper: pull the shared region out. "
        "parameterize: one implementation with the differences as arguments."
    )
    owner: str = Field(
        description="For call_existing: the member number that already is the implementation. "
        "Otherwise the module path the shared implementation belongs in."
    )
    score: float = Field(
        description=(
            "Your confidence, 0 to 1, that the members carry out the same operation. NOT lowered for drift, small size, "
            "keep_apart or refactoring effort. 0.9-1.0: the same operation step for step. 0.7-0.9: same operation; some "
            "steps differ or one member does extra work around it. 0.5-0.7: probably the same operation; the contract is "
            "partly inferred. 0.3-0.5: a real overlap, but possibly only shape. Below 0.3: do not emit the group."
        )
    )


class UngroupedPromptSchema(BaseModel):
    """A function that is in no group."""

    function: int = Field(description="The number of the function, as in its heading.")
    kind: UngroupedKind = Field(
        description=(
            "is_the_shared_implementation: other input functions call it. calls_the_shared_implementation: it does its "
            "own distinct work and calls another input function for the shared step, or only forwards to it. shape_only: "
            "shares control flow, no domain decision. unrelated: shares vocabulary only."
        )
    )
    why: str = Field(description="What it shares with the others and why that is not a group, in one sentence.")


class FamilyVerdictPromptSchema(BaseModel):
    """Which of the input functions carry out the same operation and should have one implementation.

    Work out what each function does and what it delegates before grouping. Every input function appears in at least
    one group or in `ungrouped`. A cluster with no group is a normal answer. Be brief: one sentence per string.
    """

    groups: list[RefactorGroupPromptSchema] = Field(description="The groups; may be empty. Groups may overlap.")
    ungrouped: list[UngroupedPromptSchema] = Field(description="Every function that is in no group.")
    suspected_copies_elsewhere: list[str] = Field(
        description="Names the sources mention that probably repeat a "
        "group's operation but are not in the input. May be empty."
    )
    missing_information: str = Field(description="What you would want to see to be surer; 'none' if nothing.")


TOOL = FamilyVerdictPromptSchema.__name__
CALL = f"\nAnswer by calling the `{TOOL}` tool exactly once. Do not answer in text.\n"


def messages(job):
    text = "".join(
        f"\n## FUNCTION {n}: {f['name']}\n```\n{f['code'].rstrip()}\n```\n" for n, f in enumerate(job["functions"], 1)
    )
    return [
        HumanMessage(
            content=[
                {"type": "text", "text": RULES, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": text + CALL},
            ]
        )
    ]


def usage_of(raw):
    u = (raw.response_metadata or {}).get("usage") or {}
    return {
        "in": u.get("input_tokens", 0),
        "out": u.get("output_tokens", 0),
        "cw": u.get("cache_creation_input_tokens", 0) or 0,
        "cr": u.get("cache_read_input_tokens", 0) or 0,
        "thought": (raw.usage_metadata or {}).get("output_token_details", {}).get("reasoning", 0) or 0,
    }


def main():
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
    jobs = [json.loads(line) for line in open(sys.argv[1], encoding="utf8")]
    jobs = jobs[:limit]
    opts = dict(model="claude-haiku-5-5", output_config={"effort": "low"}, max_retries=4, timeout=300)
    forced = ChatAnthropic(max_tokens=6000, **opts).with_structured_output(
        FamilyVerdictPromptSchema, method="function_calling", include_raw=True
    )
    thinking = ChatAnthropic(max_tokens=10000, thinking={"type": "adaptive"}, **opts).with_structured_output(
        FamilyVerdictPromptSchema, method="function_calling", include_raw=True
    )
    path = Path(sys.argv[2])
    done = {}
    if path.exists():
        for line in open(path, encoding="utf8"):
            r = json.loads(line)
            if "error" not in r:
                done[r["id"]] = r
    out = open(path, "a", encoding="utf8")
    lock = threading.Lock()

    def one(job):
        if job["id"] in done:
            return done[job["id"]]
        t = time.time()
        rec = {"id": job["id"], "slot": job["slot"], "fallback": False}
        try:
            msgs = messages(job)
            try:
                got = thinking.invoke(msgs)
                if got["parsed"] is None:
                    got = None
            except Exception as e:
                rec["first_error"] = f"{type(e).__name__}: {str(e)[:160]}"
                got = None
            if got is None:
                rec["fallback"] = True
                got = forced.invoke(msgs)
            rec.update(**usage_of(got["raw"]), secs=round(time.time() - t, 2))
            if got["parsed"] is None:
                rec["error"] = f"unparsed: {str(got.get('parsing_error'))[:240]}"
            else:
                rec["answer"] = got["parsed"].model_dump(mode="json")
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {str(e)[:240]}"
        with lock:
            out.write(json.dumps(rec) + "\n")
            out.flush()
        return rec

    first = one(jobs[0])
    with ThreadPoolExecutor(8) as pool:
        res = [first, *pool.map(one, jobs[1:])]
    ok = [r for r in res if "answer" in r]
    print(len(res), "jobs", len(ok), "answered", sum(r["fallback"] for r in ok), "fallbacks")
    print([r.get("error") for r in res if "answer" not in r][:5])


if __name__ == "__main__":
    main()
