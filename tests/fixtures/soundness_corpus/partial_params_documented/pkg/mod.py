"""Public, DOCUMENTED functions carrying DECLARED parameter annotations whose
docstrings document SOME parameters but not all — the PARTIAL-documentation trap.

ADVERSARIAL SHAPE: each function already records one parameter (a Google ``Args:``
block with a single line, or one Sphinx ``:param:`` field) while a sibling
declared-annotated parameter is left undocumented. document-param MUST refuse the
WHOLE function — merging a new line into a half-filled block is fragile, corrupts
ordering, and the re-parse floor cannot catch a redundant/duplicate param line. The
honest move is to refuse, never to half-fill.

These functions carry NO ``-> T`` return annotation and return a parameter (an
ambiguous, non-literal body), so document-returns / pin-return-type refuse them on
the annotation / oracle gates.
"""

from __future__ import annotations


def google_partial(first: int, second: str):
    """Use both inputs.

    Args:
        first (int): only the FIRST parameter is documented; ``second`` is missing.
    """
    return second if first else second


def sphinx_partial(host: str, port: int):
    """Connect somewhere.

    :param host: only ``host`` is documented; ``port`` is missing.
    :type host: str
    """
    return host if port else host
