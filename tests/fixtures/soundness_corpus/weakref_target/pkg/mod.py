"""A clean slottable class whose instance is WEAK-REFERENCED in the same module.

ADVERSARIAL SHAPE (the add-slots READ-path trap the STORE-only scan misses):
``_Node`` has a boilerplate, closed ``__init__`` attribute set and no dynamic store,
so the whole-project mutated-attribute superset proof would happily slot it. But
``__slots__`` (without ``__weakref__`` in the tuple) drops the per-instance weakref
support, so ``weakref.ref(node)`` would raise ``TypeError`` ("cannot create weak
reference") at runtime — a SILENT behavior change. add-slots MUST refuse it: the
project-wide weakref scan sees the ``weakref.ref`` call and declines (it cannot prove
``_Node``'s instances never flow to that site), never landing a falsely-"behavior-
identical-storage" slot tuple.
"""

import weakref


class _Node:
    def __init__(self, value, parent):
        self.value = value
        self.parent = parent


def _track(node):
    """Take a WEAK reference to a node — the read path ``__slots__`` would break."""
    return weakref.ref(node)
