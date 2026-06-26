"""A B904 raise inside an ``except E as err:`` whose handler REBINDS the binding.

ADVERSARIAL SHAPE (the raise-from wrong-cause trap): a fixable ``raise X(...)`` sits
in a binding handler, so it LOOKS like a clean ``raise … from err`` target. But the
handler reassigns ``err`` to a DIFFERENT, freshly-built exception BEFORE the raise,
so appending ``from err`` would set ``__cause__`` to that fabricated object — NOT
the originally-caught exception. The "chains to its original cause" claim is
falsified, yet the rewrite re-parses cleanly so the floor cannot see it.

raise-from MUST refuse it: ``_name_still_caught_exception`` sees ``err`` (re)bound
before the raise and declines, never chaining a semantically-wrong cause.
"""


def parse(value):
    try:
        return int(value)
    except ValueError as err:
        err = KeyError("rebound")
        raise RuntimeError("bad value")
