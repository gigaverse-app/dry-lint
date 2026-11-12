"""Optional integration facts owned by an extractor, independent of its implementation language."""

from dataclasses import dataclass
from importlib.metadata import entry_points

from dry_lint.models import matches_any
from dry_lint.plugins import BUILT_IN, plugin_class


@dataclass(frozen=True)
class ExtractorCapabilities:
    language_name: str = ""
    comment_prefix: str = "#"
    model_extractor: str | None = None
    is_model: bool = False
    index_modules: tuple[str, ...] = ()
    index_distributions: tuple[str, ...] = ()


def capabilities(extractor: object) -> ExtractorCapabilities:
    """Legacy plugins retain their old defaults, including the historical model-only naming convention."""
    return getattr(
        extractor, "capabilities", ExtractorCapabilities(is_model=getattr(extractor, "name", "").endswith("-models"))
    )


def extractor_class_for(path: str) -> type | None:
    """Resolve trusted installed adapters without constructing parsers or reading adopter settings."""
    for name in BUILT_IN["extractors"]:
        cls = plugin_class("extractors", name)
        if not capabilities(cls).is_model and matches_any(path, cls.files):
            return cls
    for point in entry_points(group="dry_lint.extractors"):
        if point.name in BUILT_IN["extractors"]:
            continue
        try:
            cls = point.load()
        except ImportError:
            # An unavailable unrelated optional plugin cannot break reporting for another language.
            continue
        if not capabilities(cls).is_model and matches_any(path, getattr(cls, "files", ())):
            return cls
    return None


def comment_style(path: str) -> ExtractorCapabilities:
    return capabilities(extractor_class_for(path))


def comment_prefixes(path: str) -> set[str]:
    """Keep historical cross-language decisions readable, plus the matching installed adapter's marker."""
    return {comment_style(path).comment_prefix} | {
        capabilities(plugin_class("extractors", name)).comment_prefix for name in BUILT_IN["extractors"]
    }
