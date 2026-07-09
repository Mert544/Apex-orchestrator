"""seal-total-ordering — coverage gaps for the transform helpers.

Targets the last uncovered lines of :mod:`app.execution.total_ordering` (the
module is otherwise exercised by ``test_seal_total_ordering_objective_eyml``):

* ``orderable_classes`` on unparseable source -> ``[]`` (never crash);
* the ``_fold_import`` "other" branch — ``total_ordering`` bound as an IMPORTED
  MODULE (``import total_ordering``) is a differently-sourced binding, so no bare
  ``@total_ordering`` is provably ``functools.total_ordering`` -> refuse;
* the not-cleanly-widenable ``from functools import ...`` line detector — an inline
  ``#`` comment OR a trailing ``\\`` continuation forces a FRESH import line rather
  than an unsafe string-split widen of the existing block.
"""

from __future__ import annotations

import ast

from app.execution.total_ordering import orderable_classes, seal_total_ordering

# ``__eq__`` + exactly one order op — the exact eligible body shape.
_EQ = "    def __eq__(self, o):\n        return self.x == o.x\n"
_LT = "    def __lt__(self, o):\n        return self.x < o.x\n"


def test_orderable_classes_empty_on_syntax_error():
    # A module that does not parse yields no orderable classes (honest no-op).
    assert orderable_classes("def (:\n") == []
    assert orderable_classes("class C(:\n") == []


def test_refuses_when_total_ordering_is_an_imported_module():
    # ``import total_ordering`` binds the name to a (differently-sourced) MODULE,
    # not ``functools.total_ordering`` — a bare ``@total_ordering`` would be the
    # wrong callable and ``functools`` is not bound, so the class is refused.
    src = "import total_ordering\nclass C:\n" + _EQ + _LT
    assert orderable_classes(src) == []
    assert seal_total_ordering(src) is None


def test_inserts_fresh_import_when_functools_import_has_inline_comment():
    # A ``from functools import reduce  # keep`` line carries an inline comment, so
    # it is NOT cleanly widenable by the string splitter — a fresh
    # ``from functools import total_ordering`` line is inserted instead and the
    # commented import is left byte-for-byte untouched.
    src = "from functools import reduce  # keep\nclass C:\n" + _EQ + _LT
    out = seal_total_ordering(src)
    assert out is not None
    assert "from functools import reduce  # keep" in out  # original untouched
    assert "from functools import total_ordering" in out  # fresh line inserted
    assert "@total_ordering" in out
    ast.parse(out)  # never lands broken Python


def test_inserts_fresh_import_when_functools_import_uses_line_continuation():
    # A backslash line-continuation ``from functools import \`` is a multi-line
    # logical import the naive splitter cannot re-emit safely, so — like the
    # commented case — a fresh import line is inserted rather than widening it.
    src = ("from functools import \\\n"
           "    reduce\n"
           "class C:\n" + _EQ + _LT)
    out = seal_total_ordering(src)
    assert out is not None
    assert "from functools import \\" in out  # continuation block untouched
    assert "from functools import total_ordering" in out  # fresh line inserted
    assert "@total_ordering" in out
    ast.parse(out)
