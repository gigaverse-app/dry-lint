"""Reserve review slots for shared destinations and diversify repeated file pairs."""

from collections import defaultdict, deque

from dry_lint.models import Candidate, Function


def at_destination(function: Function, candidate: Candidate) -> bool:
    return any(
        (not target.repository or function.origin and function.origin.repository == target.repository)
        and (target.path == "." or function.path == target.path or function.path.startswith(target.path + "/"))
        for target in candidate.consolidation
    )


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    groups = defaultdict(list)
    for pair in candidates:
        names = tuple(
            sorted(f.origin.repository if f.origin else f.path.split("/")[0] for f in (pair.new, pair.existing))
        )
        preferred = any(at_destination(f, pair) for f in (pair.new, pair.existing))
        groups[(not preferred, names)].append(pair)
    queues = []
    for group in sorted(groups):
        families = defaultdict(list)
        for pair in sorted(groups[group], key=lambda p: (-p.similarity, p.key)):
            family = tuple(sorted((f.origin.repository if f.origin else "", f.path) for f in (pair.new, pair.existing)))
            families[family].append(pair)
        ordered = []
        while families:
            for family in list(families):
                ordered.append(families[family].pop(0))
                if not families[family]:
                    del families[family]
        queues.append(deque(ordered))
    ranked = []
    while queues:
        for queue in list(queues):
            ranked.append(queue.popleft())
            if not queue:
                queues.remove(queue)
    return ranked
