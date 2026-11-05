import json
import re
import sys
from pathlib import Path

import pytest

from dry_lint.baseline import Baseline
from dry_lint.cli import main
from dry_lint.comparers import TfidfComparer
from dry_lint.detector import Detector
from dry_lint.extractors import PythonExtractor
from dry_lint.functions import repository_functions
from dry_lint.ledger import COUNTER, counter_key
from dry_lint.models import pair_key
from dry_lint.report import Report
from dry_lint.settings import Settings
from dry_lint.typescript import TypeScriptExtractor

from conftest import Repo, run_cli


def sweep(repo: Repo, tmp_path: Path, judge: str, *args: str) -> int:
    return run_cli(repo, tmp_path, "--judge", "command", "--judge-command", judge, "--update", *args, command="sweep")


def state(repo: Repo) -> dict:
    return json.loads((repo.root / ".dry-lint/baseline.json").read_text())


def test_sweep_ratchets_specific_pairs_and_rejects_reintroduction(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    assert len(state(repo)["entries"]) == 1
    assert sweep(repo, tmp_path, twin_judge) == 0
    original = (repo.root / "src/widgets/caption.py").read_text()
    repo.write("src/widgets/caption.py", "from src.text import shorten_text\n")
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge) == 0
    assert state(repo)["entries"][0]["state"] == "cleaned"
    repo.write("src/widgets/caption.py", original)
    repo.commit()
    before = state(repo)
    assert sweep(repo, tmp_path, twin_judge) == 1
    assert state(repo) == before


def test_baseline_allows_only_unchanged_debt(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    args = (
        "--base",
        "main",
        "--judge",
        "command",
        "--judge-command",
        twin_judge,
        "--baseline",
        ".dry-lint/baseline.json",
        "--require-complete",
    )
    assert run_cli(repo, tmp_path, *args) == 0
    assert run_cli(repo, tmp_path, *args, "--warn-only") == 2
    path = repo.root / "src/widgets/caption.py"
    path.write_text(path.read_text().replace("max_len - 1", "max_len - 2"))
    repo.commit()
    assert run_cli(repo, tmp_path, *args) == 1
    assert sweep(repo, tmp_path, twin_judge) == 1


def test_an_entry_recorded_before_context_hashes_still_accepts_its_unchanged_pair(
    repo: Repo, tmp_path: Path, twin_judge: str
) -> None:
    """
    INVARIANT: a baseline accepted before the detector gave every pair a context hash keeps accepting the same,
    unchanged functions; it still refuses them once either changes. A recorded context hash is still compared.
    """
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    path = repo.root / ".dry-lint/baseline.json"
    recorded = json.loads(path.read_text())
    assert recorded["entries"][0]["context_hash"]  # today every pair has one

    def record(context_hash: str) -> None:
        recorded["entries"][0]["context_hash"] = context_hash
        path.write_text(json.dumps(recorded))
        repo.commit()

    args = ("--judge", "command", "--judge-command", twin_judge, "--baseline", ".dry-lint/baseline.json")
    record("")  # as baselines written before context hashing
    assert sweep(repo, tmp_path, twin_judge) == 0
    assert run_cli(repo, tmp_path, "--base", "main", *args, "--require-complete") == 0
    record("0" * 16)  # a different recorded context is not this pair's
    assert sweep(repo, tmp_path, twin_judge) == 1
    record("")
    source = repo.root / "src/widgets/caption.py"
    source.write_text(source.read_text().replace("max_len - 1", "max_len - 2"))
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge) == 1  # changed logic is new debt, with or without a context hash


def test_suppression_is_dismissal_not_cleanup(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    path = repo.root / "src/widgets/caption.py"
    path.write_text(path.read_text().replace("    if len", "    # dry-lint: ignore\n    if len", 1))
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge) == 0
    assert state(repo)["entries"][0]["state"] == "dismissed"


def test_sweep_honors_only_committed_exact_source_feedback(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    report_path = tmp_path / "review.json"
    assert sweep(repo, tmp_path, twin_judge, "--init", "--report", str(report_path)) == 0
    report = Report.model_validate_json(report_path.read_bytes())
    pair = next(f.candidate.key for f in report.findings if f.blocking)
    assert (
        main(
            [
                "feedback",
                "dismiss",
                pair,
                "--root",
                str(repo.root),
                "--from",
                str(report_path),
                "--reason",
                "Independently owned wire contracts verified at callers",
                "--reviewer",
                "source-review",
            ]
        )
        == 0
    )
    assert sweep(repo, tmp_path, twin_judge) == 0
    assert state(repo)["entries"][0]["state"] == "remaining"  # Uncommitted feedback cannot settle committed code.
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge) == 0
    assert state(repo)["entries"][0]["state"] == "dismissed"
    settled = state(repo)
    assert sweep(repo, tmp_path, twin_judge) == 0
    assert state(repo) == settled
    path = repo.root / "src/widgets/caption.py"
    path.write_text(path.read_text().replace("max_len - 1", "max_len - 2"))
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge) == 1  # A stale dismissal cannot hide changed evidence.
    assert state(repo) == settled


@pytest.mark.parametrize("command", ["check", "sweep"])
def test_strict_mode_never_passes_without_a_judge(repo: Repo, tmp_path: Path, command: str) -> None:
    args = ["--base", "main", "--require-complete"] if command == "check" else ["--init"]
    assert run_cli(repo, tmp_path, "--judge", "none", *args, command=command) == 2
    assert not (repo.root / ".dry-lint/baseline.json").exists()


def test_sweep_refuses_incomplete_judging_and_existing_initialization(
    repo: Repo, tmp_path: Path, twin_judge: str
) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    before = state(repo)
    assert sweep(repo, tmp_path, twin_judge, "--init") == 2
    assert state(repo) == before


def test_readme_progress_is_idempotent_and_matches_shields_schema(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    repo.write("README.md", "# A library\n\nUseful introduction.\n")
    args = ("--readme", "README.md", "--repository", "acme/library")
    assert sweep(repo, tmp_path, twin_judge, "--init", *args) == 0
    readme = (repo.root / "README.md").read_text()
    assert "Useful introduction." in readme and "img.shields.io/endpoint?url=" in readme
    assert sweep(repo, tmp_path, twin_judge, *args) == 0
    assert (repo.root / "README.md").read_text() == readme
    badge = json.loads((repo.root / ".dry-lint/progress.json").read_text())
    assert badge["schemaVersion"] == 1
    assert badge["message"] == "0 cleaned · 1 remaining"


def card(readme: str) -> list[str]:
    """The sign addresses in a README's block, light and dark."""
    return re.findall(r'(?:src|srcset)="(https://dry-lint-counter[^"]+)"', readme)


def test_the_readme_block_opens_with_the_repositorys_sign_and_its_backlog(
    repo: Repo, tmp_path: Path, twin_judge: str
) -> None:
    """
    INVARIANT: a repository's sign carries the long-term counts by its counter key, and this backlog's counts in its
    address, so a sweep that cleans a pair changes the sign.
    """
    repo.write("README.md", "# A library\n")
    args = ("--readme", "README.md", "--repository", "acme/library", "--repository-id", "4242")
    assert sweep(repo, tmp_path, twin_judge, "--init", *args) == 0
    readme = (repo.root / "README.md").read_text()
    signs = card(readme)
    # The sign shows the backlog, so the block repeats it nowhere else.
    assert "img.shields.io" not in readme and "| Duplicate pairs cleaned |" not in readme
    assert "[Accepted backlog](.dry-lint/baseline.json) · [Weekly audit](" in readme
    key = counter_key("4242")
    assert signs == [
        f"{COUNTER}/v1/sign.svg?theme=dark&amp;key={key}&amp;name=acme%2Flibrary&amp;cleaned=0&amp;remaining=1&amp;dismissed=0",
        f"{COUNTER}/v1/sign.svg?key={key}&amp;name=acme%2Flibrary&amp;cleaned=0&amp;remaining=1&amp;dismissed=0",
    ]
    repo.write("src/widgets/caption.py", "from src.text import shorten_text\n")
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge, *args) == 0
    assert all("cleaned=1&amp;remaining=0" in sign for sign in card((repo.root / "README.md").read_text()))


def test_actions_name_their_own_repository_and_a_local_sweep_keeps_the_sign(
    repo: Repo, tmp_path: Path, twin_judge: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo.write("README.md", "# A library\n")
    args = ("--readme", "README.md", "--repository", "acme/library")
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/other")
    monkeypatch.setenv("GITHUB_REPOSITORY_ID", "77")
    assert sweep(repo, tmp_path, twin_judge, "--init", *args) == 0
    assert card((repo.root / "README.md").read_text()) == []  # another repository's id is not this one's
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/library")
    assert sweep(repo, tmp_path, twin_judge, *args) == 0
    assert counter_key("77") in (repo.root / "README.md").read_text()
    for name in ("GITHUB_REPOSITORY", "GITHUB_REPOSITORY_ID"):
        monkeypatch.delenv(name)
    repo.write("src/widgets/caption.py", "from src.text import shorten_text\n")
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge, *args) == 0
    readme = (repo.root / "README.md").read_text()
    assert len(card(readme)) == 2 and counter_key("77") in readme and "cleaned=1" in readme
    assert sweep(repo, tmp_path, twin_judge, *args, "--no-counter-card") == 0
    assert card((repo.root / "README.md").read_text()) == []


def test_parse_failure_cannot_clear_the_backlog(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    before = state(repo)
    repo.write("src/widgets/caption.py", "def broken(:\n")
    assert sweep(repo, tmp_path, twin_judge) == 2
    assert state(repo) == before


def test_unknown_baseline_schema_is_an_error(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    value = state(repo)
    value["schema"] = 999
    (repo.root / ".dry-lint/baseline.json").write_text(json.dumps(value))
    assert sweep(repo, tmp_path, twin_judge) == 2


def test_required_check_rejects_a_widened_pr_baseline(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    repo.commit()
    base = repo.git("rev-parse", "HEAD")
    value = state(repo)
    value["entries"] = []
    (repo.root / ".dry-lint/baseline.json").write_text(json.dumps(value))
    repo.commit()
    assert (
        run_cli(
            repo,
            tmp_path,
            "--base",
            base,
            "--baseline-ref",
            base,
            "--baseline",
            ".dry-lint/baseline.json",
            "--judge",
            "command",
            "--judge-command",
            twin_judge,
        )
        == 2
    )


def test_partial_sweep_keeps_all_previous_state(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    source = (repo.root / "src/widgets/caption.py").read_text()
    repo.write("src/third.py", source.replace("preview_caption_text", "third_caption"))
    repo.write(".dry-lint.toml", "max_judgements = 1\n")
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge, "--init") == 2
    assert not (repo.root / ".dry-lint/baseline.json").exists()


def test_default_audit_is_read_only_even_after_cleanup(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    before = state(repo)
    repo.write("src/widgets/caption.py", "from src.text import shorten_text\n")
    repo.commit()
    assert run_cli(repo, tmp_path, "--judge", "command", "--judge-command", twin_judge, command="sweep") == 0
    assert state(repo) == before


@pytest.mark.parametrize("mutation", ["duplicate", "missing_hash", "scope", "hash", "reopen"])
def test_corrupt_or_widened_acceptance_is_rejected(repo: Repo, tmp_path: Path, twin_judge: str, mutation: str) -> None:
    assert sweep(repo, tmp_path, twin_judge, "--init") == 0
    original = Baseline.model_validate(state(repo))
    value = state(repo)
    if mutation == "duplicate":
        value["entries"].append(value["entries"][0])
    elif mutation == "missing_hash":
        value["entries"][0]["hashes"] = {"a.py::a": ""}
    elif mutation == "scope":
        repo.write(".dry-lint.toml", 'exclude = ["src/*"]\n')
        assert sweep(repo, tmp_path, twin_judge) == 2
        return
    elif mutation == "hash":
        name = next(iter(value["entries"][0]["hashes"]))
        value["entries"][0]["hashes"][name] = "different"
    else:
        original.entries[0].state = "cleaned"
    with pytest.raises(ValueError):
        Baseline.model_validate(value).validate_successor(original)


def test_valid_successor_and_direct_advance_refuse_new_debt(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    report_path = tmp_path / "report.json"
    assert sweep(repo, tmp_path, twin_judge, "--init", "--report", str(report_path)) == 0
    baseline = Baseline.model_validate(state(repo))
    baseline.validate_successor(baseline)
    report = Report.model_validate_json(report_path.read_text())
    empty = baseline.model_copy(update={"entries": []})
    with pytest.raises(ValueError, match="cannot be added"):
        empty.advance(report)
    with pytest.raises(ValueError, match="OWNER/NAME"):
        baseline.markdown("bad repo", "main", ".dry-lint")


def test_strict_scanning_requires_valid_source_and_a_validating_plugin(repo: Repo) -> None:
    class LegacyExtractor:
        files = ("*.py",)

    with pytest.raises(ValueError, match="strict source validation"):
        repository_functions(repo.root, ["*"], [], [LegacyExtractor()], strict=True)
    (repo.root / "src/text.py").unlink()
    with pytest.raises(FileNotFoundError):
        repository_functions(repo.root, ["*"], [], [PythonExtractor()], strict=True)
    extractor = TypeScriptExtractor()
    extractor.validate_source("a.ts", "export const a = (x: number) => x + 1;")
    with pytest.raises(ValueError, match="parse error"):
        extractor.validate_source("a.ts", "export function broken( {")


def test_strict_mode_rejects_workspace_scopes(repo: Repo, tmp_path: Path) -> None:
    assert run_cli(repo, tmp_path, "--require-complete", "--repo", f"acme/lib={repo.root}") == 2


@pytest.mark.parametrize("staged", [False, True])
def test_balanced_strict_check_validates_the_selected_tree(repo: Repo, tmp_path: Path, capsys, staged: bool) -> None:
    repo.write("src/text.py", "def broken(\n")
    repo.commit()
    if staged:
        repo.write("src/text.py", "def also_broken(\n")
        repo.git("add", "src/text.py")
    # A valid unstaged repair must not hide invalid committed/staged input from the strict check.
    repo.write("src/text.py", "def repaired():\n    return 1\n")
    args = ["--staged"] if staged else ["--base", "main"]
    assert run_cli(repo, tmp_path, "--preset", "balanced", "--judge", "none", "--require-complete", *args) == 2
    assert "Cannot completely scan src/text.py" in capsys.readouterr().err


def adopt(repo: Repo, tmp_path: Path, judge: str) -> tuple[str, ...]:
    """main accepts the caption twin as debt; a `cleanup` branch starts from it. Returns the required check's args."""
    assert sweep(repo, tmp_path, judge, "--init") == 0
    repo.commit("adopt")
    repo.git("checkout", "-q", "-B", "main")
    repo.git("checkout", "-q", "-b", "cleanup")
    return (
        "--base",
        "main",
        "--baseline",
        ".dry-lint/baseline.json",
        "--baseline-ref",
        "main",
        "--require-complete",
        "--judge",
        "command",
        "--judge-command",
        judge,
        "--report",
        str(tmp_path / "report.json"),
    )


def backlog(tmp_path: Path) -> list[dict] | None:
    return json.loads((tmp_path / "report.json").read_text())["backlog"]


TWIN_PAIR = {"new": "src/text.py::shorten_text", "existing": "src/widgets/caption.py::preview_caption_text"}


@pytest.mark.parametrize("recorded", [False, True], ids=["cleanup", "cleanup-and-sweep"])
def test_a_check_credits_accepted_debt_its_change_removed(
    repo: Repo, tmp_path: Path, twin_judge: str, recorded: bool
) -> None:
    args = adopt(repo, tmp_path, twin_judge)
    repo.write("src/widgets/caption.py", "from src.text import shorten_text\n")
    repo.commit()
    if recorded:  # the pull request also records its cleanup; the target branch's debt still names the pair
        assert sweep(repo, tmp_path, twin_judge) == 0
        repo.commit()
    metadata = [(repo.root / ".dry-lint" / name).read_bytes() for name in ("baseline.json", "progress.json")]
    assert run_cli(repo, tmp_path, *args) == 0
    assert backlog(tmp_path) == [{**TWIN_PAIR, "how": "removed"}]
    # The baseline and its badge belong to the sweep: a check never moves them.
    assert [(repo.root / ".dry-lint" / name).read_bytes() for name in ("baseline.json", "progress.json")] == metadata


def copy_judge(tmp_path: Path) -> str:
    """A judge that reads the code: the twin is a duplicate only while the caption keeps its copied body."""
    path = tmp_path / "copy_judge.py"
    path.write_text(
        "import json, sys\n"
        "prompt = sys.stdin.read()\n"
        "copy = 'clipped' in prompt and 'cut = text' in prompt\n"
        "print(json.dumps({'label': 'duplicate' if copy else 'separate', 'score': 0.85 if copy else 0.1, "
        "'owner': 'existing', 'why': 'the caption copies the helper'}))\n"
    )
    return f'"{sys.executable}" "{path}"'


def test_property_setter_cannot_retire_unchanged_getter_debt(repo: Repo, tmp_path: Path) -> None:
    repo.write(".dry-lint.toml", '[comparer]\nuse = "tfidf"\nmin_similarity = 0.3\n')
    repo.write(
        "src/widgets/caption.py",
        """
        class Caption:
            @property
            def preview_caption_text(self):
                caption_text, max_len = self.text, self.limit
                if len(caption_text) <= max_len:
                    return caption_text
                clipped = caption_text[: max_len - 1].rstrip()
                return clipped.rstrip(".,;") + "…"

            @preview_caption_text.setter
            def preview_caption_text(self, value):
                self.text = value
                self.notify_listeners(value)
        """,
    )
    repo.commit()
    judge = copy_judge(tmp_path)
    assert sweep(repo, tmp_path, judge, "--init") == 0
    accepted = state(repo)
    assert len(accepted["entries"]) == 1
    detector = Detector.for_repository(repo.root, Settings.load(repo.root))
    detector.comparer = TfidfComparer(min_similarity=1.0, min_similarity_small=1.0)
    detector.comparer.index(detector.functions)
    assert detector.candidates(detector.functions) == []  # Control: the getter fell outside retrieval.
    baseline = Baseline.model_validate(accepted)
    recovered = baseline.candidates(detector)
    assert len(recovered) == 1 and baseline.entries[0].accepts(recovered[0])
    for _ in range(2):
        assert sweep(repo, tmp_path, judge) == 0
        assert state(repo) == accepted

    path = repo.root / "src/widgets/caption.py"
    path.write_text(path.read_text().replace("max_len - 1", "max_len - 2"))
    repo.commit()
    assert sweep(repo, tmp_path, judge) == 1
    assert state(repo) == accepted


def test_a_rerouted_side_is_revisited_and_credited_on_a_separate_verdict(repo: Repo, tmp_path: Path) -> None:
    args = adopt(repo, tmp_path, copy_judge(tmp_path))
    source = (repo.root / "src/widgets/caption.py").read_text()
    body = source[source.index("    if len") : source.index("\n\n\ndef register_widget")]
    rerouted = source.replace(body, "    return shorten_text(caption_text, max_len)")
    repo.write("src/widgets/caption.py", "from src.text import shorten_text\n\n\n" + rerouted)
    repo.commit()
    assert run_cli(repo, tmp_path, *args) == 0
    report = Report.model_validate_json((tmp_path / "report.json").read_text())
    assert any(f.candidate.key == pair_key(*TWIN_PAIR.values()) for f in report.findings)  # judged, proposed or not
    assert backlog(tmp_path) == [{**TWIN_PAIR, "how": "separate"}]


def test_debt_removed_before_the_branch_is_not_credited_to_it(repo: Repo, tmp_path: Path, twin_judge: str) -> None:
    args = adopt(repo, tmp_path, twin_judge)
    repo.git("checkout", "-q", "main")
    repo.write("src/widgets/caption.py", "from src.text import shorten_text\n")
    repo.commit("cleaned on main before the next sweep recorded it")
    repo.git("checkout", "-q", "-B", "cleanup")
    repo.write("src/widgets/later.py", "def later(value):\n    return value\n")
    repo.commit()
    assert run_cli(repo, tmp_path, *args) == 0
    assert backlog(tmp_path) == []


def test_a_check_without_a_baseline_claims_nothing_about_the_backlog(
    repo: Repo, tmp_path: Path, twin_judge: str
) -> None:
    args = (
        "--base",
        "main",
        "--judge",
        "command",
        "--judge-command",
        twin_judge,
        "--warn-only",
        "--report",
        str(tmp_path / "report.json"),
    )
    assert run_cli(repo, tmp_path, *args) == 0
    assert backlog(tmp_path) is None


def test_a_renamed_copy_is_not_credited_as_removed_debt(repo: Repo, tmp_path: Path) -> None:
    args = adopt(repo, tmp_path, copy_judge(tmp_path))
    path = repo.root / "src/widgets/caption.py"
    path.write_text(path.read_text().replace("preview_caption_text", "caption_preview_text"))
    repo.commit()
    assert run_cli(repo, tmp_path, *args) == 1  # the duplication moved, so it is new debt
    assert backlog(tmp_path) == []


def test_debt_the_target_already_records_as_cleaned_is_not_credited_again(
    repo: Repo, tmp_path: Path, twin_judge: str
) -> None:
    args = adopt(repo, tmp_path, twin_judge)
    repo.write("src/widgets/caption.py", "from src.text import shorten_text\n")
    repo.commit()
    assert sweep(repo, tmp_path, twin_judge) == 0
    repo.commit("record the cleanup")
    repo.git("checkout", "-q", "-B", "main")  # the cleanup and its record are merged
    repo.git("checkout", "-q", "-b", "later")
    repo.write("src/widgets/later.py", "def later(value):\n    return value\n")
    repo.commit()
    assert run_cli(repo, tmp_path, *args) == 0
    assert backlog(tmp_path) == []
