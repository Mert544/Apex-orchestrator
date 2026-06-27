"""Public, DOCUMENTED, ``-> T``-annotated functions whose docstrings ALREADY record
their return — one in each convention.

ADVERSARIAL SHAPE (the document-returns double-doc trap): each function here is a
document-returns candidate on its NAME + annotation + docstring, but its return is
ALREADY documented (a Google ``Returns:`` section, a Sphinx ``:rtype:`` field, a
NumPy ``Returns`` underline). document-returns MUST refuse every one — appending a
second return section would be a redundant double-doc its re-parse floor cannot
catch (a docstring changes no runtime value). pin-return-type refuses these too
(every function carries an explicit ``-> T``, so its inferred-return oracle
declines).
"""

from __future__ import annotations


def google_documented(x: int) -> int:
    """Add one to x.

    Args:
        x: the input.

    Returns:
        the input plus one.
    """
    return x + 1


def sphinx_documented(name: str) -> str:
    """Greet someone.

    :param name: who to greet.
    :rtype: str
    """
    return "hi " + name


def numpy_documented() -> dict[str, int]:
    """Build a tiny map.

    Returns
    -------
    dict[str, int]
        the built map.
    """
    return {"a": 1}
