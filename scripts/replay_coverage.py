"""Offline, unit-cost scheduling experiment. Never calls a judge or writes a verdict store.

    uv run python scripts/replay_coverage.py --input /private/replay.json --out /private/result.json

Each step supplies ordered candidate files under baseline, semantic and/or deep. Baseline should contain the
current shortlist; other sources hold additional candidates. Successful simulated attempts count as examined,
not as correct judgments. Input can contain private code; output contains only identities, hashes and counts.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from dry_lint.models import Candidate, CandidatesFile, Versioned

Policy = Literal["fixed", "refill", "high-precision", "balanced", "high-recall"]
Source = Literal["baseline", "semantic", "deep"]
SCHEDULES = {
    "fixed": ("baseline",),
    "refill": ("baseline",),
    "high-precision": ("baseline",) * 8 + ("explore", "age"),
    "balanced": ("baseline", "baseline", "explore", "baseline", "age"),
    "high-recall": ("baseline", "explore", "age"),
}


class ReplayStep(BaseModel):
    run_id: str = Field(min_length=1)
    sources: dict[Source, CandidatesFile]
    judge_policy: str = "offline-v1"
    failed_keys: set[str] = Field(default_factory=set, description="Simulated failures, charged but not covered.")


class ReplayFile(Versioned):
    """Independent experimental format; production candidate schemas are embedded unchanged."""

    schema_version: Literal[1] = Field(default=1, alias="schema")


class ReplayInput(ReplayFile):
    steps: list[ReplayStep]


class ReplayState(ReplayFile):
    policy: Policy
    attempts: int = Field(default=0, ge=0)
    completed: dict[str, str] = Field(default_factory=dict, description="Pair -> last successfully examined evidence.")
    historical_pairs: set[str] = Field(default_factory=set)
    first_seen: dict[str, int] = Field(default_factory=dict)
    query_attempts: dict[str, int] = Field(default_factory=dict)
    runs: dict[str, str] = Field(default_factory=dict, description="Logical run -> exact replay input digest.")


class Selection(BaseModel):
    key: str
    query: str
    partner: str
    lane: str
    sources: list[str]
    success: bool


class StepResult(BaseModel):
    run_id: str
    repeated: bool = False
    pool: int
    cached: int
    selected: list[Selection] = Field(default_factory=list)
    covered: int
    deferred: int
    cumulative_attempts: int


class ReplayResult(ReplayFile):
    simulation: str = "Unit-cost attempts; no LLM calls, verdicts, precision or dollar estimates."
    state: ReplayState
    steps: list[StepResult]


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def evidence(candidate: Candidate, judge_policy: str) -> str:
    """Conservative exact-input reuse for the spike; not a replacement for production verdict reuse."""
    return digest(
        [
            sorted((f.qualname, f.code) for f in (candidate.new, candidate.existing)),
            candidate.context_hash,
            judge_policy,
        ]
    )


def pool(step: ReplayStep) -> tuple[dict[str, Candidate], dict[str, dict[str, int]]]:
    candidates: dict[str, Candidate] = {}
    ranks: dict[str, dict[str, int]] = {}
    functions: dict[str, str] = {}
    filters: dict[str, str | None] = {}
    origins = {snapshot.run.model_dump_json() for snapshot in step.sources.values()}
    if len(origins) > 1:
        raise ValueError("conflicting snapshot provenance: sources must describe the same run")
    for source, snapshot in step.sources.items():
        for rank, candidate in enumerate(snapshot.candidates):
            # A snapshot cannot cover two different versions of one function at once.
            for f in (candidate.new, candidate.existing):
                version = digest([f.code, f.context, f.context_digest])
                if functions.setdefault(f.qualname, version) != version:
                    raise ValueError(f"conflicting function evidence: {f.qualname}")
            key = candidate.key
            if key in filters and filters[key] != candidate.filtered:
                raise ValueError(f"conflicting suppression for pair {key}")
            filters[key] = candidate.filtered
            if candidate.filtered is not None:
                continue
            if key in candidates and evidence(candidates[key], step.judge_policy) != evidence(
                candidate, step.judge_policy
            ):
                raise ValueError(f"conflicting pair evidence: {key}")
            candidates.setdefault(key, candidate)
            ranks.setdefault(key, {}).setdefault(source, rank)
    return candidates, ranks


def choose(
    pending: set[str], candidates: dict[str, Candidate], ranks: dict[str, dict[str, int]], state: ReplayState, lane: str
) -> str | None:
    eligible = pending
    if lane == "baseline":
        eligible = {key for key in pending if "baseline" in ranks[key]}
    elif lane == "explore":
        eligible = {key for key in pending if "baseline" not in ranks[key]}
    if not eligible:
        if state.policy == "fixed":
            return None
        eligible = pending  # Empty lanes lend capacity, without losing the cross-run schedule position.

    def priority(key: str) -> tuple[int, int, int, str]:
        query = candidates[key].new.qualname
        rank = ranks[key].get("baseline", min(ranks[key].values()))
        age = state.first_seen[key] if lane == "age" else 0
        return age, state.query_attempts.get(query, 0), rank, key

    return min(eligible, key=priority)


def replay(
    steps: list[ReplayStep],
    policy: Policy = "balanced",
    per_run: int = 3,
    total: int = 30,
    state: ReplayState | None = None,
) -> ReplayResult:
    if per_run < 0 or total < 0 or policy not in SCHEDULES:
        raise ValueError("budgets must be nonnegative and policy must name a known schedule")
    state = state.model_copy(deep=True) if state is not None else ReplayState(policy=policy)
    if state.policy != policy:
        raise ValueError("resume with the same policy; compare policies from separate ledgers")
    results = []
    for step in steps:
        candidates, ranks = pool(step)
        versions = {key: evidence(c, step.judge_policy) for key, c in candidates.items()}
        # Sets must be sorted before hashing so retries remain idempotent across processes/hash seeds.
        payload = step.model_dump(mode="json")
        payload["failed_keys"] = sorted(step.failed_keys)
        run_digest = digest(payload)
        repeated = step.run_id in state.runs
        if repeated and state.runs[step.run_id] != run_digest:
            raise ValueError(f"run_id {step.run_id!r} was already used with different evidence")
        pending = {key for key, version in versions.items() if state.completed.get(key) != version}
        cached = len(candidates) - len(pending)
        selected = []
        if not repeated:
            for key in candidates:
                state.first_seen.setdefault(key, len(state.runs))
            # Cumulative attempts include failures. A run cannot reset its campaign allowance.
            allowance = min(per_run, max(0, total - state.attempts))
            for _ in range(allowance):
                if not pending:
                    break
                schedule = SCHEDULES[policy]
                lane = schedule[state.attempts % len(schedule)]
                key = choose(pending, candidates, ranks, state, lane)
                if key is None:
                    break
                candidate = candidates[key]
                success = key not in step.failed_keys
                selected.append(
                    Selection(
                        key=key,
                        query=candidate.new.qualname,
                        partner=candidate.existing.qualname,
                        lane=lane,
                        sources=sorted(ranks[key]),
                        success=success,
                    )
                )
                state.attempts += 1
                query = candidate.new.qualname
                state.query_attempts[query] = state.query_attempts.get(query, 0) + 1
                if success:
                    # Selection is not coverage: only successful simulated completion acknowledges evidence.
                    state.completed[key] = versions[key]
                    state.historical_pairs.add(key)
                pending.remove(key)  # At most one attempt for a pair in this run, including failures.
            state.runs[step.run_id] = run_digest
        covered = sum(state.completed.get(key) == version for key, version in versions.items())
        results.append(
            StepResult(
                run_id=step.run_id,
                repeated=repeated,
                pool=len(candidates),
                cached=cached,
                selected=selected,
                covered=covered,
                deferred=len(candidates) - covered,
                cumulative_attempts=state.attempts,
            )
        )
    return ReplayResult(state=state, steps=results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resume", type=Path, help="A prior result; resumes its simulation ledger.")
    parser.add_argument("--profile", choices=list(SCHEDULES), default="balanced")
    parser.add_argument("--per-run", type=int, default=3, help="Maximum unit-cost attempts per new logical run.")
    parser.add_argument("--total", type=int, default=30, help="Maximum cumulative attempts, including resumed runs.")
    args = parser.parse_args()
    payload = ReplayInput.model_validate_json(args.input.read_text(encoding="utf-8"))
    state = ReplayResult.model_validate_json(args.resume.read_text(encoding="utf-8")).state if args.resume else None
    result = replay(payload.steps, args.profile, args.per_run, args.total, state)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(
        f"{args.profile}: {result.state.attempts} simulated attempts, "
        f"{len(result.state.historical_pairs)} distinct pairs examined"
    )


if __name__ == "__main__":
    main()
