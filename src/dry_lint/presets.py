"""
Judging presets: which judges run, on which scores, and the thresholds measured for that combination.

A threshold belongs to a judging setup, not to dry-lint: Jev's 0.8 and Claude Sonnet's 0.7 mean different things.
So the judges and the thresholds are chosen together, as a preset, and any of them can still be set explicitly:

    [tool.dry-lint]
    preset = "jev+sonnet"      # or "auto" (the default): the best preset the environment's credentials allow
    fail_at = 0.8              # an explicit value always wins over the preset's

Each preset's numbers come from the 250-pair gigaverse-ai gold set (docs/benchmark.md); presets marked
`measured = False` share their thresholds with the API preset for the same model.
"""

import os
from collections.abc import Mapping

from pydantic import BaseModel

from dry_lint.settings import Escalation, PluginChoice, Settings

SONNET = "claude-sonnet-5-5"


class Preset(BaseModel):
    name: str
    summary: str
    judge: PluginChoice
    escalate: Escalation | None = None
    drop_below: float
    report_at: float
    fail_at: float
    needs: tuple[str, ...] = ()  # environment variables that must be set for "auto" to pick it
    automatic: bool = True  # False: a login no environment variable shows, so it must be named
    measured: bool = True
    numbers: str = ""


def _escalate(use: str, **options: object) -> Escalation:
    return Escalation(use=use, between=(0.5, 0.91), **options)


PRESETS = {preset.name: preset for preset in [
    Preset(name="jev+sonnet", summary="Jev on every pair, Claude Sonnet 5.5 (API key) on Jev scores in [0.5, 0.91)",
           judge=PluginChoice(use="jev"), escalate=_escalate("anthropic", model=SONNET),
           drop_below=0.5, report_at=0.6, fail_at=0.7, needs=("TYPESAFE_AI_API_KEY", "ANTHROPIC_API_KEY"),
           numbers="fails at 0.7: 97% precision, 84% recall; reports from 0.6: 94% precision, 88% recall; "
                   "about 1.1 Sonnet calls and $0.004 per pull request"),
    Preset(name="jev+claude-code", summary="Jev on every pair, Claude Sonnet 5.5 through a Claude subscription on [0.5, 0.91)",
           judge=PluginChoice(use="jev"), escalate=_escalate("claude-code", model=SONNET),
           drop_below=0.5, report_at=0.6, fail_at=0.7, needs=("TYPESAFE_AI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"),
           measured=False, numbers="the same model and prompt as jev+sonnet, through the `claude` CLI; no per-token cost, "
                                   "about 1.1 subscription calls per pull request"),
    Preset(name="jev+codex", summary="Jev on every pair, the ChatGPT subscription's model through `codex` on [0.5, 0.91)",
           judge=PluginChoice(use="jev"), escalate=_escalate("codex"),
           drop_below=0.5, report_at=0.7, fail_at=0.7, needs=("TYPESAFE_AI_API_KEY",), automatic=False,
           numbers="fails at 0.7: 96% precision, 85% recall (its scores barely move between 0.6 and 0.8); "
                   "about 1.1 subscription calls per pull request, about 14 s each"),
    Preset(name="sonnet", summary="Claude Sonnet 5.5 (API key) on every pair",
           judge=PluginChoice(use="anthropic", model=SONNET),
           drop_below=0.5, report_at=0.6, fail_at=0.7, needs=("ANTHROPIC_API_KEY",),
           numbers="fails at 0.7: 97% precision, 84% recall; about 3.4 calls and $0.011 per pull request"),
    Preset(name="claude-code", summary="Claude Sonnet 5.5 through a Claude subscription on every pair",
           judge=PluginChoice(use="claude-code", model=SONNET),
           drop_below=0.5, report_at=0.6, fail_at=0.7, needs=("CLAUDE_CODE_OAUTH_TOKEN",), measured=False,
           numbers="the same model and prompt as sonnet; about 3.4 subscription calls per pull request"),
    Preset(name="jev", summary="Jev on every pair",
           judge=PluginChoice(use="jev"), drop_below=0.6, report_at=0.8, fail_at=0.8, needs=("TYPESAFE_AI_API_KEY",),
           numbers="fails at 0.8: 94% precision, 73% recall; about $0.0001 per pull request"),
    Preset(name="none", summary="no judge: candidates are listed, nothing is reported or fails",
           judge=PluginChoice(use="none"), drop_below=0.6, report_at=0.8, fail_at=0.8),
]}  # fmt: skip

# "auto" takes the first preset whose credentials are all in the environment; jev+codex must be named.
AUTO_ORDER = ("jev+sonnet", "jev+claude-code", "jev", "sonnet", "claude-code", "none")
LISTED = (*AUTO_ORDER[:3], "jev+codex", *AUTO_ORDER[3:])
PRESET_FIELDS = ("judge", "escalate", "drop_below", "report_at", "fail_at")


def auto_preset(environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    return next(name for name in AUTO_ORDER if all(environ.get(variable) for variable in PRESETS[name].needs))


def resolve(settings: Settings, environ: Mapping[str, str] | None = None) -> Settings:
    """The settings with the preset's judges and thresholds filled in wherever they were not set explicitly."""
    if settings.preset == "auto" and "judge" in settings.model_fields_set:
        # Your own judge: a preset's escalation and thresholds were measured for other judges, so none is added.
        update = {} if "escalate" in settings.model_fields_set else {"escalate": None}
        return settings.model_copy(update={**update, "preset": "custom"})
    name = settings.preset if settings.preset != "auto" else auto_preset(environ)
    if name not in PRESETS:
        raise ValueError(f"Unknown preset {name!r}; available: {', '.join(PRESETS)}")
    preset = PRESETS[name]
    update = {field: getattr(preset, field) for field in PRESET_FIELDS if field not in settings.model_fields_set}
    return settings.model_copy(update={**update, "preset": name})
