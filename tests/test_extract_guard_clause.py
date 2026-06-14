from __future__ import annotations

import ast

from app.execution.extract_guard_clause import plan_extract_guard_clause


def _write(tmp_path, source: str, rel: str = "app/m.py") -> str:
    """Write ``source`` to ``rel`` under ``tmp_path`` (making ``app/``) and
    return the project-relative path."""
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / rel).write_text(source, encoding="utf-8")
    return rel


def _run_func(source: str, name: str, *args):
    """Exec ``source`` in a fresh namespace and call ``name(*args)``."""
    ns: dict = {}
    exec(compile(source, "<rewritten>", "exec"), ns)
    return ns[name](*args)


def test_canonical_guard_extraction(tmp_path):
    rel = _write(tmp_path, "def f(x):\n    if x > 0:\n        return x * 2\n")
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert plan.new_contents and not plan.blockers
    new = plan.new_contents[rel]
    assert new == (
        "def f(x):\n"
        "    if not (x > 0):\n"
        "        return\n"
        "    return x * 2\n"
    )
    # The nesting level under the body is gone — body sits at the function indent.
    ast.parse(new)


def test_exec_equivalence_true_and_false(tmp_path):
    src = "def f(x):\n    if x > 0:\n        return x * 2\n"
    rel = _write(tmp_path, src)
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    # cond true -> body runs; cond false -> falls off, returns None. Identical
    # before and after the rewrite.
    assert _run_func(src, "f", 5) == 10
    assert _run_func(new, "f", 5) == 10
    assert _run_func(src, "f", -1) is None
    assert _run_func(new, "f", -1) is None
    assert _run_func(new, "f", 0) is None


def test_docstring_preserved(tmp_path):
    rel = _write(
        tmp_path,
        'def f(x):\n'
        '    """Doc."""\n'
        '    if x:\n'
        '        return x + 1\n',
    )
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == (
        'def f(x):\n'
        '    """Doc."""\n'
        '    if not (x):\n'
        '        return\n'
        '    return x + 1\n'
    )
    assert _run_func(new, "f", 3) == 4
    assert _run_func(new, "f", 0) is None


def test_multi_statement_if_body_kept_multiline(tmp_path):
    # The if-body may be several statements; they all dedent together.
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    if x:\n"
        "        y = x + 1\n"
        "        return y * 2\n",
    )
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == (
        "def f(x):\n"
        "    if not (x):\n"
        "        return\n"
        "    y = x + 1\n"
        "    return y * 2\n"
    )
    assert _run_func(new, "f", 4) == 10
    assert _run_func(new, "f", 0) is None


def test_function_with_two_statements_untouched(tmp_path):
    # The if is NOT the whole body (a statement follows) -> no match.
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    if x:\n"
        "        return x\n"
        "    return 0\n",
    )
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_if_with_else_untouched(tmp_path):
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    if x:\n"
        "        return x\n"
        "    else:\n"
        "        return 0\n",
    )
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_if_with_elif_untouched(tmp_path):
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    if x > 0:\n"
        "        return 1\n"
        "    elif x < 0:\n"
        "        return -1\n",
    )
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_multiline_cond_untouched(tmp_path):
    rel = _write(
        tmp_path,
        "def f(a, b):\n"
        "    if (a > 0 and\n"
        "            b > 0):\n"
        "        return a + b\n",
    )
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_nested_method_in_class_handled(tmp_path):
    rel = _write(
        tmp_path,
        "class C:\n"
        "    def m(self, x):\n"
        "        if x > 1:\n"
        "            return x - 1\n",
    )
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == (
        "class C:\n"
        "    def m(self, x):\n"
        "        if not (x > 1):\n"
        "            return\n"
        "        return x - 1\n"
    )
    ns: dict = {}
    exec(compile(new, "<rewritten>", "exec"), ns)
    inst = ns["C"]()
    assert inst.m(5) == 4
    assert inst.m(0) is None


def test_async_function_handled(tmp_path):
    rel = _write(
        tmp_path,
        "async def f(x):\n"
        "    if x:\n"
        "        return x\n",
    )
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == (
        "async def f(x):\n"
        "    if not (x):\n"
        "        return\n"
        "    return x\n"
    )
    ast.parse(new)


def test_unparseable_source_blocks(tmp_path):
    rel = _write(tmp_path, "def f(:\n    pass\n")
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert plan.blockers and not plan.new_contents


def test_noop_on_clean_module(tmp_path):
    rel = _write(tmp_path, "x = 1\n")
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers  # empty no-op, not a failure


def test_missing_module_blocks(tmp_path):
    plan = plan_extract_guard_clause(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_fixture_subject_is_skipped(tmp_path):
    # A subject under tests/ is a fixture even if it matches the shape.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "def f(x):\n    if x:\n        return x\n", encoding="utf-8")
    plan = plan_extract_guard_clause(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_two_matching_functions_both_rewritten(tmp_path):
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    if x:\n"
        "        return x\n"
        "\n"
        "def g(y):\n"
        "    if y:\n"
        "        return y\n",
    )
    plan = plan_extract_guard_clause(str(tmp_path), rel)
    assert plan.edits_by_file[rel] == 2
    new = plan.new_contents[rel]
    assert new.count("if not (") == 2
    ast.parse(new)


def test_determinism(tmp_path):
    rel = _write(tmp_path, "def f(x):\n    if x > 0:\n        return x * 2\n")
    a = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    b = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert a == b


def test_membership_test_inverts_operator_not_wrapped(tmp_path):
    # ``if a in b`` must become ``if a not in b`` — wrapping it as
    # ``if not (a in b)`` is lint-dirty (ruff E713). The guard inverts in place.
    rel = _write(
        tmp_path,
        "def f(topic, subs):\n"
        "    if topic in subs:\n"
        "        return subs[topic]\n",
    )
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == (
        "def f(topic, subs):\n"
        "    if topic not in subs:\n"
        "        return\n"
        "    return subs[topic]\n"
    )
    assert "not (" not in new  # never the E713 shape
    assert _run_func(new, "f", "a", {"a": 1}) == 1
    assert _run_func(new, "f", "z", {"a": 1}) is None


def test_identity_test_inverts_operator(tmp_path):
    # ``if x is None`` -> ``if x is not None`` (not ``not (x is None)``, E714).
    rel = _write(
        tmp_path,
        "def f(x):\n"
        "    if x is None:\n"
        "        return 0\n",
    )
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert new == (
        "def f(x):\n"
        "    if x is not None:\n"
        "        return\n"
        "    return 0\n"
    )
    assert _run_func(new, "f", None) == 0
    assert _run_func(new, "f", 5) is None


def test_not_in_test_inverts_to_in(tmp_path):
    rel = _write(
        tmp_path,
        "def f(k, d):\n"
        "    if k not in d:\n"
        "        return None\n",
    )
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert "    if k in d:\n" in new
    assert "not (" not in new


def test_multi_operator_compare_falls_back_to_wrap(tmp_path):
    # A chained compare (a < b < c) is not a single-operator membership/identity
    # test, so it stays wrapped in ``not (...)`` — still correct, just not inverted.
    rel = _write(
        tmp_path,
        "def f(a, b, c):\n"
        "    if a < b < c:\n"
        "        return b\n",
    )
    new = plan_extract_guard_clause(str(tmp_path), rel).new_contents[rel]
    assert "    if not (a < b < c):\n" in new
    assert _run_func(new, "f", 1, 2, 3) == 2
    assert _run_func(new, "f", 3, 2, 1) is None


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "extract-guard-clause" in available_objectives()  # via the registry


def test_membership_inversion_parenthesises_low_precedence_operand(tmp_path):
    # `(a if c else d) in lst` -> `(a if c else d) not in lst`, never
    # `a if c else d not in lst` (== `a if c else (d not in lst)`).  [H5]
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "m.py").write_text(
        "def f(a, c, d, lst, x):\n    if (a if c else d) in lst:\n        return x\n",
        encoding="utf-8")
    new = plan_extract_guard_clause(str(tmp_path), "app/m.py").new_contents["app/m.py"]
    assert "if (a if c else d) not in lst:" in new
    ns: dict = {}
    exec(compile(new, "<m>", "exec"), ns)  # noqa: S102
    assert ns["f"](5, True, 99, [5], 10) == 10
    assert ns["f"](5, False, 99, [5], 10) is None
