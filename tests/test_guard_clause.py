from __future__ import annotations

import ast

from app.execution.guard_clause import plan_guard_clause


def _write(tmp_path, source: str, rel: str = "app/m.py") -> str:
    """Write ``source`` to ``rel`` under ``tmp_path`` (making ``app/``) and
    return the project-relative path."""
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / rel).write_text(source, encoding="utf-8")
    return rel


def _run_func(source: str, name: str, *args):
    """Exec ``source`` in a fresh namespace and call ``name(*args)``."""
    ns: dict = {}
    exec(compile(source, "<rewritten>", "exec"), ns)  # noqa: S102
    return ns[name](*args)


# --------------------------------------------------------------------------- #
# Positive cases: a trailing else-less if PRECEDED by real setup is flattened.
# --------------------------------------------------------------------------- #

def test_canonical_flatten_with_setup(tmp_path):
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    y = x + 1\n"
        "    if x > 0:\n"
        "        return y * 2\n",
    )
    plan = plan_guard_clause(str(tmp_path), rel)
    assert plan.new_contents and not plan.blockers
    new = plan.new_contents[rel]
    assert new == (
        "def f(x):\n"
        "    y = x + 1\n"
        "    if not (x > 0):\n"
        "        return\n"
        "    return y * 2\n"
    )
    ast.parse(new)


def test_exec_equivalence_true_and_false(tmp_path):
    src = (
        "def f(x):\n"
        "    y = x + 1\n"
        "    if x > 0:\n"
        "        return y * 2\n"
    )
    rel = _write(tmp_path, src)
    new = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    # The setup runs in both forms; cond true -> body, cond false -> None.
    assert _run_func(src, "f", 5) == _run_func(new, "f", 5) == 12
    assert _run_func(src, "f", -1) is None
    assert _run_func(new, "f", -1) is None
    assert _run_func(new, "f", 0) is None


def test_multi_statement_setup_and_body(tmp_path):
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    a = 1\n"
        "    b = 2\n"
        "    if x:\n"
        "        c = a + b\n"
        "        return c + x\n",
    )
    new = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == (
        "def f(x):\n"
        "    a = 1\n"
        "    b = 2\n"
        "    if not (x):\n"
        "        return\n"
        "    c = a + b\n"
        "    return c + x\n"
    )
    assert _run_func(new, "f", 4) == 7
    assert _run_func(new, "f", 0) is None


def test_docstring_plus_setup_flattened(tmp_path):
    # A leading docstring does NOT count as setup, but a real statement after it
    # does, so this still fires (and leaves the docstring in place).
    rel = _write(
        tmp_path,
        'def f(x):\n'
        '    """Doc."""\n'
        '    y = x\n'
        '    if y:\n'
        '        return y + 1\n',
    )
    new = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == (
        'def f(x):\n'
        '    """Doc."""\n'
        '    y = x\n'
        '    if not (y):\n'
        '        return\n'
        '    return y + 1\n'
    )
    assert _run_func(new, "f", 3) == 4
    assert _run_func(new, "f", 0) is None


def test_comment_in_setup_preserved(tmp_path):
    # The setup region (including comments) is left byte-for-byte untouched.
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    # important note\n"
        "    y = x\n"
        "    if y:\n"
        "        return y\n",
    )
    new = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert "    # important note\n" in new
    assert "    if not (y):\n" in new


# --------------------------------------------------------------------------- #
# Condition-inversion correctness (the precedence guarantee).
# --------------------------------------------------------------------------- #

def test_and_inverts_parenthesised(tmp_path):
    # `if a and b:` MUST become `if not (a and b):`, never `if not a and b:`.
    rel = _write(
        tmp_path,
        "def f(a, b):\n"
        "    s = 1\n"
        "    if a and b:\n"
        "        return s\n",
    )
    new = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert "    if not (a and b):\n" in new
    # Equivalence across the truth table for `a and b`.
    for a in (True, False):
        for b in (True, False):
            assert (_run_func(new, "f", a, b) == 1) == (a and b)


def test_or_inverts_parenthesised(tmp_path):
    # `if a or b:` MUST become `if not (a or b):`, never `if not a or b:`.
    rel = _write(
        tmp_path,
        "def f(a, b):\n"
        "    s = 1\n"
        "    if a or b:\n"
        "        return s\n",
    )
    new = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert "    if not (a or b):\n" in new
    for a in (True, False):
        for b in (True, False):
            assert (_run_func(new, "f", a, b) == 1) == (a or b)


def test_equality_compare_wraps(tmp_path):
    # An equality compare is not a membership/identity op, so it wraps as
    # `not (x == 1)` — still precedence-correct and semantically exact.
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    s = 1\n"
        "    if x == 1:\n"
        "        return s\n",
    )
    new = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert "    if not (x == 1):\n" in new
    assert _run_func(new, "f", 1) == 1
    assert _run_func(new, "f", 2) is None


def test_membership_test_inverts_operator(tmp_path):
    # `if a in b` -> `if a not in b` (not the E713 `not (a in b)`).
    rel = _write(
        tmp_path,
        "def f(k, d):\n"
        "    s = 1\n"
        "    if k in d:\n"
        "        return d[k]\n",
    )
    new = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert "    if k not in d:\n" in new
    assert "not (" not in new
    assert _run_func(new, "f", "a", {"a": 9}) == 9
    assert _run_func(new, "f", "z", {"a": 9}) is None


def test_identity_test_inverts_operator(tmp_path):
    # `if x is None` -> `if x is not None` (not the E714 `not (x is None)`).
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    s = 1\n"
        "    if x is None:\n"
        "        return s\n",
    )
    new = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert "    if x is not None:\n" in new
    assert "not (" not in new
    assert _run_func(new, "f", None) == 1
    assert _run_func(new, "f", 5) is None


def test_chained_compare_wraps(tmp_path):
    # A chained compare (a < b < c) is not single-operator membership/identity,
    # so it stays wrapped as `not (a < b < c)` — correct, just not inverted.
    rel = _write(
        tmp_path,
        "def f(a, b, c):\n"
        "    s = b\n"
        "    if a < b < c:\n"
        "        return s\n",
    )
    new = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert "    if not (a < b < c):\n" in new
    assert _run_func(new, "f", 1, 2, 3) == 2
    assert _run_func(new, "f", 3, 2, 1) is None


# --------------------------------------------------------------------------- #
# Negative cases: shapes that must NOT transform (no finding).
# --------------------------------------------------------------------------- #

def test_sole_if_no_setup_untouched(tmp_path):
    # The if is the WHOLE body — that's extract-guard-clause's territory; this
    # objective must NOT fire (the two stay disjoint).
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    if x:\n"
        "        return x\n",
    )
    plan = plan_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_only_docstring_before_if_untouched(tmp_path):
    # A lone leading docstring is not "setup", so this is still the sole-if shape.
    rel = _write(
        tmp_path,
        'def f(x):\n'
        '    """Doc."""\n'
        '    if x:\n'
        '        return x\n',
    )
    plan = plan_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_if_with_else_untouched(tmp_path):
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    s = 1\n"
        "    if x:\n"
        "        return x\n"
        "    else:\n"
        "        return s\n",
    )
    plan = plan_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_if_with_elif_untouched(tmp_path):
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    s = 1\n"
        "    if x > 0:\n"
        "        return 1\n"
        "    elif x < 0:\n"
        "        return -1\n",
    )
    plan = plan_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_if_not_last_untouched(tmp_path):
    # A statement (a meaningful return) follows the if, so flattening would
    # reorder semantics — no finding.
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    s = 1\n"
        "    if x:\n"
        "        s = 2\n"
        "    return s\n",
    )
    plan = plan_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_multiline_cond_untouched(tmp_path):
    rel = _write(
        tmp_path,
        "def f(a, b):\n"
        "    s = 1\n"
        "    if (a > 0 and\n"
        "            b > 0):\n"
        "        return a + b\n",
    )
    plan = plan_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_nested_inner_function_not_double_counted(tmp_path):
    # The inner function (whole-body if) is extract-guard-clause's shape, so it
    # is not matched here; the OUTER ends in a real if after setup, so only it
    # fires — exactly one edit, and the result re-parses.
    rel = _write(
        tmp_path,
        "def outer(x):\n"
        "    def inner(y):\n"
        "        if y:\n"
        "            return y\n"
        "    z = inner(x)\n"
        "    if z:\n"
        "        return z + 1\n",
    )
    plan = plan_guard_clause(str(tmp_path), rel)
    assert plan.edits_by_file[rel] == 1
    new = plan.new_contents[rel]
    assert "    if not (z):\n" in new
    # inner's `if y:` is left alone (its whole-body shape is not ours).
    assert "        if y:\n" in new
    ast.parse(new)


# --------------------------------------------------------------------------- #
# Structural / plumbing cases.
# --------------------------------------------------------------------------- #

def test_async_function_handled(tmp_path):
    rel = _write(
        tmp_path,
        "async def f(x):\n"
        "    y = x\n"
        "    if y:\n"
        "        return y\n",
    )
    new = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == (
        "async def f(x):\n"
        "    y = x\n"
        "    if not (y):\n"
        "        return\n"
        "    return y\n"
    )
    ast.parse(new)


def test_method_in_class_handled(tmp_path):
    rel = _write(
        tmp_path,
        "class C:\n"
        "    def m(self, x):\n"
        "        n = x\n"
        "        if n > 1:\n"
        "            return n - 1\n",
    )
    new = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == (
        "class C:\n"
        "    def m(self, x):\n"
        "        n = x\n"
        "        if not (n > 1):\n"
        "            return\n"
        "        return n - 1\n"
    )
    ns: dict = {}
    exec(compile(new, "<rewritten>", "exec"), ns)  # noqa: S102
    inst = ns["C"]()
    assert inst.m(5) == 4
    assert inst.m(0) is None


def test_two_matching_functions_both_rewritten(tmp_path):
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    a = 1\n"
        "    if x:\n"
        "        return x\n"
        "\n"
        "def g(y):\n"
        "    b = 2\n"
        "    if y:\n"
        "        return y\n",
    )
    plan = plan_guard_clause(str(tmp_path), rel)
    assert plan.edits_by_file[rel] == 2
    new = plan.new_contents[rel]
    assert new.count("if not (") == 2
    ast.parse(new)


def test_unparseable_source_blocks(tmp_path):
    rel = _write(tmp_path, "def f(:\n    pass\n")
    plan = plan_guard_clause(str(tmp_path), rel)
    assert plan.blockers and not plan.new_contents


def test_noop_on_clean_module(tmp_path):
    rel = _write(tmp_path, "x = 1\n")
    plan = plan_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_missing_module_blocks(tmp_path):
    plan = plan_guard_clause(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_fixture_subject_is_skipped(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def f(x):\n    a = 1\n    if x:\n        return x\n", encoding="utf-8")
    plan = plan_guard_clause(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_determinism(tmp_path):
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    y = x + 1\n"
        "    if x > 0:\n"
        "        return y * 2\n",
    )
    a = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    b = plan_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert a == b


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "guard-clause" in available_objectives()  # via the registry
