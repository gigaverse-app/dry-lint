"""Meter live model judgments while replaying fixed and baseline-first discovery. Private outputs.

Reads captures from capture_history.py. Supply ANTHROPIC_API_KEY in the environment. Uses the canonical judge,
prompt, preset and price table. Never loads credentials from a repository or executes captured source.
"""

import argparse
import json
import time
from pathlib import Path

import anthropic
import httpx2
from pydantic import BaseModel, Field
from replay_coverage import ReplayInput, ReplayState, choose, digest, pool

from dry_lint.costs import PRICES
from dry_lint.judges.anthropic import AnthropicJudge
from dry_lint.judges.command import PROMPT_POLICIES, prompt
from dry_lint.models import Candidate, Verdict
from dry_lint.presets import resolve
from dry_lint.settings import Settings

MODEL = "claude-sonnet-5-5"


class Protection(BaseModel):
    """Capacity exploration may never spend; baseline work can use it on any later revision."""

    baseline_calls: int = Field(ge=0)
    baseline_usd: float = Field(ge=0)
    exploration_per_run: int = Field(default=1, ge=0)
    exploration_run_usd: float | None = Field(default=None, ge=0)
    exploration_carry_usd: float | None = Field(default=None, ge=0)


class Observation(BaseModel):
    key: str
    pair: str
    model: str
    request_id: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    usd: float
    seconds: float
    verdict: Verdict | None = None
    error: str | None = None
    error_detail: str = ""
    stop_reason: str = ""


def answer_key(candidate: Candidate, version: str, policy: str = "concept", *, template: str | None = None) -> str:
    # Orientation and the actual judge input matter, even when the unordered pair is identical.
    return digest([version, prompt(candidate, policy=policy, template=template)])


class LiveAnswers:
    def __init__(
        self,
        directory: Path,
        limit: float = 10.0,
        http_client=None,
        prompt_policy: str = "concept",
        max_tokens: int = 8000,
        model: str = MODEL,
    ) -> None:
        if model not in PRICES:
            raise ValueError("Live model needs a known price before spending")
        self.directory, self.limit = directory, limit
        directory.mkdir(parents=True, exist_ok=True)
        if list(directory.glob("*.unmetered")):
            raise ValueError("Unmetered attempt exists; reconcile it before resuming")
        self.observations = {
            p.stem: Observation.model_validate_json(p.read_text(encoding="utf-8")) for p in directory.glob("*.json")
        }
        self.response = None
        client = http_client or anthropic.DefaultHttpxClient()
        client.event_hooks.setdefault("response", []).append(self.capture_response)
        self.judge = AnthropicJudge(
            model=model, workers=1, http_client=client, prompt_policy=prompt_policy, max_tokens=max_tokens
        )
        self.judge.client = self.judge.client.with_options(max_retries=0)
        self.settings = resolve(Settings(preset="sonnet"))

    def capture_response(self, response: httpx2.Response) -> None:
        response.read()
        if response.is_success:
            self.response = response.json()

    def key(self, candidate: Candidate) -> str:
        return answer_key(candidate, self.judge.version, self.judge.prompt_policy)

    @property
    def spent(self) -> float:
        return sum(o.usd for o in self.observations.values())

    def reserve(self, candidate: Candidate) -> float:
        # Conservative UTF-8 byte bound plus framing, at the maximum price of the selected model.
        # Reserve max output even when this experiment already has an answer: same admission rule in both arms.
        tokens = len(prompt(candidate, policy=self.judge.prompt_policy).encode("utf-8")) + 1000
        input_rate, output_rate = PRICES[self.judge.model]
        return (tokens * input_rate * 1.25 + self.judge.max_tokens * output_rate) / 1_000_000

    def observe(self, candidate: Candidate) -> Observation:
        """A known paid failure is evidence of spending, never evidence that the pair is separate."""
        try:
            return self.get(candidate)
        except ValueError:
            observation = self.observations.get(self.key(candidate))
            if observation is None or observation.error is None:
                raise
            return observation

    def get(self, candidate: Candidate) -> Observation:
        key = self.key(candidate)
        if key in self.observations:
            observation = self.observations[key]
            if observation.error:
                raise ValueError(f"Previous paid attempt failed: {key}; inspect its record before retrying")
            return observation
        if self.spent + self.reserve(candidate) > self.limit:
            raise ValueError("Physical experiment allowance exhausted")
        if list(self.directory.glob("*.unmetered")):
            raise ValueError("Unmetered attempt exists; reconcile it before sending another request")
        pending_path = self.directory / f"{key}.unmetered"
        # A crash after sending must not turn unknown provider usage into a free retry on resume.
        pending_path.write_text("Request started; usage not yet persisted", encoding="utf-8")
        self.response = None
        start, verdict, failure, error_detail = time.perf_counter(), None, None, ""
        try:
            [verdict] = self.judge.judge([candidate], self.settings)
        except Exception as error:
            failure = type(error).__name__
            error_detail = str(error)
        seconds = time.perf_counter() - start
        if self.response is None:
            # Unknown provider usage is not zero cost; stop instead of making additional unmetered calls.
            (self.directory / f"{key}.unmetered").write_text(failure or "missing usage", encoding="utf-8")
            raise ValueError("Live response has no usage; experiment stopped")
        data = self.response
        model, usage = data.get("model"), data.get("usage")
        if not isinstance(usage, dict) or any(
            not isinstance(usage.get(field), int) or usage[field] < 0 for field in ("input_tokens", "output_tokens")
        ):
            (self.directory / f"{key}.unmetered").write_text("missing or invalid usage", encoding="utf-8")
            raise ValueError("Live response has invalid usage; experiment stopped")
        if model != self.judge.model:
            (self.directory / f"{key}.unmetered").write_text("unexpected returned model", encoding="utf-8")
            raise ValueError("Unexpected returned model; do not price it as the requested model")
        input_rate, output_rate = PRICES[model]
        creation, read = usage.get("cache_creation_input_tokens", 0), usage.get("cache_read_input_tokens", 0)
        usd = (
            usage["input_tokens"] * input_rate
            + usage["output_tokens"] * output_rate
            + creation * input_rate * 1.25
            + read * input_rate * 0.10
        ) / 1_000_000
        observation = Observation(
            key=key,
            pair=candidate.key,
            model=model,
            request_id=data["id"],
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cache_creation_tokens=creation,
            cache_read_tokens=read,
            usd=usd,
            seconds=seconds,
            verdict=verdict,
            error=failure,
            error_detail=error_detail,
            stop_reason=str(data.get("stop_reason", "")),
        )
        self.observations[key] = observation
        (self.directory / f"{key}.json").write_text(observation.model_dump_json(indent=2), encoding="utf-8")
        pending_path.unlink()
        if failure:
            raise ValueError(f"Paid judgment failed: {failure}; usage recorded")
        return observation


def judge_manifest(answers: LiveAnswers) -> dict:
    return {
        "judge": answers.judge.version,
        "prompt_policy": answers.judge.prompt_policy,
        "prompt_template": PROMPT_POLICIES[answers.judge.prompt_policy][1],
        "report_at": answers.settings.report_at,
    }


def judge_for_result(ranks: dict[str, int], result: dict) -> dict:
    config = result.get("baseline_judge") if "baseline" in ranks else None
    return config if config is not None else result


def key_for_result(candidate: Candidate, ranks: dict[str, int], result: dict) -> str:
    config = judge_for_result(ranks, result)
    return answer_key(
        candidate, config["judge"], config.get("prompt_policy", "concept"), template=config.get("prompt_template")
    )


def evaluate(
    payload: ReplayInput,
    answers: LiveAnswers,
    policy: str,
    per_run: int = 10,
    total: int = 40,
    run_usd: float = 0.15,
    total_usd: float = 0.50,
    protection: Protection | None = None,
    baseline_answers: LiveAnswers | None = None,
) -> dict:
    if policy not in ("fixed", "refill", "protected") or min(per_run, total, run_usd, total_usd) < 0:
        raise ValueError("Use fixed/refill/protected and nonnegative budgets")
    if policy == "protected" and protection is None:
        protection = Protection(baseline_calls=(total + 1) // 2, baseline_usd=total_usd / 2)
    if protection and (
        policy != "protected" or protection.baseline_calls > total or protection.baseline_usd > total_usd
    ):
        raise ValueError("Protected capacity must fit the campaign budget and use the protected policy")
    if protection and protection.exploration_carry_usd is not None and protection.exploration_run_usd is None:
        raise ValueError("Carried exploration credit requires a per-revision dollar allowance")
    if baseline_answers is not None:
        if (
            baseline_answers.directory.resolve() != answers.directory.resolve()
            or baseline_answers.limit != answers.limit
        ):
            raise ValueError("Mixed judges must share one physical answer directory and allowance")
        # Both clients spend from one physical ledger; independent snapshots would undercount later calls.
        answers.observations.update(baseline_answers.observations)
        baseline_answers.observations = answers.observations
    state = ReplayState(policy="fixed" if policy == "fixed" else "refill")
    spent, exploration_spent, exploration_attempts, curves = 0.0, 0.0, 0, []
    baseline_query_attempts = {}
    failed_answers = set()
    exploration_credit, credited_revisions = 0.0, set()
    for ordinal, step in enumerate(payload.steps):
        raw = step.model_dump(mode="json")
        raw["failed_keys"] = sorted(step.failed_keys)
        run_digest = digest(raw)
        repeated = step.run_id in state.runs
        if repeated and state.runs[step.run_id] != run_digest:
            raise ValueError("Logical run identity was reused for different evidence")
        revision = next(iter(step.sources.values())).run.head or step.run_id
        if protection and protection.exploration_carry_usd is not None and revision not in credited_revisions:
            assert protection.exploration_run_usd is not None, "A carry bank requires a per-revision allowance"
            exploration_credit = min(
                protection.exploration_carry_usd, exploration_credit + protection.exploration_run_usd
            )
            credited_revisions.add(revision)
        candidates, ranks = pool(step)
        routes = {
            k: baseline_answers if baseline_answers is not None and "baseline" in ranks[k] else answers
            for k in candidates
        }
        keys = {k: routes[k].key(c) for k, c in candidates.items()}
        pending = {k for k in candidates if state.completed.get(k) != keys[k] and keys[k] not in failed_answers}
        for key in candidates:
            state.first_seen.setdefault(key, ordinal)
        selected, run_spent, run_seconds, run_exploration = [], 0.0, 0.0, 0
        run_exploration_usd = 0.0
        stopped_reason = "repeated_run" if repeated else "campaign_calls" if state.attempts >= total else "run_calls"
        for _ in range(0 if repeated else min(per_run, total - state.attempts)):
            baseline = {k for k in pending if "baseline" in ranks[k]}
            # Protect the current baseline before cost filtering. An expensive baseline item must not
            # silently donate its slot to cheaper exploration. Future revisions need a separate reserve.
            eligible = baseline or (pending if policy != "fixed" else set())
            if not eligible:
                stopped_reason = "pool_complete" if not pending else "fixed_pool_complete"
                break
            room = min(run_usd - run_spent, total_usd - spent)
            if not baseline and protection:
                # Never borrow baseline capacity for exploration, even on an empty early baseline.
                if exploration_attempts >= total - protection.baseline_calls:
                    stopped_reason = "exploration_call_reserve"
                    break
                if run_exploration >= protection.exploration_per_run:
                    stopped_reason = "exploration_pacing"
                    break
                room = min(room, total_usd - protection.baseline_usd - exploration_spent)
                if protection.exploration_run_usd is not None:
                    pacing_room = (
                        exploration_credit
                        if protection.exploration_carry_usd is not None
                        else protection.exploration_run_usd - run_exploration_usd
                    )
                    room = min(room, pacing_room)
            affordable = {k for k in eligible if routes[k].reserve(candidates[k]) <= room}
            if not affordable:
                stopped_reason = "baseline_request_does_not_fit" if baseline else "exploration_request_does_not_fit"
                break
            chooser = (
                state.model_copy(update={"query_attempts": baseline_query_attempts})
                if baseline and protection
                else state
            )
            key = choose(affordable, candidates, ranks, chooser, "baseline")
            if key is None:
                break
            c = candidates[key]
            observation = routes[key].observe(c)
            state.attempts += 1
            if observation.verdict is None:
                failed_answers.add(keys[key])
            else:
                state.completed[key] = keys[key]
            state.historical_pairs.add(key)
            state.query_attempts[c.new.qualname] = state.query_attempts.get(c.new.qualname, 0) + 1
            if baseline:
                baseline_query_attempts[c.new.qualname] = baseline_query_attempts.get(c.new.qualname, 0) + 1
            else:
                exploration_attempts += 1
                run_exploration += 1
                exploration_spent += observation.usd
                run_exploration_usd += observation.usd
                if protection and protection.exploration_carry_usd is not None:
                    exploration_credit -= observation.usd
            spent += observation.usd
            run_spent += observation.usd
            run_seconds += observation.seconds
            selected.append(
                {
                    "key": key,
                    "answer": observation.key,
                    "usd": observation.usd,
                    "sources": sorted(ranks[key]),
                    "error": observation.error,
                }
            )
            pending.remove(key)
        state.runs[step.run_id] = run_digest
        current = {k: state.completed[k] for k in candidates if state.completed.get(k) == keys[k]}
        reports = [
            k
            for k, v in current.items()
            if answers.observations[v].verdict.label != "separate"
            and answers.observations[v].verdict.score >= routes[k].settings.report_at
        ]
        curves.append(
            {
                "run_id": step.run_id,
                "head": next(iter(step.sources.values())).run.head,
                "pool": len(candidates),
                "covered": current,
                "reported": reports,
                "selected": selected,
                "deferred": len(candidates) - len(current),
                "cumulative_attempts": state.attempts,
                "run_usd": run_spent,
                "cumulative_usd": spent,
                "serial_api_seconds": run_seconds,
                "exploration_attempts": exploration_attempts,
                "exploration_usd": exploration_spent,
                "exploration_credit_usd": exploration_credit,
                "repeated": repeated,
                "stopped_reason": stopped_reason,
            }
        )
        print(policy, step.run_id.split("/")[-1][:8], len(selected), "new answers", f"${spent:.5f}", flush=True)
    return {
        "policy": policy,
        "per_run": per_run,
        "total": total,
        "run_usd": run_usd,
        "total_usd": total_usd,
        **judge_manifest(answers),
        "baseline_judge": judge_manifest(baseline_answers) if baseline_answers is not None else None,
        "protection": protection.model_dump() if protection else None,
        "curves": curves,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit-usd", type=float, default=10.0)
    parser.add_argument("--per-run", type=int, default=10)
    parser.add_argument("--total", type=int, default=40)
    parser.add_argument("--run-usd", type=float, default=0.15)
    parser.add_argument("--total-usd", type=float, default=0.50)
    parser.add_argument("--prompt-policy", choices=["concept", "shared-operations"], default="concept")
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--policies", nargs="+", choices=["fixed", "refill", "protected"], default=["fixed", "refill"])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if list((args.out / "answers").glob("*.unmetered")):
        raise ValueError("Unmetered attempt exists; reconcile it before resuming")
    answers = LiveAnswers(
        args.out / "answers", args.limit_usd, prompt_policy=args.prompt_policy, max_tokens=args.max_tokens
    )
    for path in sorted(args.captures.glob("*/replay.json")):
        payload = ReplayInput.model_validate_json(path.read_text(encoding="utf-8"))
        for policy in args.policies:
            result = evaluate(payload, answers, policy, args.per_run, args.total, args.run_usd, args.total_usd)
            (args.out / f"{path.parent.name}-{policy}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Physical live usage-priced cost:", answers.spent, flush=True)


if __name__ == "__main__":
    main()
