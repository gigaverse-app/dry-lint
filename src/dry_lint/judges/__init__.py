"""Judges decide whether a candidate pair is one concept implemented twice. They run apart from the detector."""

import os

from dry_lint.plugins import Judge, load
from dry_lint.settings import PluginChoice, Settings


def label_for(score: float, behaves_differently: float, settings: Settings) -> str:
    if score < settings.drop_below:
        return "separate"
    return "drifted" if behaves_differently >= settings.drift_at else "duplicate"


def make_judge(choice: PluginChoice) -> Judge | None:
    """The judge a settings slot names: a plugin, "none", or "auto" (Jev when TYPESAFE_AI_API_KEY is set, else none)."""
    name = choice.use
    if name == "auto":
        name = "jev" if os.environ.get("TYPESAFE_AI_API_KEY") else "none"
    if name == "none":
        return None
    return load("judges", choice.model_copy(update={"use": name}))
