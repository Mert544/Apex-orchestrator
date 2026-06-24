"""A dataclass whose decorator is NOT a single-line rewritable ``@dataclass``.

ADVERSARIAL SHAPE: ``@dataclass(**opts)`` uses ``**``-unpacking, so the keyword
set (and whether ``frozen`` is already configured) is not statically knowable.
freeze-dataclass must REFUSE (``_decorator_has_frozen`` cannot prove the absence
of ``frozen``, and the call is not single-line rewritable) rather than splice a
``frozen=True`` into an opaque decorator.
"""

from dataclasses import dataclass

_OPTS = {"eq": True}


@dataclass(**_OPTS)
class Config:
    host: str = "localhost"
    port: int = 8080
