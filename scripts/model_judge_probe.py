"""Evaluate a bounded sample of a model probe with the adopter's configured API key.

Outputs contain source and belong outside the code PR. Verdicts checkpoint individually so retries
preserve completed work. The inventory and source revision come from model_probe.py.
"""

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from dry_lint.judges.anthropic import AnthropicJudge
from dry_lint.models import CandidatesFile
from dry_lint.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=30, help="Maximum per input file")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--policy", default="model-contracts")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.env_file:
        from dotenv import load_dotenv

        load_dotenv(args.env_file)
    judge = AnthropicJudge(prompt_policy=args.policy, max_tokens=512, workers=4, retry_malformed=True)
    args.out.mkdir(parents=True, exist_ok=True)
    pairs = []
    for path in args.candidates:
        data = CandidatesFile.model_validate_json(path.read_text(encoding="utf-8"))
        eligible = sorted((c for c in data.candidates if not c.filtered and c.lane == "baseline"), key=lambda c: c.key)
        chosen = random.Random(args.seed).sample(eligible, min(args.limit, len(eligible)))
        pairs.extend(chosen)
    (args.out / "sample.json").write_text(CandidatesFile(candidates=pairs).model_dump_json(indent=2), encoding="utf-8")

    def ask(pair):
        target = args.out / f"{pair.key}.json"
        if target.exists():
            return
        try:
            verdict = judge.judge([pair], Settings())[0]
            target.write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
            print(pair.key, verdict.label, verdict.score, flush=True)
        except Exception as error:
            # Checkpoint successful answers, but leave this one absent and retryable.
            print(pair.key, type(error).__name__, flush=True)

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(ask, pairs))
    completed = sum((args.out / f"{c.key}.json").exists() for c in pairs)
    receipt = {
        "sample": len(pairs),
        "completed": completed,
        "tokens_this_run": judge.tokens,
        "judge": judge.name,
        "version": judge.version,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    (args.out / f"receipt-{stamp}.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt), flush=True)
    if completed != len(pairs):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
