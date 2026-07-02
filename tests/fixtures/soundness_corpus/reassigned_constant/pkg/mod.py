"""A module CONSTANT that LOOKS never-rebound but IS reassigned later.

ADVERSARIAL SHAPE (the Python module-scope analogue of ``java_reassigned_local``):
``MAX_RETRIES`` is a top-level ``UPPER_SNAKE`` constant with a literal value — it
LOOKS finalizable to a declaration-only glance. But ``bump`` REBINDS it via a
``global`` assignment, so annotating it ``typing.Final`` would be a TYPE ERROR a
checker rejects on the reassignment. ``Final`` is a pure runtime no-op, so a green
suite could never catch that false "final". finalize-module-constant must refuse it
— the whole-project rebind scan sees both the ``global`` declaration and the later
``MAX_RETRIES = ...`` store and omits the name from the finalizable set.

``LIMIT`` is here as a NON-finalizable control of a different flavour (rebound by a
plain module-scope ``=`` in a branch, no ``global`` needed), so the fixture proves
BOTH rebind shapes are refused. Neither constant is ever sealed.
"""


MAX_RETRIES = 3

LIMIT = 100


def bump() -> int:
    """Rebind the module constant — the reassignment `Final` would forbid."""
    global MAX_RETRIES
    MAX_RETRIES = MAX_RETRIES + 1
    return MAX_RETRIES


def reset(flag: bool) -> None:
    """A branch that rebinds ``LIMIT`` at module scope indirectly is emulated by a
    plain reassignment below; here we only READ it, to keep this a pure function."""
    if flag:
        _ = LIMIT


# A later plain module-scope rebind of LIMIT — a real reassignment the rebind scan
# catches, so LIMIT is not finalizable either.
LIMIT = 200
