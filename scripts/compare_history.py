"""Paired live prompt/scheduler experiment. Packets omit judge answers; outputs contain private source.

Use --packets-only for blinded reference review. Baseline overrides retain their own prompt and output policy.
Use a separate output directory per model/budget configuration; result filenames identify prompt and scheduler.
The answer directory is shared across cohorts so --limit-usd is the whole experiment's physical ceiling.
"""

import argparse
import json
from pathlib import Path

from judge_history import MODEL, LiveAnswers, Protection, answer_key, evaluate
from replay_coverage import ReplayInput, pool

from dry_lint.judges.command import PROMPT_POLICIES
from dry_lint.settings import Escalation


def packets(payload: ReplayInput) -> list[dict]:
    rows = {}
    for ordinal, step in enumerate(payload.steps, 1):
        candidates, ranks = pool(step)
        for key, candidate in candidates.items():
            identity = answer_key(candidate, "reference-v1")
            row = rows.setdefault(
                identity,
                {
                    "id": len(rows) + 1,
                    "evidence": identity,
                    "pair": key,
                    "first_commit": ordinal,
                    "baseline": False,
                    "new": candidate.new.model_dump(),
                    "existing": candidate.existing.model_dump(),
                },
            )
            row["baseline"] |= "baseline" in ranks[key]
    return list(rows.values())


def complete_pool(payload: ReplayInput, answers: LiveAnswers) -> list[str]:
    """Account invalid paid answers as unresolved and continue independent diagnostic work, without retries."""
    failed = set()
    for step in payload.steps:
        for candidate in pool(step)[0].values():
            observation = answers.observe(candidate)
            if observation.error:
                failed.add(observation.key)
    return sorted(failed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--packets-only", action="store_true")
    parser.add_argument(
        "--complete-pool", action="store_true", help="Judge the entire development pool, outside scheduler budgets"
    )
    parser.add_argument("--per-run", type=int, default=3)
    parser.add_argument("--total", type=int, default=40)
    parser.add_argument("--total-usd", type=float, default=0.50)
    parser.add_argument("--run-usd", type=float, default=0.15)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--limit-usd", type=float, default=10)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--report-at", type=float, default=0.6)
    parser.add_argument("--baseline-report-at", type=float, default=0.6)
    parser.add_argument("--baseline-model")
    parser.add_argument("--baseline-prompt-policy", choices=list(PROMPT_POLICIES), default="shared-operations")
    parser.add_argument("--baseline-max-tokens", type=int, default=2048)
    parser.add_argument(
        "--escalate-model", help="Second opinions share exploration capacity, preserving later baseline calls"
    )
    parser.add_argument("--escalate-between", type=float, nargs=2, default=[0.4, 0.7])
    parser.add_argument("--escalate-report-at", type=float, default=0.6)
    parser.add_argument("--escalate-max-tokens", type=int, default=512)
    parser.add_argument("--reserve-usd", type=float)
    parser.add_argument("--reserve-calls", type=int)
    parser.add_argument("--exploration-per-run", type=int, default=1)
    parser.add_argument("--exploration-run-usd", type=float)
    parser.add_argument("--exploration-carry-usd", type=float, help="Bank unused pacing credit across distinct heads")
    parser.add_argument(
        "--prompt-policies",
        nargs="+",
        choices=list(PROMPT_POLICIES),
        default=["concept", "shared-operations"],
    )
    args = parser.parse_args()
    if (
        not 0 <= args.report_at <= 1
        or not 0 <= args.baseline_report_at <= 1
        or not 0 <= args.escalate_report_at <= 1
        or not 0 <= args.escalate_between[0] < args.escalate_between[1] <= 1
    ):
        parser.error("Report thresholds must be between zero and one")
    args.out.mkdir(parents=True, exist_ok=True)
    captures = {
        p.parent.name: ReplayInput.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(args.captures.glob("*/replay.json"))
    }
    for name, payload in captures.items():
        (args.out / f"{name}-packets.json").write_text(json.dumps(packets(payload), indent=2), encoding="utf-8")
    if args.packets_only:
        return
    for policy in args.prompt_policies:
        answers = LiveAnswers(
            args.answers, args.limit_usd, prompt_policy=policy, max_tokens=args.max_tokens, model=args.model
        )
        answers.settings = answers.settings.model_copy(update={"report_at": args.report_at})
        baseline = (
            LiveAnswers(
                args.answers,
                args.limit_usd,
                model=args.baseline_model,
                prompt_policy=args.baseline_prompt_policy,
                max_tokens=args.baseline_max_tokens,
            )
            if args.baseline_model
            else None
        )
        if baseline is not None:
            baseline.settings = baseline.settings.model_copy(update={"report_at": args.baseline_report_at})
        second = (
            LiveAnswers(
                args.answers,
                args.limit_usd,
                model=args.escalate_model,
                prompt_policy="shared-operations-compact",
                max_tokens=args.escalate_max_tokens,
            )
            if args.escalate_model
            else None
        )
        if second is not None:
            second.settings = second.settings.model_copy(update={"report_at": args.escalate_report_at})
        protection = Protection(
            baseline_calls=args.reserve_calls if args.reserve_calls is not None else (args.total + 1) // 2,
            baseline_usd=args.reserve_usd if args.reserve_usd is not None else args.total_usd / 2,
            exploration_per_run=args.exploration_per_run,
            exploration_run_usd=args.exploration_run_usd,
            exploration_carry_usd=args.exploration_carry_usd,
        )
        for name, payload in captures.items():
            failures = complete_pool(payload, answers) if args.complete_pool else []
            for scheduler in ("fixed", "refill", "protected"):
                result = evaluate(
                    payload,
                    answers,
                    scheduler,
                    args.per_run,
                    args.total,
                    args.run_usd,
                    args.total_usd,
                    protection=protection if scheduler == "protected" else None,
                    baseline_answers=baseline,
                    escalation_answers=second,
                    escalation=Escalation(
                        use="anthropic", between=tuple(args.escalate_between), first_at=args.report_at
                    )
                    if second
                    else None,
                )
                result["diagnostic_failures"] = failures
                (args.out / f"{name}-{policy}-{scheduler}.json").write_text(
                    json.dumps(result, indent=2), encoding="utf-8"
                )
            print(name, policy, "complete; physical usage-priced USD", answers.spent, flush=True)


if __name__ == "__main__":
    main()
