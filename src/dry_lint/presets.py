"""
Judging presets: which judges run, on which scores, and the thresholds measured for that combination.

A threshold belongs to a judging setup, not to dry-lint: Jev's 0.8 and Claude Sonnet's 0.7 mean different things.
So the judges and the thresholds are chosen together, as a preset, and any of them can still be set explicitly:

    [tool.dry-lint]
    preset = "balanced"        # or "auto" (the default): the best preset the environment's credentials allow
    fail_at = 0.8              # an explicit value always wins over the preset's

Legacy presets' numbers come from the 250-pair gigaverse-ai gold set (docs/benchmark.md), simulated on each pull
request's real candidates under the default budget ($0.04 a pull request, every push included); presets marked
`measured = False` are not independently calibrated. Balanced has separate historical production measurements
(docs/production-discovery-results.md), including the limitations of its small known-positive panel.
The agent presets' numbers come from four gigaverse gold sets, Python and TypeScript, at their report threshold
(docs/judges.md#who-reads-the-findings-people-or-coding-agents).
"""

import os
from collections.abc import Mapping

from pydantic import BaseModel

from dry_lint.settings import Discovery, Escalation, ExplorationComparer, PluginChoice, Settings

SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"
HAIKU = "claude-haiku-5-5"


class Preset(BaseModel):
    name: str
    summary: str
    judge: PluginChoice
    discovery: Discovery = Discovery()
    discovery_append: tuple[ExplorationComparer, ...] = ()
    escalate: Escalation | None = None
    drop_below: float
    report_at: float
    fail_at: float
    needs: tuple[str, ...] = ()  # environment variables that must be set for "auto" to pick it
    automatic: bool = False  # False: a login no environment variable shows, so it must be named
    measured: bool = True
    numbers: str = ""


def _escalate(use: str, **options: object) -> Escalation:
    # Jev's own bar for the pairs the second judge did not see: the band's edges, or past the budget.
    return Escalation(use=use, between=(0.5, 0.91), first_at=0.8, **options)


PRESETS = {preset.name: preset for preset in [
    Preset(name="jev+opus", summary="Jev on every pair, Claude Opus 5.5 (API key) on Jev scores in [0.5, 0.91)",
           judge=PluginChoice(use="jev"), escalate=_escalate("anthropic", model=OPUS),
           drop_below=0.5, report_at=0.55, fail_at=0.55, needs=("TYPESAFE_AI_API_KEY", "ANTHROPIC_API_KEY"),
           numbers="98% precision, 85% recall within $0.04 a pull request (99% and 90% unbudgeted); "
                   "about $0.005 a pull request on average, and 1 in 12 reach the budget"),
    Preset(name="jev+claude-code", summary="Jev on every pair, Claude Opus 5.5 through a Claude subscription on [0.5, 0.91)",
           judge=PluginChoice(use="jev"), escalate=_escalate("claude-code", model=OPUS),
           drop_below=0.5, report_at=0.55, fail_at=0.55, needs=("TYPESAFE_AI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"),
           measured=False, numbers="the same model and prompt as jev+opus, through the `claude` CLI; about $0.005 a "
                                   "pull request of subscription use, at list price"),
    Preset(name="jev+sonnet", summary="Jev on every pair, Claude Sonnet 5.5 (API key) on Jev scores in [0.5, 0.91)",
           judge=PluginChoice(use="jev"), escalate=_escalate("anthropic", model=SONNET),
           drop_below=0.5, report_at=0.6, fail_at=0.7, needs=("TYPESAFE_AI_API_KEY", "ANTHROPIC_API_KEY"), automatic=False,
           numbers="fails at 0.7: 97% precision, 84% recall; reports from 0.6: 94% precision, 87% recall; "
                   "about $0.0035 a pull request"),
    Preset(name="jev+claude-code-sonnet", summary="Jev on every pair, Claude Sonnet 5.5 through a Claude subscription on [0.5, 0.91)",
           judge=PluginChoice(use="jev"), escalate=_escalate("claude-code", model=SONNET),
           drop_below=0.5, report_at=0.6, fail_at=0.7, needs=("TYPESAFE_AI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"),
           automatic=False, measured=False,
           numbers="the same model and prompt as jev+sonnet, through the `claude` CLI; a third of jev+claude-code's "
                   "subscription use"),
    Preset(name="jev+codex", summary="Jev on every pair, the ChatGPT subscription's model through `codex` on [0.5, 0.91)",
           judge=PluginChoice(use="jev"), escalate=_escalate("codex"),
           drop_below=0.5, report_at=0.7, fail_at=0.7, needs=("TYPESAFE_AI_API_KEY",), automatic=False,
           numbers="fails at 0.7: 96% precision, 85% recall (its scores barely move between 0.6 and 0.8); "
                   "about 1.1 subscription calls a pull request, about 14 s each"),
    Preset(name="sonnet", summary="Claude Sonnet 5.5 (API key) on every pair",
           judge=PluginChoice(use="anthropic", model=SONNET),
           drop_below=0.5, report_at=0.6, fail_at=0.7, needs=("ANTHROPIC_API_KEY",),
           numbers="fails at 0.7: 97% precision, but 63% recall within $0.04 a pull request: with no cheap first "
                   "judge, 1 in 10 pull requests run out and leave pairs unjudged (84% recall unbudgeted, $0.015)"),
    Preset(name="claude-code", summary="Claude Sonnet 5.5 through a Claude subscription on every pair",
           judge=PluginChoice(use="claude-code", model=SONNET),
           drop_below=0.5, report_at=0.6, fail_at=0.7, needs=("CLAUDE_CODE_OAUTH_TOKEN",), measured=False,
           numbers="the same model and prompt as sonnet; about $0.015 a pull request of subscription use"),
    Preset(name="jev", summary="Jev on every pair",
           judge=PluginChoice(use="jev"), drop_below=0.6, report_at=0.8, fail_at=0.8, needs=("TYPESAFE_AI_API_KEY",),
           numbers="fails at 0.8: 94% precision, 73% recall; about $0.0002 a pull request"),
    # For a coding agent, which checks every finding itself: recall first, so a low threshold and a cheap judge.
    Preset(name="agent", summary="For coding agents: Jev on every pair, reported from 0.6",
           judge=PluginChoice(use="jev"), drop_below=0.5, report_at=0.6, fail_at=0.6, needs=("TYPESAFE_AI_API_KEY",),
           automatic=False,
           numbers="92% to 100% recall at 43% to 69% precision on the gigaverse-ai, -backend, -web-app and -mobile gold "
                   "sets; about $0.0002 a pull request"),
    Preset(name="agent+haiku", summary="For coding agents: Jev on every pair, Claude Haiku 5.5 on Jev scores in [0.5, 0.91)",
           judge=PluginChoice(use="jev"),
           escalate=Escalation(use="anthropic", model=HAIKU, between=(0.5, 0.91), first_at=0.6),
           drop_below=0.5, report_at=0.5, fail_at=0.5, needs=("TYPESAFE_AI_API_KEY", "ANTHROPIC_API_KEY"), automatic=False,
           numbers="Python: 94% recall at 61% to 85% precision; TypeScript: 70% to 80% recall at 58% to 81%; Haiku "
                   "costs about a fifteenth of Sonnet a pair"),
    Preset(name="agent-haiku", summary="Experimental local feedback: Haiku shared-operation judge, coding agent reviews findings",
           judge=PluginChoice(use="anthropic", model="claude-haiku-5-5", prompt_policy="shared-operations", max_tokens=2048),
           drop_below=0.5, report_at=0.5, fail_at=0.5, needs=("ANTHROPIC_API_KEY",), automatic=False, measured=False,
           numbers="opt-in agent-reviewed experiment; 17 true and 7 false evidence reports on 10 development PRs; "
                   "local checks use baseline retrieval, not the historical exploration scheduler"),
    Preset(name="balanced", summary="Recommended function review: Claude shared-operation judging, bounded discovery and persistent budget",
           judge=PluginChoice(use="anthropic", model="claude-haiku-5-5", prompt_policy="shared-operations", max_tokens=2048,
                              max_retries=0),
           discovery=Discovery(enabled=True),
           discovery_append=(ExplorationComparer(use="operation-blocks", neighbours=1),),
             drop_below=0.5, report_at=0.5, fail_at=0.5, needs=("ANTHROPIC_API_KEY",), automatic=True, measured=True,
             numbers="TF-IDF-only historical panel: 3/3 known positives on 11 PRs; block route evaluated separately; "
                     "agent-reviewed"),
    Preset(name="none", summary="no judge: candidates are listed, nothing is reported or fails",
           judge=PluginChoice(use="none"), drop_below=0.6, report_at=0.8, fail_at=0.8, automatic=True),
]}  # fmt: skip

# Text prompt calibration is version-specific; legacy tables are historical, not measurements of v3.
for preset in PRESETS.values():
    if preset.judge.use != "jev" or preset.escalate is not None:
        if preset.name != "none":
            preset.measured = False
            preset.numbers = "Historical configuration; not population-calibrated for the current shared-operation prompt. See docs/judges.md."
PRESETS[
    "balanced"
].numbers = "AI-926 diagnostic panel: 6/6 independent cleanup pairs detected, 0/6 shared-owner adapters flagged; small agent-labelled panel, not population precision/recall."

# Subscription transport shares balanced retrieval, prompt and decision thresholds.
PRESETS["balanced-subscription"] = PRESETS["balanced"].model_copy(
    update={
        "name": "balanced-subscription",
        "summary": "Balanced function review through a Claude subscription",
        "judge": PluginChoice(use="claude-code", model=HAIKU, max_tokens=2048),
        "needs": ("CLAUDE_CODE_OAUTH_TOKEN",),
        "measured": False,
        "numbers": "Same prompt, model and thresholds as balanced; subscription transport is not independently calibrated",
    }
)
# The same model, question, discovery and budget, answering in a schema. Its rubric makes it stricter than the
# text judge, so it has its own thresholds: it reports from 0.3, where it found as many labelled duplicates as
# balanced does at 0.5, and fails only from 0.4, where Opus confirmed 51 of its 52 reports on real commits.
PRESETS["balanced-structured"] = PRESETS["balanced"].model_copy(
    update={
        "name": "balanced-structured",
        "summary": "Balanced function review with schema-constrained answers through LangChain",
        "judge": PluginChoice(use="langchain", model=HAIKU, effort="low", max_tokens=2048),
        "drop_below": 0.3,
        "report_at": 0.3,
        "fail_at": 0.4,
        "automatic": False,
        "measured": False,
        "numbers": "756 labelled pairs: reports from 0.3 find 88% of duplicates at 9% false reports (balanced: 87% at "
        "8%); 656 pairs from real commits: failing from 0.4, Opus confirmed 51 of 52, but balanced found 81 "
        "confirmed duplicates against 74 here. Half the time a pair, about a fifth dearer; no unreadable answers.",
    }
)
# Preserve enforcement for existing TypeSafe-only auto users; adopters pin balanced and fail without Claude.
PRESETS["jev"].automatic = True
AUTO_ORDER = ("balanced", "balanced-subscription", "jev", "none")
LISTED = (*AUTO_ORDER, *(name for name in PRESETS if name not in AUTO_ORDER))
PRESET_FIELDS = ("judge", "escalate", "drop_below", "report_at", "fail_at", "discovery")


def auto_preset(environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    return next(name for name in AUTO_ORDER if all(environ.get(variable) for variable in PRESETS[name].needs))


def resolve(settings: Settings, environ: Mapping[str, str] | None = None) -> Settings:
    """The settings with the preset's judges and thresholds filled in wherever they were not set explicitly."""
    if settings.preset == "auto" and "judge" in settings.model_fields_set and settings.judge.use == "none":
        settings = settings.model_copy(update={"preset": "none"})  # no judge is the `none` preset, not your own judge
    elif settings.preset == "auto" and "judge" in settings.model_fields_set:
        # Your own judge: a preset's escalation and thresholds were measured for other judges, so none is added.
        update = {} if "escalate" in settings.model_fields_set else {"escalate": None}
        return settings.model_copy(update={**update, "preset": "custom"})
    name = settings.preset if settings.preset != "auto" else auto_preset(environ)
    if name not in PRESETS:
        raise ValueError(f"Unknown preset {name!r}; available: {', '.join(PRESETS)}")
    preset = PRESETS[name]
    update = {field: getattr(preset, field) for field in PRESET_FIELDS if field not in settings.model_fields_set}
    # INVARIANT: explicit nested discovery choices win, including an empty
    # comparer list (the implicit TF-IDF-only escape hatch) and enabled=False.
    discovery = preset.discovery.model_copy(
        update={field: getattr(settings.discovery, field) for field in settings.discovery.model_fields_set}
    )
    if (
        discovery.enabled
        and preset.discovery_append
        and "comparers" not in settings.discovery.model_fields_set
        and settings.comparer.use == "tfidf"
    ):
        # Match the detector's implicit exploration configuration before appending
        # generic plugins. Explicit custom baselines keep their existing policy.
        options = settings.comparer.options()
        options.update(min_similarity=discovery.min_similarity, min_similarity_small=discovery.min_similarity)
        discovery = discovery.model_copy(
            update={
                "comparers": [
                    ExplorationComparer(use="tfidf", neighbours=discovery.depth, **options),
                    *(choice.model_copy(deep=True) for choice in preset.discovery_append),
                ]
            }
        )
    update["discovery"] = discovery
    return settings.model_copy(update={**update, "preset": name})
