from __future__ import annotations

import ast

from app.execution.fix_not_in_is import plan_fix_not_in_is


def _write(tmp_path, body: str, rel: str = "app/m.py") -> str:
    """Write a module under ``tmp_path`` and return its project-relative path."""
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return rel


def _rewrite(tmp_path, body: str, rel: str = "app/m.py") -> str:
    """Run the plan over ``body`` and return the rewritten source (asserts it
    actually changed and re-parses)."""
    _write(tmp_path, body, rel)
    plan = plan_fix_not_in_is(str(tmp_path), rel)
    assert not plan.blockers, plan.blockers
    assert plan.new_contents, "expected a rewrite"
    new = plan.new_contents[rel]
    ast.parse(new)  # must re-parse
    return new


# --- core rewrites ---------------------------------------------------------

def test_not_a_in_b(tmp_path):
    new = _rewrite(tmp_path, "y = not a in b\n")
    assert new == "y = a not in b\n"


def test_not_a_is_b(tmp_path):
    new = _rewrite(tmp_path, "y = not a is b\n")
    assert new == "y = a is not b\n"


def test_attribute_and_subscript_operands_preserved(tmp_path):
    new = _rewrite(tmp_path, "y = not obj.attr in data[key]\n")
    assert new == "y = obj.attr not in data[key]\n"


def test_is_with_none(tmp_path):
    new = _rewrite(tmp_path, "y = not val is None\n")
    assert new == "y = val is not None\n"


# --- shapes we must NOT touch ----------------------------------------------

def test_not_eq_untouched(tmp_path):
    rel = _write(tmp_path, "y = not a == b\n")
    plan = plan_fix_not_in_is(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_not_lt_untouched(tmp_path):
    rel = _write(tmp_path, "y = not a < b\n")
    plan = plan_fix_not_in_is(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_chained_compare_untouched(tmp_path):
    # `not a in b in c` is a chained compare (len(ops) == 2) — left alone.
    rel = _write(tmp_path, "y = not a in b in c\n")
    plan = plan_fix_not_in_is(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_not_boolop_untouched(tmp_path):
    # `not (a in b or c)` — operand is a BoolOp, not a single Compare.
    rel = _write(tmp_path, "y = not (a in b or c)\n")
    plan = plan_fix_not_in_is(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_proper_not_in_untouched(tmp_path):
    # Already `a not in b` — nothing to do.
    rel = _write(tmp_path, "y = a not in b\n")
    plan = plan_fix_not_in_is(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_multiline_untouched(tmp_path):
    # The UnaryOp spans two lines — the single-line splice is skipped.
    rel = _write(tmp_path, "y = not (\n    a in b\n)\n")
    plan = plan_fix_not_in_is(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


# --- parenthesised operand (we handle it; parens drop out) ------------------

def test_parens_around_compare_handled(tmp_path):
    new = _rewrite(tmp_path, "y = not (a in b)\n")
    assert new == "y = a not in b\n"


# --- ordering: multiple occurrences ----------------------------------------

def test_two_on_one_line_right_to_left(tmp_path):
    new = _rewrite(tmp_path, "y = (not a in b) or (not c is d)\n")
    assert new == "y = (a not in b) or (c is not d)\n"


def test_multiple_across_lines(tmp_path):
    body = "p = not a in b\nq = not c is d\nr = not e in f\n"
    rel = _write(tmp_path, body)
    plan = plan_fix_not_in_is(str(tmp_path), rel)
    assert plan.edits_by_file[rel] == 3
    assert plan.new_contents[rel] == (
        "p = a not in b\nq = c is not d\nr = e not in f\n"
    )


# --- comments / surrounding formatting survive ------------------------------

def test_trailing_comment_survives(tmp_path):
    new = _rewrite(tmp_path, "y = not a in b  # check membership\n")
    assert new == "y = a not in b  # check membership\n"


# --- semantic equivalence (exec before/after) -------------------------------

def test_semantically_equivalent_in(tmp_path):
    before = "def f(a, b):\n    return not a in b\n"
    rel = _write(tmp_path, before)
    after = plan_fix_not_in_is(str(tmp_path), rel).new_contents[rel]
    ns_before: dict = {}
    ns_after: dict = {}
    exec(before, ns_before)
    exec(after, ns_after)
    cases = [(1, [1, 2, 3]), (9, [1, 2, 3]), ("x", "axb"), ("z", "axb")]
    for a, b in cases:
        assert ns_before["f"](a, b) == ns_after["f"](a, b)


def test_semantically_equivalent_is(tmp_path):
    before = "def f(a, b):\n    return not a is b\n"
    rel = _write(tmp_path, before)
    after = plan_fix_not_in_is(str(tmp_path), rel).new_contents[rel]
    ns_before: dict = {}
    ns_after: dict = {}
    exec(before, ns_before)
    exec(after, ns_after)
    obj = object()
    cases = [(None, None), (obj, obj), (obj, object()), (1, 1)]
    for a, b in cases:
        assert ns_before["f"](a, b) == ns_after["f"](a, b)


# --- failure / no-op / registration ----------------------------------------

def test_unparseable_module_blocks(tmp_path):
    rel = _write(tmp_path, "def broken(:\n")
    plan = plan_fix_not_in_is(str(tmp_path), rel)
    assert plan.blockers
    assert not plan.new_contents


def test_missing_module_blocks(tmp_path):
    plan = plan_fix_not_in_is(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_noop_on_clean_module(tmp_path):
    rel = _write(tmp_path, "x = 1\n")
    plan = plan_fix_not_in_is(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers  # empty no-op, not a failure


def test_fixture_subject_is_skipped(tmp_path):
    # A test_ subject is excluded even though it has a matching shape.
    rel = _write(tmp_path, "y = not a in b\n", rel="tests/test_x.py")
    plan = plan_fix_not_in_is(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "fix-not-in-is" in available_objectives()  # discovered via the registry
