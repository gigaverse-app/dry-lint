"""Paired live prompt/scheduler experiment. Packets omit judge answers; outputs contain private source.

Use --packets-only for blinded reference review. Both prompt arms use the same output limit and allowances.
The answer directory is shared across cohorts so --limit-usd is the whole experiment's physical ceiling.
"""

import argparse
import json
from pathlib import Path

from judge_history import LiveAnswers, answer_key, evaluate
from replay_coverage import ReplayInput, pool


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
    parser.add_argument(
        "--prompt-policies",
        nargs="+",
        choices=["concept", "shared-operations"],
        default=["concept", "shared-operations"],
    )
    args = parser.parse_args()
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
        answers = LiveAnswers(args.answers, args.limit_usd, prompt_policy=policy, max_tokens=args.max_tokens)
        for name, payload in captures.items():
            if args.complete_pool:
                for step in payload.steps:
                    for candidate in pool(step)[0].values():
                        answers.get(candidate)
            for scheduler in ("fixed", "refill", "protected"):
                result = evaluate(payload, answers, scheduler, args.per_run, args.total, args.run_usd, args.total_usd)
                (args.out / f"{name}-{policy}-{scheduler}.json").write_text(
                    json.dumps(result, indent=2), encoding="utf-8"
                )
            print(name, policy, "complete; physical usage-priced USD", answers.spent, flush=True)


if __name__ == "__main__":
    main()
