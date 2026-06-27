"""Public, DOCUMENTED, subscripted iterator/generator-annotated GENERATORS (a
``yield`` in their own scope) whose docstrings ALREADY record their yield — one in
each convention.

ADVERSARIAL SHAPE (the document-yields double-doc trap): each function here is a
document-yields candidate on its NAME + iterator/generator annotation + ``yield`` +
docstring, but its yield is ALREADY documented (a Google ``Yields:`` section, a
Sphinx ``:ytype:`` field). document-yields MUST refuse every one — appending a second
``Yields:`` section would be a redundant double-doc its re-parse floor cannot catch
(a docstring changes no runtime value). document-returns refuses these too BY
CONSTRUCTION: each carries an iterator/generator return, which is in its
``_GENERATOR_RETURNS`` refuse-head set (a generator never gets a ``Returns:``) — so
the fixture also pins the document-returns <-> document-yields mutual exclusion.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator


def google_documented(n: int) -> Iterator[int]:
    """Yield ``n`` ascending ints.

    Args:
        n: how many to yield.

    Yields:
        the next int.
    """
    yield from range(n)


def sphinx_documented(rows: list[str]) -> Iterator[str]:
    """Yield each row.

    :param rows: the rows to stream.
    :ytype: str
    """
    yield from rows


def generator_documented() -> Generator[bytes, None, None]:
    """Stream byte chunks.

    Yields:
        the next chunk.
    """
    yield b"chunk"
