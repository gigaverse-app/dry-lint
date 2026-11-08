"""Resources owned by one detection call; plugins own their keys and values."""

from threading import RLock

from dry_lint.plugins import plugin_class


class ComparerResources:
    """No ambient/global state. Failed factories never publish reusable resources."""

    def __init__(self):
        self._values = {}
        self.lock = RLock()

    def get(self, key, factory):
        with self.lock:
            if key not in self._values:
                self._values[key] = factory()
            return self._values[key]

    def load(self, choice):
        cls = plugin_class("comparers", choice.use)
        factory = getattr(cls, "for_run", None)
        return factory(self, **choice.options()) if factory else cls(**choice.options())

    def index(self, comparer, functions):
        index = getattr(comparer, "index_for_run", None)
        if index:
            index(functions, self)
        else:
            comparer.index(functions)
