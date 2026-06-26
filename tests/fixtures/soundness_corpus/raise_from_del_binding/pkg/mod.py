"""A B904 raise inside an ``except E as err:`` whose handler ``del``\\ s the binding.

ADVERSARIAL SHAPE (the raise-from del/unbound trap the syntax-only re-parse floor
misses): a fixable ``raise X(...)`` sits in a binding handler, so it LOOKS like a
clean ``raise … from err`` target. But the handler ``del``\\ s ``err`` BEFORE the
raise, so appending ``from err`` would reference an unbound name — at runtime the
re-raise becomes an ``UnboundLocalError`` (the WRONG exception type + changed
control flow), not the ``RuntimeError`` the original raised. The rewrite re-parses
cleanly, so the never-fake-green floor cannot see the behavior change.

raise-from MUST refuse it: ``_name_still_caught_exception`` sees the ``del err``
preceding the raise and declines, never landing a falsely-"behavior-preserving"
chain.
"""


def parse(value):
    try:
        return int(value)
    except ValueError as err:
        del err
        raise RuntimeError("bad value")
