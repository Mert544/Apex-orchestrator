"""Public, DOCUMENTED classes with class-level annotated fields whose docstrings
ALREADY document their attributes — fully (one per convention) and PARTIALLY.

ADVERSARIAL SHAPE (the document-attributes double-doc trap): each class here is a
document-attributes candidate on its NAME + class-level annotations + docstring, but
its attributes are ALREADY documented (a Google ``Attributes:`` section, a Sphinx
``:ivar:`` field, a NumPy ``Attributes`` underline) OR PARTIALLY documented (a
half-filled ``Attributes:`` block that names only one of two fields). document-
attributes MUST refuse every one — appending a second ``Attributes:`` section, or
merging into the author's partial block, would be a redundant / corrupting double-doc
its re-parse floor cannot catch (a docstring changes no runtime value).
"""

from __future__ import annotations


class GoogleDocumented:
    """A small config.

    Attributes:
        host: the hostname.
        port: the port.
    """

    host: str
    port: int = 80


class SphinxDocumented:
    """A render target.

    :ivar width: the width.
    :ivar height: the height.
    """

    width: int
    height: int


class NumpyDocumented:
    """A tiny window.

    Attributes
    ----------
    title : str
        the window title.
    """

    title: str


class PartiallyDocumented:
    """A connection.

    Attributes:
        host: the hostname.
    """

    host: str
    port: int = 80
