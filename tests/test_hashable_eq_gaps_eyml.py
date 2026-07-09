"""Coverage gap for :mod:`app.execution.hashable_eq` — the one missing branch the
objective suite (``test_seal_hashable_eq_objective_eyml``) does not already hit: a
DOTTED ``@dataclasses.dataclass`` decorator (an ``Attribute`` whose final ``.attr`` is
``dataclass``), which ``_is_dataclass_decorated`` must recognise so the class is
refused (dataclassify / freeze own its ``eq=``/hash story).

The module is at 99% — this is a targeted regression locking the dotted-dataclass
refusal, plus a bare-``@dataclass`` characterization for symmetry. Deterministic (pure
AST + line splice, no clock/random/network).
"""

from __future__ import annotations

from app.execution.hashable_eq import hashable_eq_classes, seal_hashable_eq

# A class that — but for its ``@dataclass`` decorator — would gain a restored
# ``__hash__`` (body ``__eq__``, no ``__hash__``, a pure ``self.x = x`` copy field).
_EQ_BODY = (
    "    def __init__(self, x):\n"
    "        self.x = x\n"
    "    def __eq__(self, other):\n"
    "        return self.x == other.x\n"
)


def test_refuses_dotted_dataclass_decorated_class():
    # ``@dataclasses.dataclass`` is an Attribute decorator whose ``.attr`` is
    # ``dataclass`` — ``_is_dataclass_decorated`` recognises the dotted spelling and
    # refuses (the dataclass path owns eq=/hash).
    src = "@dataclasses.dataclass\nclass C:\n" + _EQ_BODY
    assert hashable_eq_classes(src) == []
    assert seal_hashable_eq(src) is None


def test_refuses_bare_dataclass_decorated_class():
    # Symmetric characterization: a bare ``@dataclass`` name decorator is likewise
    # refused. Non-tautological — the SAME class body without the decorator is sealed.
    decorated = "@dataclass\nclass C:\n" + _EQ_BODY
    plain = "class C:\n" + _EQ_BODY
    assert hashable_eq_classes(decorated) == []
    assert hashable_eq_classes(plain) == ["C"]  # only the decorator suppresses it
