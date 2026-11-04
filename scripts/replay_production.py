"""Capture immutable PR trees and replay the production discovery scheduler. Outputs contain private source."""

import argparse
import json
from pathlib import Path

from capture_history import History
from judge_history import LiveAnswers

from dry_lint.detector import Detector, changed_lines, touched
from dry_lint.discovery import CampaignStore
from dry_lint.feedback import Decision, Feedback
from dry_lint.git import git
from dry_lint.judging import Judging
from dry_lint.models import Candidate, CandidatesFile, Run, Verdict, evidence
from dry_lint.presets import resolve
from dry_lint.report import Report
from dry_lint.settings import Settings
from dry_lint.store import DirectoryStore, VerdictStore


def capture(history: History, destination: Path) -> None:
    settings = resolve(Settings(preset="balanced", extractors=["python"]))
    destination.mkdir(parents=True, exist_ok=True)
    provenance = {"history": history.model_dump(mode="json"), "settings": settings.model_dump(mode="json"),
                  "retrieval": "baseline-plus-same-file-v1"}
    manifest = destination / "manifest.json"
    if manifest.exists() and json.loads(manifest.read_bytes()) != provenance:
        raise ValueError("Capture inputs changed; use a new output directory")
    manifest.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    for ordinal, head in enumerate(history.commits):
        target = destination / f"{ordinal:03d}.json"
        if target.exists():
            continue
        detector = Detector.for_tree(history.root, head, settings)
        changed = touched(detector.functions, changed_lines(history.root, history.base, head=head))
        run = Run(repository=history.repository, pull_request=history.number, head=head, base=history.base,
                  revision=git(history.root, "rev-parse", f"{head}^{{tree}}"))
        snapshot = CandidatesFile(run=run, changed=len(changed), functions=len(detector.functions),
                                  candidates=detector.candidates(changed))
        target.write_text(snapshot.model_dump_json(), encoding="utf-8")
        print(destination.name, ordinal, len(snapshot.candidates), "pairs", flush=True)


class ObservedJudge:
    """Replay provider observations through production judging, charging cached usage to each campaign."""

    def __init__(self, answers: LiveAnswers) -> None:
        self.answers = answers
        provider = answers.judge
        self.name, self.version, self.model = provider.name, provider.version, provider.model
        self.max_tokens, self.prompt_policy = provider.max_tokens, provider.prompt_policy
        self.tokens = {"input": 0, "output": 0}

    def judge(self, candidates: list[Candidate], settings: Settings) -> list[Verdict]:
        verdicts = []
        for candidate in candidates:
            observation = self.answers.observe(candidate)
            self.tokens["input"] += observation.input_tokens
            self.tokens["output"] += observation.output_tokens
            self.tokens["cache_creation_input_tokens"] = (
                self.tokens.get("cache_creation_input_tokens", 0) + observation.cache_creation_tokens)
            self.tokens["cache_read_input_tokens"] = (
                self.tokens.get("cache_read_input_tokens", 0) + observation.cache_read_tokens)
            if observation.verdict is None:
                raise ValueError(observation.error or "Provider did not return a verdict")
            verdicts.append(observation.verdict)
        return verdicts


def evaluate(captures: Path, output: Path, answers: LiveAnswers, baseline: bool = False,
             labels: dict[str, str] | None = None) -> None:
    settings = resolve(Settings(preset="balanced"))
    judge = ObservedJudge(answers)
    store = VerdictStore(DirectoryStore(output / "verdicts"))
    output.mkdir(parents=True, exist_ok=True)
    progress = output / "curves.json"
    curves = json.loads(progress.read_bytes()) if progress.exists() else []
    feedback_path = output / "feedback.json"
    feedback = Feedback.read(feedback_path)
    for ordinal, source in enumerate(sorted(captures.glob("[0-9]*.json"))):
        snapshot = CandidatesFile.model_validate_json(source.read_bytes())
        if ordinal < len(curves):
            if curves[ordinal]["head"] != snapshot.run.head:
                raise ValueError("Replay history changed; use a new output directory")
            continue
        judging = Judging(settings, judge, None, store)
        judging.campaign = CampaignStore(output / "ledger.sqlite3", snapshot.run)
        candidates = [c for c in snapshot.candidates if not baseline or c.lane == "baseline"]
        candidates = feedback.apply(candidates)
        findings = judging.findings(candidates, snapshot.run)
        report = Report.build(findings, settings, run=snapshot.run, judging=judging.summary())
        (output / source.name).write_text(report.model_dump_json(), encoding="utf-8")
        state = judging.campaign.snapshot()
        curves.append({"head": snapshot.run.head, "usd": state.usd, "calls": len(state.attempts),
                       "reported": [f.candidate.key for f in report.findings if f.reported],
                       "covered": [f.candidate.key for f in report.findings if f.verdict is not None],
                       "dismissed": sum(bool(c.filtered and c.filtered.startswith("reviewed dismissal:"))
                                        for c in candidates),
                       "deferred": report.deferred})
        # Simulate reviewed dismissals only after their first interruption. Never infer a fix from disappearance.
        for finding in report.visible:
            candidate = finding.candidate
            if labels and labels.get(evidence(candidate)) == "separate":
                feedback.decisions.append(Decision(pair=candidate.key, evidence=evidence(candidate), action="dismiss",
                    reason="Reviewed separate in the supplied reference panel", reviewer="codex-replay",
                    revision=snapshot.run.revision))
        feedback.write(feedback_path)
        progress.write_text(json.dumps(curves, indent=2), encoding="utf-8")
        print(output.name, source.stem, len(report.visible), "reports", state.usd, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--feedback", type=Path, help="Exact-evidence reviewed labels; dismiss separate reports once")
    args = parser.parse_args()
    labels = ({row["evidence"]: row["label"] for row in json.loads(args.feedback.read_bytes())}
              if args.feedback else None)
    answers = (LiveAnswers(args.out / "answers", model="claude-haiku-5-5", prompt_policy="shared-operations",
                           max_tokens=2048, limit=2.0) if args.judge else None)
    for raw in json.loads(args.manifest.read_bytes()):
        history = History.model_validate(raw)
        name = f"{history.repository.split('/')[-1]}-{history.number}"
        destination = args.out / "captures" / name
        capture(history, destination)
        if answers:
            arm = "feedback" if args.feedback else "baseline" if args.baseline else "balanced"
            evaluate(destination, args.out / arm / name, answers, args.baseline, labels)


if __name__ == "__main__":
    main()
