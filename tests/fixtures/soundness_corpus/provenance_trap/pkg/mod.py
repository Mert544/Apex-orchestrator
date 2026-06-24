"""Names that LOOK like stdlib ``dataclass`` / ``final`` but are something else.

ADVERSARIAL SHAPE (the round-16 shadow lesson): ``dataclass`` here is
``pydantic.dataclasses.dataclass`` (NOT ``dataclasses.dataclass``), and ``final``
is a locally-defined decorator (NOT ``typing.final``). freeze-dataclass must
refuse to add ``frozen=True`` to a non-stdlib dataclass, and add-final must refuse
to treat the shadowed ``final`` as ``typing.final`` — the provenance checks
(``_stdlib_dataclass_binding`` / ``_final_binding``) decline both.
"""

from pydantic.dataclasses import dataclass


def final(cls):
    """A local shadow of the name ``final`` — NOT ``typing.final``."""
    return cls


@dataclass
class Model:
    a: int = 1
    b: int = 2
