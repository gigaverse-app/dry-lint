"""
Settings, read from `[tool.dry-lint]` in pyproject.toml or from `.dry-lint.toml`.

The defaults are the thresholds measured on gigaverse-ai (docs/benchmark.md): they are a starting point, and the
benchmark harness is there to re-measure them on your own code.
"""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Pattern(BaseModel):
    """A declared family of deliberate look-alikes, never reported (e.g. one router per resource)."""

    members: str = Field(description="fnmatch pattern over qualified names, e.g. 'src/api/*_api.py::create_router'.")
    reason: str


class Settings(BaseModel):
    detector: Literal["tfidf", "dryer"] = "tfidf"
    dryer_threshold: float = Field(default=0.82, gt=0, le=1)
    dryer_min_lines: int = Field(default=4, ge=1)
    dryer_min_nodes: int = Field(default=20, ge=1)
    include: list[str] = Field(default_factory=lambda: ["*.py"])
    exclude: list[str] = Field(default_factory=lambda: ["*/tests/*", "tests/*", "*/migrations/*", "*/scripts/*"])
    patterns: list[Pattern] = Field(default_factory=list)

    neighbours: int = Field(default=3, description="Nearest functions in other files considered per changed function.")
    min_similarity: float = Field(default=0.5, description="Detector floor for ordinary functions.")
    small_function_lines: int = Field(default=6, description="Functions shorter than this use the small-function floor.")
    min_similarity_small: float = Field(default=0.3, description="Tiny helpers share few tokens, so their twins score lower.")

    drop_below: float = Field(default=0.6, description="Judge scores below this are not duplicates.")
    report_at: float = Field(default=0.8, description="Judge scores at or above this are reported.")
    drift_at: float = Field(default=0.8, description="Behaves-differently scores at or above this mark a finding drifted.")
    reopen_margin: float = Field(default=0.05, description="A 'not a duplicate' verdict reopens only if the pair got this much closer.")

    @classmethod
    def load(cls, root: Path) -> "Settings":
        dedicated = root / ".dry-lint.toml"
        if dedicated.exists():
            return cls.model_validate(tomllib.loads(dedicated.read_text()))
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            return cls.model_validate(tomllib.loads(pyproject.read_text()).get("tool", {}).get("dry-lint", {}))
        return cls()
