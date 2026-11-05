"""Model discovery retains baseline retrieval and adds independently bounded mechanical routes."""

from dry_lint.detector import Detector
from dry_lint.settings import Settings

from conftest import Repo


def test_model_exploration_recovers_tiny_and_subset_contracts_without_displacing_baseline(tmp_path):
    repo = Repo(tmp_path / "models")
    declarations = {
        "Target": ["participant_identifier"],
        "InviteTarget": ["participant_identifier"],
        "Retry": ["retry_status", "retry_interval", "attempts"],
        "CompiledCall": ["retry_status", "retry_interval", "attempts", "url", "method", "headers", "body", "timeout"],
        "Receipt": ["request", "response"],
        "ReceiptCopy": ["request", "response"],
    }
    for name, fields in declarations.items():
        repo.write(
            f"{name}.py",
            "from pydantic import BaseModel\n"
            + f"class {name}(BaseModel):\n"
            + "".join(f"    {field}: str\n" for field in fields),
        )
    repo.commit()
    settings = Settings(extractors=["python-models"], comparer="model-shape")
    original = Detector.for_repository(repo.root, settings)
    baseline = original.candidates(original.functions)
    settings = settings.model_copy(
        update={
            "discovery": settings.discovery.model_validate(
                {
                    "enabled": True,
                    "comparers": [
                        {
                            "use": "tfidf",
                            "min_similarity": 0.7,
                            "min_similarity_small": 0.7,
                            "max_df": 1,
                            "neighbours": 3,
                        },
                        {"use": "model-shape", "min_similarity": 0.35, "neighbours": 10},
                    ],
                }
            )
        }
    )
    detector = Detector.for_repository(repo.root, settings)
    candidates = detector.candidates(detector.functions)
    assert [p for p in candidates if p.lane == "baseline"] == baseline
    assert len({p.key for p in candidates}) == len(candidates)
    found = {frozenset((p.new.name, p.existing.name)): p for p in candidates}
    assert found[frozenset(("Target", "InviteTarget"))].lane == "exploration"
    assert found[frozenset(("Retry", "CompiledCall"))].lane == "exploration"
    assert found[frozenset(("Target", "InviteTarget"))].comparer.startswith("tfidf:")


def test_exploration_does_not_promote_unchanged_relatives_into_the_paid_primary_queue(tmp_path):
    repo = Repo(tmp_path / "chain")
    for name, fields in {
        "Changed": ["a", "b"],
        "Bridge": ["a", "b", "c", "d", "e"],
        "Relative": ["c", "d", "e"],
    }.items():
        repo.write(
            f"{name}.py",
            "from pydantic import BaseModel\n"
            + f"class {name}(BaseModel):\n"
            + "".join(f"    {field}: str\n" for field in fields),
        )
    repo.commit()
    settings = Settings(
        extractors=["python-models"],
        comparer="model-shape",
        discovery={"enabled": True, "comparers": [{"use": "model-shape", "min_similarity": 0.35, "neighbours": 1}]},
    )
    detector = Detector.for_repository(repo.root, settings)
    changed = next(f for f in detector.functions if f.name == "Changed")
    pairs = detector.candidates([changed])
    assert len(pairs) == 1
    assert {pairs[0].new.name, pairs[0].existing.name} == {"Changed", "Bridge"}
