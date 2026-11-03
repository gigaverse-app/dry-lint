"""
Settings, read from `[tool.dry-lint]` in pyproject.toml or from `.dry-lint.toml`.

The thresholds are core and apply whatever plugins are chosen. Each plugin slot (`extractors`, `comparer`, `judge`,
`escalate`, `store`) takes a name, or a table with `use` and the plugin's own options:

    comparer = { use = "tfidf", min_similarity = 0.5 }

The default thresholds were measured on gigaverse-ai (docs/benchmark.md): they are a starting point, and
`dry-lint bench` is there to re-measure them on your own code.
"""

import tomllib
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


class Pattern(BaseModel):
    """A declared family of deliberate look-alikes, never reported (e.g. one router per resource)."""

    members: str = Field(description="fnmatch pattern over qualified names, e.g. 'src/api/*_api.py::create_router'.")
    reason: str


class PluginChoice(BaseModel):
    """Which plugin fills a slot; every other key is passed to the plugin's constructor."""

    model_config = ConfigDict(extra="allow")

    use: str

    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class Escalation(PluginChoice):
    """A second judge for the scores the first judge is least sure about."""

    between: tuple[float, float] = Field(default=(0.6, 0.8), description="First-judge scores in [low, high) escalate.")

    def options(self) -> dict[str, Any]:
        return {name: value for name, value in super().options().items() if name != "between"}


def _named(value: Any) -> Any:
    return {"use": value} if isinstance(value, str) else value


Choice = Annotated[PluginChoice, BeforeValidator(_named)]


class Settings(BaseModel):
    include: list[str] = Field(default_factory=lambda: ["*"], description="fnmatch over tracked paths.")
    exclude: list[str] = Field(default_factory=lambda: ["*/tests/*", "tests/*", "*/migrations/*", "*/scripts/*"])
    patterns: list[Pattern] = Field(default_factory=list)
    neighbours: int = Field(default=3, description="Nearest functions in other files considered per changed function.")

    extractors: list[Choice] = Field(default_factory=lambda: [PluginChoice(use="python")],
                                     description="One per language; the first whose file globs match a file reads it.")
    comparer: Choice = Field(default_factory=lambda: PluginChoice(use="tfidf"))
    judge: Choice = Field(default_factory=lambda: PluginChoice(use="auto"),
                          description="auto: Jev when TYPESAFE_AI_API_KEY is set, otherwise none (list candidates).")
    escalate: Annotated[Escalation | None, BeforeValidator(_named)] = None
    store: Choice = Field(default_factory=lambda: PluginChoice(use="dir"),
                          description="dir: a folder, by default inside the git directory; s3: a bucket prefix.")

    drop_below: float = Field(default=0.6, description="Judge scores below this are not duplicates.")
    report_at: float = Field(default=0.8, description="Judge scores at or above this are reported.")
    fail_at: float = Field(default=0.9, description="Judged duplicates at or above this fail `check`; between "
                                                    "report_at and fail_at they only warn.")
    drift_at: float = Field(default=0.8, description="Behaves-differently scores at or above this mark a finding drifted.")
    reopen_margin: float = Field(default=0.05, description="A 'not a duplicate' verdict reopens only if the pair got this much closer.")
    max_findings: int = Field(default=10, description="Findings listed in a pull request comment; the rest are counted.")

    @classmethod
    def load(cls, root: Path) -> "Settings":
        dedicated = root / ".dry-lint.toml"
        if dedicated.exists():
            return cls.model_validate(tomllib.loads(dedicated.read_text()))
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            return cls.model_validate(tomllib.loads(pyproject.read_text()).get("tool", {}).get("dry-lint", {}))
        return cls()
