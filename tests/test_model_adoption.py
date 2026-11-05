import json

import pytest

from dry_lint.baseline import Baseline, Entry, contract
from dry_lint.cli import main
from dry_lint.detector import Detector
from dry_lint.feedback import Decision, Feedback
from dry_lint.model_review import baseline, profile, ratchet
from dry_lint.models import CandidatesFile, evidence
from dry_lint.report import Report
from dry_lint.settings import Settings

from conftest import Repo, clear_judge_credentials


@pytest.mark.parametrize("setting", ["enabled", "hook"])
def test_repo_can_opt_out_of_staged_models(tmp_path, monkeypatch, setting):
    clear_judge_credentials(monkeypatch)
    repo = model_repo(tmp_path)
    repo.write(".dry-lint.toml", f"[models]\n{setting} = false\n")
    repo.write("new.py", (repo.root / "new.py").read_text() + "    etag: str\n")
    repo.git("add", "-A")
    report = tmp_path / "report.json"
    args = ["check", "--root", str(repo.root), "--staged", "--report", str(report)]
    assert main(args) == 0
    assert Report.model_validate_json(report.read_text()).models == 0
    assert main([*args, "--models"]) == 0
    assert Report.model_validate_json(report.read_text()).models == 2


def model_repo(tmp_path):
    repo = Repo(tmp_path / "models")
    repo.write("old.py", "from pydantic import BaseModel\nclass Receipt(BaseModel):\n    url: str\n    size: int\n")
    repo.commit()
    repo.git("checkout", "-qb", "feature")
    repo.write("new.py", "from dataclasses import dataclass\n@dataclass\nclass Payload:\n    url: str\n    size: int\n")
    repo.commit()
    return repo


def test_default_model_pass_survives_split_pipeline_and_opt_out(tmp_path, monkeypatch):
    clear_judge_credentials(monkeypatch)
    repo = model_repo(tmp_path)
    candidates, report = tmp_path / "candidates.json", tmp_path / "report.json"
    args = ["--root", str(repo.root), "--base", "main", "--out", str(candidates)]
    assert main(["detect", *args]) == 0
    found = CandidatesFile.model_validate_json(candidates.read_text())
    assert len(found.model_candidates) == 1
    assert main(["judge", "--root", str(repo.root), "--candidates", str(candidates), "--report", str(report)]) == 0
    result = Report.model_validate_json(report.read_text())
    assert result.models == 2
    assert len(result.visible) == 1
    assert result.visible[0].candidate.new.declaration
    assert main(["detect", *args, "--no-models"]) == 0
    assert json.loads(candidates.read_text())["model_candidates"] is None


def test_hook_defaults_to_models_and_reads_staged_source(tmp_path, monkeypatch):
    clear_judge_credentials(monkeypatch)
    repo = model_repo(tmp_path)
    repo.write(
        "new.py",
        "from dataclasses import dataclass\n@dataclass\nclass Payload:\n    url: str\n    size: int\n    etag: str\n",
    )
    repo.git("add", "new.py")
    repo.write("new.py", "# unstaged removal must not hide the staged model\n")
    report = tmp_path / "report.json"
    args = ["check", "--root", str(repo.root), "--staged", "--report", str(report)]
    assert main(args) == 0
    assert len(Report.model_validate_json(report.read_text()).visible) == 1
    assert main([*args, "--no-models"]) == 0
    assert not Report.model_validate_json(report.read_text()).visible


def test_reviewed_model_debt_ratchets_and_never_accepts_changed_or_new_pairs(tmp_path, monkeypatch):
    clear_judge_credentials(monkeypatch)
    repo = model_repo(tmp_path)
    report_path = tmp_path / "report.json"
    args = ["check", "--root", str(repo.root), "--base", "main", "--report", str(report_path)]
    assert main(args) == 0
    pair = Report.model_validate_json(report_path.read_text()).visible[0].candidate.key
    baseline_args = ["model-baseline", "--root", str(repo.root)]
    assert main([*baseline_args, "--init"]) == 2  # A candidate/atomic score is not acceptance.
    assert (
        main(
            [
                "feedback",
                "accept",
                pair,
                "--root",
                str(repo.root),
                "--from",
                str(report_path),
                "--reason",
                "Both consumers read the same artifact receipt; consolidate in storage contracts.",
                "--reviewer",
                "source reviewer",
            ]
        )
        == 0
    )
    assert main([*baseline_args, "--init"]) == 0
    repo.write(".dry-lint.toml", '[models]\nbaseline = ".dry-lint/models.json"\n')
    repo.commit()
    assert main(args) == 0
    result = Report.model_validate_json(report_path.read_text())
    assert result.model_debt == {"remaining": 1, "cleaned": 0, "dismissed": 0}
    assert not result.visible
    repo.write(
        "new.py",
        "from dataclasses import dataclass\n@dataclass\nclass Payload:\n    url: str\n    size: int\n    etag: str\n",
    )
    repo.commit()
    assert main(args) == 0  # No credentials: listed, not judged or falsely cleared.
    assert len(Report.model_validate_json(report_path.read_text()).visible) == 1
    assert main([*baseline_args, "--update"]) == 0
    path = repo.root / ".dry-lint/models.json"
    assert Baseline.model_validate_json(path.read_text()).count("remaining") == 1
    (repo.root / "new.py").unlink()
    repo.commit()
    assert main([*baseline_args, "--update"]) == 0
    assert Baseline.model_validate_json(path.read_text()).count("cleaned") == 1
    repo.commit()
    repo.write("new.py", "from dataclasses import dataclass\n@dataclass\nclass Payload:\n    url: str\n    size: int\n")
    repo.commit()
    assert main(args) == 0
    assert len(Report.model_validate_json(report_path.read_text()).visible) == 1


def test_models_require_source_review_without_paying_another_judge(tmp_path, monkeypatch, twin_judge):
    clear_judge_credentials(monkeypatch)
    repo = model_repo(tmp_path)
    report = tmp_path / "report.json"
    args = [
        "check",
        "--root",
        str(repo.root),
        "--base",
        "main",
        "--judge",
        "command",
        "--judge-command",
        twin_judge,
        "--report",
        str(report),
    ]
    assert main(args) == 1
    result = Report.model_validate_json(report.read_text())
    assert len(result.review_required) == 1
    assert result.review_required[0].verdict is None
    assert result.deferred == 0
    assert main([*args, "--warn-only"]) == 0
    assert main([*args, "--no-models"]) == 0


def test_model_policies_are_opt_in_and_a_changed_policy_reopens_a_dismissal(tmp_path, monkeypatch, twin_judge):
    clear_judge_credentials(monkeypatch)
    repo = model_repo(tmp_path)
    policy = """
[[models.policies]]
name = "separate-wire"
reason = "Payload is an independently versioned wire boundary."
action = "discard"
left = { paths = ["new.py"], names = ["Payload"], role = "wire" }
right = { paths = ["old.py"], names = ["Receipt"], role = "domain" }
"""
    repo.write(".dry-lint.toml", policy)
    repo.commit()
    report = tmp_path / "report.json"
    args = [
        "check",
        "--root",
        str(repo.root),
        "--base",
        "main",
        "--judge",
        "command",
        "--judge-command",
        twin_judge,
        "--report",
        str(report),
    ]
    assert main(args) == 0
    result = Report.model_validate_json(report.read_text())
    assert not result.visible
    assert result.filtered[0].policies[0].name == "separate-wire"
    repo.write(".dry-lint.toml", policy.replace('action = "discard"', 'action = "review"\npriority = 5'))
    repo.commit()
    assert main(args) == 1
    assert Report.model_validate_json(report.read_text()).review_required[0].candidate.priority == 5


def test_split_check_rejects_missing_model_inventory_when_requested(tmp_path, monkeypatch):
    clear_judge_credentials(monkeypatch)
    repo = model_repo(tmp_path)
    candidates = tmp_path / "missing.json"
    candidates.write_text(CandidatesFile().model_dump_json())
    assert main(["judge", "--root", str(repo.root), "--candidates", str(candidates), "--models"]) == 2


def test_model_allowances_cannot_be_widened_and_use_the_staged_baseline(tmp_path):
    repo = model_repo(tmp_path)
    settings = Settings(models={"baseline": ".dry-lint/models.json"})
    configured = profile(settings)
    detector = Detector.for_repository(repo.root, configured)
    [pair] = detector.candidates(detector.functions)
    debt = Baseline(
        contract=contract(configured), started_at="adoption", checked_at="adoption", entries=[Entry.of(pair)]
    )
    repo.write(".dry-lint/models.json", debt.model_dump_json())
    repo.commit()
    assert baseline(repo.root, settings, staged=True) == debt
    changed = debt.model_copy(deep=True)
    changed.entries[0].hashes[pair.new.qualname] = "new allowance"
    repo.write(".dry-lint/models.json", changed.model_dump_json())
    assert baseline(repo.root, settings, staged=True) == debt  # Unstaged tampering cannot reach the hook.
    with pytest.raises(ValueError, match="widen"):
        baseline(repo.root, settings, base="HEAD")
    repo.git("add", ".dry-lint/models.json")
    with pytest.raises(ValueError, match="widen"):
        baseline(repo.root, settings, staged=True)
    settings.models.neighbours = 4
    with pytest.raises(ValueError, match="policy differs"):
        baseline(repo.root, settings)


def test_model_ratchet_keeps_renamed_debt_and_distinguishes_dismissal_from_cleanup(tmp_path):
    repo = model_repo(tmp_path)
    settings = Settings()
    detector = Detector.for_repository(repo.root, profile(settings))
    [pair] = detector.candidates(detector.functions)
    feedback = Feedback(
        decisions=[
            Decision(
                pair=pair.key,
                evidence=evidence(pair),
                action="accept",
                reason="same receipt",
                reviewer="source review",
                revision="HEAD",
            )
        ]
    )
    debt = ratchet(repo.root, settings, feedback, None)
    repo.git("mv", "new.py", "renamed.py")
    repo.commit()
    assert ratchet(repo.root, settings, feedback, debt).count("remaining") == 1
    repo.git("mv", "renamed.py", "new.py")
    repo.commit()
    feedback.decisions.append(
        feedback.decisions[0].model_copy(update={"action": "dismiss", "reason": "independent wire version verified"})
    )
    result = ratchet(repo.root, settings, feedback, debt)
    assert result.count("dismissed") == 1 and result.count("cleaned") == 0
    assert ratchet(repo.root, settings, feedback, result) == result
