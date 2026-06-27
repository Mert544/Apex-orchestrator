"""Public, DOCUMENTED functions carrying DECLARED parameter annotations whose
docstrings ALREADY record their parameters — one in each convention.

ADVERSARIAL SHAPE (the document-param double-doc trap): each function here is a
document-param candidate on its NAME + at least one declared parameter annotation +
docstring, but its parameters are ALREADY documented (a Google ``Args:`` section, a
Sphinx ``:param:`` field, a NumPy ``Parameters`` underline). document-param MUST
refuse every one — appending a second ``Args:`` section would be a redundant
double-doc its re-parse floor cannot catch (a docstring changes no runtime value).

These functions carry NO ``-> T`` return annotation and return a parameter (an
ambiguous, non-literal body), so document-returns refuses (no annotation) and
pin-return-type refuses (the inferred-return oracle declines an ambiguous body) —
the corpus needs no separate annotation-free shape for those siblings.
"""

from __future__ import annotations


def google_documented(x: int, y: str):
    """Combine x and y.

    Args:
        x (int): the count.
        y (str): the label.
    """
    return y if x else y


def sphinx_documented(name: str, repeat: int):
    """Render a name.

    :param name: who to render.
    :type name: str
    :param repeat: how many times.
    :type repeat: int
    """
    return name if repeat else name


def numpy_documented(value: dict[str, int]):
    """Inspect a tiny map.

    Parameters
    ----------
    value : dict[str, int]
        the map to inspect.
    """
    return value
