"""A module that ALREADY carries every construct the objectives would land.

ADVERSARIAL SHAPE (idempotence, S6): it already declares ``__all__``, already
seals its leaf class ``@final``, and already has ``frozen=True``. A second run of
wire-module-exports / add-final / freeze-dataclass must be a byte-identical no-op
— they must refuse to re-apply what is already present.
"""

from dataclasses import dataclass
from typing import final

__all__ = ["Point", "origin"]


@final
@dataclass(frozen=True)
class Point:
    x: int = 0
    y: int = 0


def origin():
    return Point(0, 0)
