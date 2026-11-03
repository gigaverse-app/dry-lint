"""Historical capture must not see code introduced after the queried revision."""

import runpy
from pathlib import Path

from dry_lint.detector import changed_lines
from dry_lint.settings import Settings

from conftest import EXISTING, TWIN

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "capture_history.py"


def test_history_uses_immutable_trees_and_merge_base_diffs(repo, tmp_path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    api = runpy.run_path(str(SCRIPT))
    base, first = repo.git("rev-parse", "main"), repo.git("rev-parse", "HEAD")
    expected_lines = changed_lines(repo.root, base)
    repo.write("src/future.py", "def future(value):\n    return value.copy()\n")
    repo.commit("feat: add future function")
    second = repo.git("rev-parse", "HEAD")
    (repo.root / "src/widgets/caption.py").unlink()
    repo.commit("refactor: delete caption")
    third = repo.git("rev-parse", "HEAD")
    assert changed_lines(repo.root, base, head=first) == expected_lines
    sources = api["tree_sources"](repo.root, first, Settings())
    assert "src/future.py" not in sources
    assert "src/widgets/caption.py" in sources
    history = api["History"](
        repository="test/project", root=repo.root, number=1, base=base, commits=[first, second, third]
    )
    result = api["capture"](history, tmp_path / "capture", 3)
    assert [s.sources["baseline"].changed for s in result.steps] == [2, 3, 1]
    assert [s.sources["baseline"].run.head for s in result.steps] == [first, second, third]
    assert all(
        "future" not in c.new.code and "future" not in c.existing.code
        for f in result.steps[0].sources.values()
        for c in f.candidates
    )
    assert repo.git("rev-parse", "HEAD") == third


def test_empty_historical_tree_is_a_valid_zero_candidate_opportunity(repo, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    api = runpy.run_path(str(SCRIPT))
    assert api["tree_sources"](repo.root, "HEAD", Settings(include=["missing/*"])) == {}


def test_audit_is_deterministic_and_excludes_every_previously_proposed_pair(repo, tmp_path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    api = runpy.run_path(str(SCRIPT))
    for number in range(4):
        repo.write(f"src/alternative{number}.py", EXISTING.replace("shorten_text", f"alternative{number}"))
    repo.commit("test: seed more neighbours than the shortlist holds")
    base = repo.git("rev-parse", "HEAD")
    repo.write("src/widgets/caption.py", TWIN.replace('rstrip(".,;")', 'rstrip(".,;!")'))
    repo.commit("test: revise caption")
    history = api["History"](
        repository="test/project",
        root=repo.root,
        number=1,
        base=base,
        commits=[repo.git("rev-parse", "HEAD")],
    )
    directory = tmp_path / "capture"
    captured = api["capture"](history, directory, 3)
    audit = runpy.run_path(str(SCRIPT.with_name("audit_history.py")))["audit"]
    first, second = audit(directory), audit(directory)
    assert first == second
    prior = {c.key for step in captured.steps for source in step.sources.values() for c in source.candidates}
    chosen = first.steps[0].sources["semantic"].candidates
    assert chosen
    assert len(chosen) <= 2
    assert all(c.key not in prior for c in chosen)
    ablate = runpy.run_path(str(SCRIPT.with_name("score_history.py")))["retrieval_ablation"]
    counts = ablate(directory, prior)
    assert counts["baseline"]["pairs"] == counts["baseline"]["known_positives"]
    assert counts["lexical-relaxed-20"]["pairs"] > counts["baseline"]["pairs"]
