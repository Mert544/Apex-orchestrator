"""A B904 raise whose source text ALSO appears in a string literal on its line.

ADVERSARIAL SHAPE (the raise-from textual-``str.replace`` corruption trap, P0-#1):
the physical line holds ``tag = "raise RuntimeError(...)"; raise RuntimeError(...)``
— the raise's own source segment occurs FIRST inside the string literal. A textual
``line.replace(seg, seg + " from err", 1)`` would splice ``from err`` INTO the
string literal, leave the REAL raise un-caused, re-parse cleanly (the never-fake-
green floor is blind to a same-text splice) and — because fitness never reaches 0 —
churn ``" from err from err …"`` forever (a non-idempotent corruption loop).

raise-from must NOT corrupt it: the COLUMN-OFFSET splice inserts ``from err`` at the
raise's ``end_col_offset`` (the exact position past the raise expression), so the
string literal is untouched and the REAL raise is chained. The audit therefore sees
a single, behavior-identical, idempotent rewrite (re-parses; a second pass is a
byte-no-op) — never the textual-replace corruption.
"""


def parse(value):
    try:
        return int(value)
    except ValueError as err:
        tag = "raise RuntimeError(1)"; raise RuntimeError(1)
