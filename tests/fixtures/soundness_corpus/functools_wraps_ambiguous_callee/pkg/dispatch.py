"""An AMBIGUOUS-CALLEE trap for the soundness corpus — the shape
add-functools-wraps MUST refuse, never guess.

``combine``'s inner ``wrapper`` calls BOTH of the outer's parameters
(``primary`` AND ``fallback``) — so which one is "the" wrapped callee
``@functools.wraps(...)`` should name is NOT provable from the shape alone. A
naive detector that only asks "is exactly one parameter callable" (rather than
"is exactly one parameter ACTUALLY CALLED inside the wrapper") would wrongly
pick one of the two by accident (e.g. list order) and land
``@functools.wraps`` on the WRONG callee — a metadata lie about the wrapper's
true identity. add-functools-wraps refuses the WHOLE ``wrapper`` here: two
outer parameters are called inside it, so no single callee is provable.
"""

from __future__ import annotations


def combine(primary, fallback):
    """A decorator factory taking TWO callables — deliberately ambiguous."""

    def wrapper(*args, **kwargs):
        try:
            return primary(*args, **kwargs)
        except Exception:
            return fallback(*args, **kwargs)

    return wrapper
