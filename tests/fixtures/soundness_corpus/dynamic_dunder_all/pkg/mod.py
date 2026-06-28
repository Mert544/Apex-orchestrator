"""A module whose ``__all__`` is assembled DYNAMICALLY yet carries a literal duplicate.

ADVERSARIAL SHAPE (the dedup-dunder-all dynamic-__all__ trap): ``__all__`` is a
``BinOp`` (``_BASE + ["alpha", "alpha"]``) whose appended literal fragment repeats
``"alpha"``. A de-dup that edited only that literal fragment would change the exported
SET the dynamic ``_BASE`` part composes with — so dedup-dunder-all MUST refuse any
``__all__`` that is not a PURE literal list/tuple of string constants (the shared
sort-dunder-all gate sees the ``BinOp`` and declines). sort-dunder-all refuses it for
the same reason, so this fixture also pins that sibling boundary.

The bare functions carry no docstring, no annotation, and no provable return type, so
the document-* / infer-type-hints / pin-return-type family all decline them too — the
fixture isolates exactly the dynamic-``__all__`` refusal.
"""

_BASE = ["beta"]

__all__ = _BASE + ["alpha", "alpha"]


def alpha():
    return _BASE


def beta():
    return 0
