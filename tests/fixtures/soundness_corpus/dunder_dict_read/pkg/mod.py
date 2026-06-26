"""A clean slottable class whose instance ``__dict__`` is READ in the same module.

ADVERSARIAL SHAPE (the add-slots READ-path trap the STORE-only scan misses): ``_Conf``
has a boilerplate, closed ``__init__`` attribute set and no dynamic store, so the
whole-project mutated-attribute superset proof would happily slot it. But ``__slots__``
(without ``__dict__`` in the tuple) drops the per-instance ``__dict__``, so the
``conf.__dict__`` READ here would raise ``AttributeError`` at runtime — a SILENT
behavior change (this is a READ, NOT the ``conf.__dict__[...] =`` store the existing
enumerability gate already catches). add-slots MUST refuse it: the project-wide
``__dict__``-read scan sees the load and declines, never landing a falsely-"behavior-
identical-storage" slot tuple.
"""


class _Conf:
    def __init__(self, host, port):
        self.host = host
        self.port = port


def _as_mapping(conf):
    """READ the instance ``__dict__`` — the read path ``__slots__`` would break."""
    return dict(conf.__dict__)
