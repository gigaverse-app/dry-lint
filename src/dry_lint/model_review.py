"""Model pass configuration and reviewed allowances, reusing detection and baseline contracts."""

from pathlib import Path

from dry_lint.baseline import Baseline, Entry, contract
from dry_lint.detector import Detector
from dry_lint.feedback import Feedback
from dry_lint.git import git
from dry_lint.models import Candidate
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
            "preset": "custom",
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


def baseline(root: Path, settings: Settings, *, staged: bool = False, base: str | None = None) -> Baseline | None:
    if not settings.models.baseline:
        return None
    path = (root / settings.models.baseline).resolve().relative_to(root.resolve()).as_posix()
    raw = git(root, "show", f":{path}") if staged else (root / path).read_text(encoding="utf-8")
    proposed = Baseline.model_validate_json(raw)
    if proposed.contract != contract(profile(settings)):
        raise ValueError("Model baseline detection policy differs; restore the adoption settings before checking")
    previous_ref = "HEAD" if staged else base
    if previous_ref and git(root, "ls-tree", "--name-only", previous_ref, "--", path):
        previous = Baseline.model_validate_json(git(root, "show", f"{previous_ref}:{path}"))
        proposed.validate_successor(previous)
    return proposed


def allowances(candidates: list[Candidate], debt: Baseline | None) -> list[Candidate]:
    """Exact reviewed debt is a source policy, never a reusable atomic verdict."""
    accepted = {entry.key: entry for entry in debt.entries} if debt else {}
    return [
        c.model_copy(update={"filtered": "accepted model debt: consolidate this reviewed pair"})
        if not c.filtered and c.key in accepted and accepted[c.key].accepts(c)
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
            "backlog": [*(functions.backlog or []), *(models.backlog or [])]
            if functions.backlog is not None or models.backlog is not None
            else None,
        }
    )


def ratchet(root: Path, settings: Settings, feedback: Feedback, previous: Baseline | None) -> Baseline:
    """Record reviewed positives, or retire allowances after source removal / explicit dismissal.

    Unknown and changed candidates never authorize new debt or cleanup. This is an inventory of reviewed
    consolidation work, not an assertion that the whole repository was classified by a model.
    """
    configured = profile(settings)
    detector = Detector.for_tree(root, "HEAD", configured, strict=True)
    candidates = previous.candidates(detector) if previous else detector.candidates(detector.functions)
    candidates = feedback.apply(candidates)
    revision = git(root, "rev-parse", "HEAD")
    if previous is None:
        entries = [Entry.of(c) for c in candidates if not c.filtered and feedback.accepted(c)]
        if not entries:
            raise ValueError(
                "Review model pairs with `feedback accept --reason ... --reviewer ...` before initializing debt"
            )
        return Baseline(contract=contract(configured), started_at=revision, checked_at=revision, entries=entries)
    present = {f.qualname for f in detector.functions}
    pairs = {c.key: c for c in candidates}
    entries = []
    for entry in previous.entries:
        state = entry.state
        if state == "remaining":
            candidate = pairs.get(entry.key)
            if candidate and candidate.filtered:
                state = "dismissed"
            elif not set(entry.hashes) <= present:
                # A renamed copy must remain work: do not count its surviving partner as cleaned while
                # it still has unresolved look-alikes elsewhere in the current inventory.
                surviving = set(entry.hashes) & present
                unresolved = any(
                    not c.filtered and c.key != entry.key and surviving & {c.new.qualname, c.existing.qualname}
                    for c in candidates
                )
                if not unresolved:
                    state = "cleaned"
        entries.append(entry.model_copy(update={"state": state}))
    return (
        previous.model_copy(update={"entries": entries, "checked_at": revision})
        if entries != previous.entries
        else previous
    )
