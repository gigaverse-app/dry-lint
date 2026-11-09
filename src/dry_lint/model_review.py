"""Model pass configuration and reviewed allowances, reusing detection and baseline contracts."""

from pathlib import Path

from dry_lint.baseline import Baseline, Entry, contract
from dry_lint.detector import Detector
from dry_lint.feedback import Feedback
from dry_lint.git import git
from dry_lint.models import Candidate, Function
from dry_lint.report import Report
from dry_lint.settings import Discovery, PluginChoice, Settings


def profile(settings: Settings) -> Settings:
    """Fixed model contract, independent of the available credentials and function preset."""
    return settings.model_copy(
        update={
            "extractors": [PluginChoice(use="python-models"), PluginChoice(use="typescript-models")],
            "comparer": settings.models.comparer,
            "neighbours": settings.models.neighbours,
            "policies": [*settings.policies, *settings.models.policies],
            "judge": PluginChoice(use="jev-models"),
            "escalate": None,
            "preset": "models",  # the fixed model contract, which no repository preset changes
            "discovery": Discovery(),
            "budget": settings.models.budget,
            "drop_below": 0.6,
            "report_at": 0.8,
            "fail_at": 0.8,
            "drift_at": 0.8,
        }
    )


def enabled(settings: Settings, override: bool | None, *, staged: bool = False) -> bool:
    # Explicit model-only plugin configurations already run their own pass.
    if any(e.use.endswith("-models") for e in settings.extractors):
        return False
    return override if override is not None else settings.models.enabled and (not staged or settings.models.hook)


def baseline(
    root: Path, settings: Settings, *, staged: bool = False, base: str | None = None, target: bool = False
) -> Baseline | None:
    """Validate current allowances; cleanup may read the target's still-outstanding debt."""
    if not settings.models.baseline:
        return None
    proposed, previous = Baseline.for_repository(
        root, Path(settings.models.baseline), profile(settings), base=base, staged=staged
    )
    return (previous or proposed) if target else proposed


def allowances(candidates: list[Candidate], debt: Baseline | None) -> list[Candidate]:
    """Exact reviewed debt is a source policy, never a reusable atomic verdict."""
    accepted = debt.matching(candidates) if debt else set()
    return [
        c.model_copy(update={"filtered": "accepted model debt: consolidate this reviewed pair"})
        if not c.filtered and c.key in accepted
        else c
        for c in candidates
    ]


def combine(functions: Report, models: Report, debt: Baseline | None) -> Report:
    return functions.model_copy(
        update={
            "findings": [*functions.findings, *models.findings],
            "filtered": [*functions.filtered, *models.filtered],
            "models": models.functions,
            "changed_models": models.changed,
            "model_judging": models.judging,
            "judge": functions.judge or models.judge,
            "model_debt": {state: debt.count(state) for state in ("remaining", "cleaned", "dismissed")}
            if debt
            else None,
            "model_backlog": [item.model_copy(update={"kind": "model"}) for item in models.backlog]
            if models.backlog is not None
            else None,
        }
    )


def ratchet(
    root: Path, settings: Settings, feedback: Feedback, previous: Baseline | None, *, staged: bool = False
) -> Baseline:
    """Record reviewed positives, or retire allowances after source removal / explicit dismissal.

    Unknown and changed candidates never authorize new debt or cleanup. This is an inventory of reviewed
    consolidation work, not an assertion that the whole repository was classified by a model.
    """
    configured = profile(settings)
    revision = git(root, "write-tree") if staged else git(root, "rev-parse", "HEAD")
    detector = Detector.for_tree(root, revision, configured, strict=True)
    candidates = previous.candidates(detector) if previous else detector.candidates(detector.functions)
    candidates = feedback.apply(candidates)
    if previous is None:
        entries = [Entry.of(c) for c in candidates if not c.filtered and feedback.accepted(c)]
        if not entries:
            raise ValueError(
                "Review model pairs with `feedback accept --reason ... --reviewer ...` before initializing debt"
            )
        return Baseline(contract=contract(configured), started_at=revision, checked_at=revision, entries=entries)
    return advance(previous, detector.functions, candidates, revision)


def advance(previous: Baseline, functions: list[Function], candidates: list[Candidate], revision: str) -> Baseline:
    """Retire only resolved allowances; shared by audits and checks that enforce the ratchet."""
    present = {f.qualname for f in functions}
    dismissed = {c.key for c in candidates if c.filtered}
    cleaned = set()
    for entry in previous.entries:
        if not set(entry.hashes) <= present:
            # A renamed copy must remain work: do not count its surviving partner as cleaned while
            # it still has unresolved look-alikes elsewhere in the current inventory.
            surviving = set(entry.hashes) & present
            unresolved = any(
                not c.filtered and c.key != entry.key and surviving & {c.new.qualname, c.existing.qualname}
                for c in candidates
            )
            if not unresolved:
                cleaned.add(entry.key)
    return previous.retire(dismissed=dismissed, cleaned=cleaned, revision=revision)
