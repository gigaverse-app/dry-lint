"""Judges decide whether a candidate pair is one concept implemented twice. They run apart from the detector."""

import os

from dry_lint.plugins import Judge, load
from dry_lint.settings import PluginChoice, Settings


def label_for(score: float, behaves_differently: float, settings: Settings) -> str:
    if score < settings.drop_below:
        return "separate"
    return "drifted" if behaves_differently >= settings.drift_at else "duplicate"


def make_judge(choice: PluginChoice, auto: tuple[str, str] = ("jev", "TYPESAFE_AI_API_KEY")) -> Judge | None:
    """
    The judge a settings slot names: a plugin, "none", or "auto": the `auto` judge when its key is in the
    environment (Jev and TYPESAFE_AI_API_KEY for `judge`), otherwise none.
    """
    name = choice.use
    if name == "auto":
        name = auto[0] if os.environ.get(auto[1]) else "none"
    if name == "none":
        return None
    return load("judges", choice.model_copy(update={"use": name}))


def make_escalation(settings: Settings) -> Judge | None:
    """The second judge: by default ("auto") Gemini when GEMINI_API_KEY is set, otherwise none."""
    return make_judge(settings.escalate, auto=("gemini", "GEMINI_API_KEY")) if settings.escalate else None
