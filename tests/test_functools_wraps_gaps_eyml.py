"""Coverage gaps for :mod:`app.execution.functools_wraps` — the missing rebind-shape,
parse-guard, and defensive branches the objective suite
(``test_add_functools_wraps_objective_eyml``) does not already hit:

  - a callee parameter REBOUND by a nested ``def`` of the SAME name before the wrapper
    closes over it (``_name_rebound_before`` matching a ``FunctionDef`` target) — a
    refusal, so nothing is wrapped;
  - a SYNTAX ERROR in ``source`` — ``wrappable_functions`` returns ``[]`` via its own
    parse guard;
  - the two DEFENSIVE guards (an empty-body ``FunctionDef`` in ``_returned_wrapper_name``
    and the "wrapper not among outer's statements" tail of ``_name_rebound_before``)
    that are unreachable through parsed source but documented, exercised here directly
    as characterization.

Everything deterministic (pure AST + line splice, no clock/random/network).
"""

from __future__ import annotations

import ast

from app.execution.functools_wraps import (
    _name_rebound_before,
    _returned_wrapper_name,
    wrappable_functions,
)


def test_refuses_callee_rebound_by_nested_def():
    # The callee ``func`` is REBOUND by a nested ``def func`` before ``wrapper`` closes
    # over it — ``_name_rebound_before`` matches the nested ``FunctionDef`` target and
    # refuses (``func`` inside the wrapper would not be the parameter).
    src = (
        "def outer(func):\n"
        "    def func():\n"
        "        return 0\n"
        "    def wrapper(*a, **k):\n"
        "        return func(*a, **k)\n"
        "    return wrapper\n"
    )
    assert wrappable_functions(src) == []


def test_syntax_error_yields_empty_list():
    # An unparseable source returns ``[]`` (the module-wide parse guard).
    assert wrappable_functions("def (") == []


def test_returned_wrapper_name_none_for_empty_body():
    # Defensive guard: an empty-body function (impossible via parse, so constructed
    # directly) has no ``return <name>`` tail — ``_returned_wrapper_name`` returns
    # ``None``.
    fn = ast.parse("def f():\n    return g\n").body[0]
    fn.body = []
    assert _returned_wrapper_name(fn) is None


def test_name_rebound_before_false_when_wrapper_not_in_body():
    # Defensive tail: when the supplied ``wrapper`` is NOT among the outer's own
    # statements (never happens via ``_wrap_target``, constructed here), the scan
    # completes without a rebind and returns ``False``.
    outer = ast.parse("def outer(func):\n    x = 1\n    return x\n").body[0]
    stranger = ast.parse("def stranger():\n    pass\n").body[0]
    assert _name_rebound_before(outer, stranger, "func") is False
