"""
Settings, read from `[tool.dry-lint]` in pyproject.toml or from `.dry-lint.toml`.

The thresholds are core and apply whatever plugins are chosen. Each plugin slot (`extractors`, `comparer`, `judge`,
`escalate`, `store`) takes a name, or a table with `use` and the plugin's own options:

    comparer = { use = "tfidf", min_similarity = 0.5 }

The default thresholds were measured on gigaverse-ai (docs/benchmark.md): they are a starting point, and
`dry-lint bench` is there to re-measure them on your own code.
"""

import fnmatch
import tomllib
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from dry_lint.git import git
from dry_lint.models import Consolidation, Verdict
from dry_lint.policies import PairPolicy
from dry_lint.schema_policy import SchemaPolicy


def _globs(value: Any) -> Any:
    return [value] if isinstance(value, str) else value


class Pattern(BaseModel):
    """
    A declared family of deliberate look-alikes, never reported: one router per resource, or copies a project keeps
    on purpose. A pair belongs to the family when each side's `path::Qualified.name` matches one of `members`.
    """

    members: Annotated[list[str], BeforeValidator(_globs)] = Field(
        min_length=1,
        description="fnmatch globs over qualified names, one or a list, e.g. 'src/api/*_api.py::create_router' or "
        "['pkg/strutils.py::indent', 'pkg/funcutils.py::_indent'].",
    )
    reason: str

    def matches(self, qualname: str) -> bool:
        return any(fnmatch.fnmatch(qualname, glob) for glob in self.members)


class PluginChoice(BaseModel):
    """Which plugin fills a slot; every other key is passed to the plugin's constructor."""

    model_config = ConfigDict(extra="allow")

    use: str

    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class Escalation(PluginChoice):
    """A second judge for the scores the first judge is least sure about."""

    between: tuple[float, float] = Field(default=(0.6, 0.91), description="First-judge scores in [low, high) escalate.")
    first_at: float | None = Field(
        default=None,
        description="The first judge's own threshold, for its answers that got "
        "no second opinion (outside the band, or past the budget).",
    )

    def options(self) -> dict[str, Any]:
        return {name: value for name, value in super().options().items() if name not in ("between", "first_at")}


def _named(value: Any) -> Any:
    return {"use": value} if isinstance(value, str) else value


Choice = Annotated[PluginChoice, BeforeValidator(_named)]


class ExplorationComparer(PluginChoice):
    neighbours: int | None = Field(default=None, ge=1, le=100)


class Budget(BaseModel):
    """What judging may spend on one pull request, across all its pushes (on one run, outside a pull request)."""

    usd: float = Field(
        default=0.04,
        description="Most judging spends on a pull request, estimated at list price; a "
        "subscription judge counts at its model's list price too. The "
        "riskiest pairs are judged first; the rest keep the first judge's "
        "answer, or stay unjudged.",
    )
    subscription_calls: int = Field(
        default=20,
        description="Most calls a run makes to subscription judges, which are rate-limited as well as priced.",
    )


class CpuRecovery(BaseModel):
    """Explicit adopter-owned local artifacts for the frozen CPU recovery profile."""

    model_config = ConfigDict(extra="forbid")
    model_dir: str = Field(min_length=1)
    cache_dir: str = Field(min_length=1)
    threads: int = Field(default=2, ge=1, le=2, strict=True)

    def comparers(self):
        return [
            {"use": "tfidf", "neighbours": 20, "min_similarity": 0.35, "min_similarity_small": 0.35},
            {"use": "operation-blocks", "neighbours": 1},
            {"use": "cpu-embedding", "neighbours": 1, **self.model_dump()},
            {"use": "cpu-tail-rrf", "neighbours": 1, **self.model_dump()},
        ]


class Discovery(BaseModel):
    """Baseline first, then paced exploration, sharing a durable campaign allowance."""

    @model_validator(mode="before")
    @classmethod
    def expand_cpu_recovery(cls, value):
        # Normalize the shorthand to the existing configuration contract. Round
        # trips and detection/baseline identities are identical to explicit routes.
        if isinstance(value, dict) and "cpu_recovery" in value:
            value = dict(value)
            profile = CpuRecovery.model_validate(value.pop("cpu_recovery"))
            if "comparers" in value:
                raise ValueError("Choose cpu_recovery or explicit discovery.comparers, not both.")
            value["comparers"] = profile.comparers()
            value.setdefault("enabled", True)
        return value

    enabled: bool = False
    comparers: list[Annotated[ExplorationComparer, BeforeValidator(_named)]] = Field(default_factory=list)
    residual_comparers: list[Annotated[ExplorationComparer, BeforeValidator(_named)]] = Field(
        default_factory=list,
        description="Opt-in recovery after the complete configured pass, borrowing future baseline capacity.",
    )
    depth: int = Field(default=20, ge=3, le=100)
    min_similarity: float = Field(default=0.35, ge=0, le=1)
    baseline_fraction: float = Field(default=0.625, ge=0, le=1)
    exploration_per_revision: float = Field(default=0.006, ge=0)
    calls_per_revision: int = Field(default=20, ge=1)
    exploration_calls_per_revision: int = Field(default=10, ge=0)
    calls: int = Field(default=200, ge=1)


class ModelReview(BaseModel):
    """Independent model retrieval; ownership policies are explicitly supplied by the adopter."""

    enabled: bool = True
    hook: bool = True
    sticky: bool = True
    baseline: str | None = None
    policies: list[PairPolicy] = Field(default_factory=list)
    comparer: Choice = Field(default_factory=lambda: PluginChoice(use="model-shape"))
    schema_policy: SchemaPolicy | None = None
    neighbours: int = Field(default=3, ge=1)
    budget: Budget = Field(default_factory=lambda: Budget(usd=0.01, subscription_calls=0))


class Settings(BaseModel):
    include: list[str] = Field(default_factory=lambda: ["*"], description="fnmatch over tracked paths.")
    exclude: list[str] = Field(default_factory=lambda: ["*/tests/*", "tests/*", "*/migrations/*", "*/scripts/*"])
    patterns: list[Pattern] = Field(default_factory=list)
    policies: list[PairPolicy] = Field(default_factory=list)
    models: ModelReview = Field(default_factory=ModelReview)
    neighbours: int = Field(default=3, description="Nearest functions in other files considered per changed function.")
    consolidation: list[Consolidation] = Field(default_factory=list)
    max_judgements: int | None = Field(default=None, ge=1, description="Maximum uncached pairs judged per run.")

    extractors: list[Choice] = Field(
        default_factory=lambda: [PluginChoice(use="python"), PluginChoice(use="typescript")],
        description="One per language; the first whose file globs match a file reads it.",
    )
    comparer: Choice = Field(default_factory=lambda: PluginChoice(use="tfidf"))
    judge: Choice = Field(
        default_factory=lambda: PluginChoice(use="auto"),
        description="auto: Jev when TYPESAFE_AI_API_KEY is set, otherwise none (list candidates).",
    )
    escalate: Annotated[Escalation | None, BeforeValidator(_named)] = Field(
        default_factory=lambda: Escalation(use="auto"),
        description='auto: Claude Sonnet 5.5 when ANTHROPIC_API_KEY is set, otherwise none; "none" turns it off.',
    )
    preset: str = Field(
        default="auto",
        description="The judging setup: judges and the thresholds measured for them "
        "(presets.py). auto: the best one the credentials allow. Explicit "
        "judge, escalate and threshold settings win over the preset's.",
    )
    budget: Budget = Field(default_factory=Budget)
    discovery: Discovery = Field(default_factory=Discovery)
    labellers: list[str] = Field(
        default_factory=lambda: ["anthropic/claude-opus-5.5", "openai/gpt-5.5", "google/gemini-3.1-pro-preview"],
        description="For `bench --replay --label`: OpenRouter model ids, or `command:<cli>`; the strict majority labels a "
        "pair. Three vendors, so no judge's own family decides its gold labels.",
    )
    prices: dict[str, tuple[float, float]] = Field(
        default_factory=dict,
        description="USD per million input and output tokens, by model or judge name, over the built-in table.",
    )
    store: Choice = Field(
        default_factory=lambda: PluginChoice(use="dir"),
        description="dir: a folder, by default inside the git directory; s3: a bucket prefix.",
    )

    drop_below: float = Field(default=0.6, description="Judge scores below this are not duplicates.")
    report_at: float = Field(default=0.8, description="Judge scores at or above this are reported.")
    fail_at: float = Field(
        default=0.8,
        description="Judged duplicates at or above this fail `check`; between report_at and fail_at they only warn.",
    )
    drift_at: float = Field(
        default=0.8, description="Behaves-differently scores at or above this mark a finding drifted."
    )
    reopen_margin: float = Field(
        default=0.05, description="A 'not a duplicate' verdict reopens only if the pair got this much closer."
    )
    max_findings: int = Field(
        default=10, description="Findings listed in a pull request comment; the rest are counted."
    )

    def bar(self, threshold: float, second_opinion: bool) -> float:
        """
        `threshold` (report_at or fail_at) for an answer that got a second opinion, or when there is no `first_at`;
        otherwise the first judge's own bar, since the thresholds were measured on the second judge's scores.
        """
        first_at = self.escalate.first_at if self.escalate else None
        return threshold if second_opinion or first_at is None else max(threshold, first_at)

    def duplicate_at(self, verdict: Verdict, threshold: float) -> bool:
        """A duplicate label at or above `threshold`, as the judge that answered measures it: what reports decide on."""
        return verdict.label != "separate" and verdict.score >= self.bar(threshold, verdict.second_opinion is not None)

    @classmethod
    def load(cls, root: Path, *, staged: bool = False) -> "Settings":
        tracked = (
            set(git(root, "ls-files", "--cached", "--", ".dry-lint.toml", "pyproject.toml").splitlines())
            if staged
            else set()
        )

        def source(name: str) -> str | None:
            if staged:
                return git(root, "show", f":{name}") if name in tracked else None
            path = root / name
            return path.read_text(encoding="utf-8") if path.exists() else None

        dedicated = source(".dry-lint.toml")
        if dedicated is not None:
            return cls.model_validate(tomllib.loads(dedicated))
        pyproject = source("pyproject.toml")
        if pyproject is not None:
            return cls.model_validate(tomllib.loads(pyproject).get("tool", {}).get("dry-lint", {}))
        return cls()
