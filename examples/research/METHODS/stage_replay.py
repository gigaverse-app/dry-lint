"""Stage narrowly bounded original replays in a new writable directory.

Inputs remain private. No provider/model acquisition or new fitting is performed.
The legacy source manifests must already resolve to accessible frozen inputs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--method",
        choices=[
            "learned-budget-policy",
            "refactor-discovery-bundles",
            "adaptive-judge-budget",
            "encoder-corpus-evaluation",
        ],
        required=True,
    )
    ap.add_argument("--evidence-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    root = args.evidence_root.resolve()
    out = args.out.resolve()
    if not root.is_dir() or out.exists():
        ap.error("Need existing evidence root and a new output directory")
    source = root / "jobs" / args.method / ".lab-results"
    out.mkdir(parents=True)
    implementation = Path(__file__).resolve().parent / args.method / "implementation"
    for p in implementation.glob("*.py"):
        shutil.copy2(p, out / p.name)
    if args.method == "learned-budget-policy":
        files = ["INPUTS.json", "COMPLETION-SUBSET.json", "selections.jsonl", "guard-selections.jsonl"]
        directories = ["models"]
        command = [sys.executable, str(out / "reproduce_policy.py"), "--out", "recomputed"]
    elif args.method == "adaptive-judge-budget":
        files = []
        directories = ["matched-captures", "returned-wave-v1"]
        command = [
            sys.executable,
            str(out / "replay_completion.py"),
            "--snapshot",
            str(source / "completion-round4-receipts/RECORDINGS.json"),
            "--out",
            str(out / "recomputed"),
        ]
    elif args.method == "encoder-corpus-evaluation":
        files = []
        directories = ["runtime"]
        driver = out / "test_driver.py"
        driver.write_text(
            "import pytest\nraise SystemExit(pytest.main(['-q','-c','/dev/null','-p','no:cacheprovider','test_rank_harness.py']))\n"
        )
        command = [sys.executable, str(driver)]
    else:
        files = []
        directories = ["samples"]
        command = [sys.executable, str(out / "test_bundles.py")]
    for name in files:
        shutil.copy2(source / name, out / name)
    # Only read-only input directories are linked. Outputs are new names in out.
    for name in directories:
        (out / name).symlink_to(source / name, target_is_directory=True)
    env = dict(os.environ, DRY_LINT_EVIDENCE_ROOT=str(root), PYTHONDONTWRITEBYTECODE="1")
    # Audit hook denies networking in the replay process. No credentials needed.
    offline = out / "_offline_runner.py"
    offline.write_text(
        "import sys, runpy\ndef guard(event,args):\n    if event in {'socket.connect','socket.getaddrinfo'}: raise RuntimeError('Networking disabled during frozen replay')\nsys.addaudithook(guard)\nsys.argv=sys.argv[1:]\nrunpy.run_path(sys.argv[0],run_name='__main__')\n"
    )
    command = [command[0], str(offline), *command[1:]]
    result = subprocess.run(command, cwd=out, env=env, check=False)
    if result.returncode == 0 and args.method == "adaptive-judge-budget":

        def keyed(path):
            return {(r["cohort_id"], r["query"]): r for r in map(json.loads, path.read_text().splitlines())}

        actual = keyed(out / "recomputed/results.jsonl")
        expected = keyed(source / "completion-final-measured/results.jsonl")
        assert actual.keys() == expected.keys()
        arms = 0
        for key in actual:
            for arm, value in actual[key]["arms"].items():
                reference = expected[key]["arms"][arm]
                assert value["normal"] == reference["normal"]
                for field in [
                    "state",
                    "censored",
                    "reports",
                    "actual_settled_usd",
                    "unresolved_hold_usd",
                    "recordings",
                ]:
                    assert value["native"][field] == reference["native"][field], field
                arms += 1
        (out / "SCHEDULER-VALIDATION.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "arms": arms,
                    "native_states_reports_usage_holds_identical": True,
                    "normal_ledgers_identical": True,
                    "network_blocked": True,
                },
                indent=2,
            )
            + "\n"
        )
    (out / "EXECUTION.json").write_text(
        json.dumps(
            {
                "method": args.method,
                "exit_code": result.returncode,
                "provider_calls": 0,
                "encoder_calls": 0,
                "limits": "Original manifests retain frozen paths. Full arbitrary-root materialization is a separate prerequisite.",
            },
            indent=2,
        )
        + "\n"
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
