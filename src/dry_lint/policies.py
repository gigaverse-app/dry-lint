"""Declarative adopter policy. Paths and names are selectors, never inferred architectural truth."""

import fnmatch
import hashlib
import json
from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from dry_lint.models import AppliedPolicy, Function, PolicyIntent, qualified


class SymbolSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[str] = Field(default_factory=lambda: ["*"], min_length=1)
    names: list[str] = Field(default_factory=lambda: ["*"], min_length=1)
    repositories: list[str] = Field(default_factory=lambda: ["*"], min_length=1)
    reachable_from: list[str] = Field(default_factory=list)
    not_reachable_from: list[str] = Field(default_factory=list)
    role: str = Field(
        default="", description="Adopter-declared ownership role; verify against consumers before refactoring."
    )

    def matches(self, function: Function) -> bool:
        roots = function.declaration.reachable_from if function.declaration else []
        if self.reachable_from and not any(
            fnmatch.fnmatchcase(root, pattern) for root in roots for pattern in self.reachable_from
        ):
            return False
        if any(fnmatch.fnmatchcase(root, pattern) for root in roots for pattern in self.not_reachable_from):
            return False
        return all(
            any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)
            for value, patterns in (
                (function.path, self.paths),
                (qualified(function.owner, function.name), self.names),
                (function.origin.repository if function.origin else "", self.repositories),
            )
        )


class PairPolicy(PolicyIntent):
    left: SymbolSelector
    right: SymbolSelector

    def apply(self, a: Function, b: Function) -> AppliedPolicy | None:
        orientations = [(x, y) for x, y in ((a, b), (b, a)) if self.left.matches(x) and self.right.matches(y)]
        if not orientations:
            return None
        roles: dict[str, set[str]] = defaultdict(set)
        for x, y in orientations:
            for function, selector in ((x, self.left), (y, self.right)):
                if selector.role:
                    roles[function.qualname].add(selector.role)
        # Both matching orientations retain both possible roles rather than arbitrarily assigning ownership.
        return AppliedPolicy(
            name=self.name,
            reason=self.reason,
            action=self.action,
            priority=self.priority,
            definition_hash=hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True).encode()).hexdigest(),
            roles={name: sorted(values) for name, values in sorted(roles.items())},
        )
