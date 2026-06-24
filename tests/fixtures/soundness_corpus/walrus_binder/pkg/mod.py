"""A module with unmodelled top-level binders the public-name analysis can't model.

ADVERSARIAL SHAPE: a module-level walrus (``:=``), a top-level ``for`` /
``with`` / ``try`` binding a public name, a tuple-unpack, and a ``del``. The
defined-public-names collector returns None on any of these (``has_walrus`` /
``_collect_defined_names`` -> None), so wire-module-exports must REFUSE rather
than land an ``__all__`` over an incompletely-modelled public surface.
"""

import os

if (sep_len := len(os.sep)) > 0:
    DERIVED = sep_len

FIRST, SECOND = 1, 2

for _name in ("alpha", "beta"):
    LAST_NAME = _name

del _name


def public_w():
    return DERIVED + FIRST + SECOND
