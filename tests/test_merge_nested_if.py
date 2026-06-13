"""Tests for the merge-nested-if develop objective.

Collapse ``if A:\\n    if B:`` (no else on either, single-line tests) into
``if (A) and (B):`` with the inner body dedented one level. Conservative: any
else/elif, a multi-statement outer body, or a multi-line test is left untouched,
and the rewritten module must always re-parse and stay semantically equivalent.
"""

from __future__ import annotations

import ast
import textwrap

from app.execution.merge_nested_if import plan_merge_nested_if


def _write(tmp_path, rel, source):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _plan(tmp_path, rel, source):
    _write(tmp_path, rel, source)
    return plan_merge_nested_if(str(tmp_path), rel)


# --- scaffold invariants (kept) ------------------------------------------- #

def test_noop_on_clean_module(tmp_path):
    plan = _plan(tmp_path, "app/m.py", "x = 1\n")
    assert not plan.new_contents and not plan.blockers  # empty no-op, not a failure


def test_missing_module_blocks(tmp_path):
    plan = plan_merge_nested_if(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_fixture_subject_is_skipped(tmp_path):
    # Even with a perfectly mergeable shape, a fixture path is left alone.
    src = "if a:\n    if b:\n        do()\n"
    plan = _plan(tmp_path, "tests/test_x.py", src)
    assert not plan.new_contents and not plan.blockers


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "merge-nested-if" in available_objectives()  # discovered via the registry


# --- the canonical merge -------------------------------------------------- #

def test_canonical_top_level_merge(tmp_path):
    src = "if A:\n    if B:\n        body()\n"
    plan = _plan(tmp_path, "app/m.py", src)
    assert plan.new_contents["app/m.py"] == "if (A) and (B):\n    body()\n"
    assert plan.edits_by_file["app/m.py"] == 1


def test_merge_inside_function_preserves_indentation(tmp_path):
    src = textwrap.dedent("""\
        def f(a, b):
            if a:
                if b:
                    return 1
            return 0
    """)
    plan = _plan(tmp_path, "app/m.py", src)
    expected = textwrap.dedent("""\
        def f(a, b):
            if (a) and (b):
                return 1
            return 0
    """)
    assert plan.new_contents["app/m.py"] == expected


def test_multi_statement_inner_body_all_dedented(tmp_path):
    src = textwrap.dedent("""\
        if a:
            if b:
                x = 1
                y = 2
                z = x + y
    """)
    plan = _plan(tmp_path, "app/m.py", src)
    expected = textwrap.dedent("""\
        if (a) and (b):
            x = 1
            y = 2
            z = x + y
    """)
    assert plan.new_contents["app/m.py"] == expected


def test_complex_conditions_each_wrapped_in_parens(tmp_path):
    src = "if x or y:\n    if z and w:\n        run()\n"
    plan = _plan(tmp_path, "app/m.py", src)
    assert plan.new_contents["app/m.py"] == "if (x or y) and (z and w):\n    run()\n"


# --- shapes that must be left untouched ----------------------------------- #

def test_outer_body_with_two_statements_untouched(tmp_path):
    src = textwrap.dedent("""\
        if a:
            if b:
                body()
            other()
    """)
    plan = _plan(tmp_path, "app/m.py", src)
    assert not plan.new_contents and not plan.blockers


def test_outer_else_untouched(tmp_path):
    src = textwrap.dedent("""\
        if a:
            if b:
                body()
        else:
            alt()
    """)
    plan = _plan(tmp_path, "app/m.py", src)
    assert not plan.new_contents and not plan.blockers


def test_inner_else_untouched(tmp_path):
    src = textwrap.dedent("""\
        if a:
            if b:
                body()
            else:
                alt()
    """)
    plan = _plan(tmp_path, "app/m.py", src)
    assert not plan.new_contents and not plan.blockers


def test_inner_elif_chain_untouched(tmp_path):
    src = textwrap.dedent("""\
        if a:
            if b:
                body()
            elif c:
                other()
    """)
    plan = _plan(tmp_path, "app/m.py", src)
    assert not plan.new_contents and not plan.blockers


def test_outer_elif_chain_untouched(tmp_path):
    src = textwrap.dedent("""\
        if a:
            if b:
                body()
        elif c:
            other()
    """)
    plan = _plan(tmp_path, "app/m.py", src)
    assert not plan.new_contents and not plan.blockers


def test_multiline_outer_condition_untouched(tmp_path):
    src = textwrap.dedent("""\
        if (a and
                d):
            if b:
                body()
    """)
    plan = _plan(tmp_path, "app/m.py", src)
    assert not plan.new_contents and not plan.blockers


def test_multiline_inner_condition_untouched(tmp_path):
    src = textwrap.dedent("""\
        if a:
            if (b and
                    e):
                body()
    """)
    plan = _plan(tmp_path, "app/m.py", src)
    assert not plan.new_contents and not plan.blockers


def test_inner_not_an_if_untouched(tmp_path):
    src = "if a:\n    body()\n"
    plan = _plan(tmp_path, "app/m.py", src)
    assert not plan.new_contents and not plan.blockers


# --- multiple occurrences ------------------------------------------------- #

def test_multiple_independent_occurrences(tmp_path):
    src = textwrap.dedent("""\
        if a:
            if b:
                first()
        z = 0
        if c:
            if d:
                second()
    """)
    plan = _plan(tmp_path, "app/m.py", src)
    expected = textwrap.dedent("""\
        if (a) and (b):
            first()
        z = 0
        if (c) and (d):
            second()
    """)
    assert plan.new_contents["app/m.py"] == expected
    assert plan.edits_by_file["app/m.py"] == 2


def test_triple_nested_collapses_outer_pair_and_reparses(tmp_path):
    # if A: if B: if C: — the outermost pair merges this pass; the still-nested
    # remainder is left for a later pass. The result must re-parse.
    src = textwrap.dedent("""\
        if A:
            if B:
                if C:
                    body()
    """)
    plan = _plan(tmp_path, "app/m.py", src)
    out = plan.new_contents["app/m.py"]
    ast.parse(out)  # must re-parse
    expected = textwrap.dedent("""\
        if (A) and (B):
            if C:
                body()
    """)
    assert out == expected
    # And a second pass collapses what remains.
    _write(tmp_path, "app/m.py", out)
    plan2 = plan_merge_nested_if(str(tmp_path), "app/m.py")
    out2 = plan2.new_contents["app/m.py"]
    ast.parse(out2)
    assert out2 == "if ((A) and (B)) and (C):\n    body()\n"


# --- re-parse / semantics / blocker / no-op ------------------------------- #

def test_result_reparses(tmp_path):
    src = "if a:\n    if b:\n        body()\n"
    plan = _plan(tmp_path, "app/m.py", src)
    ast.parse(plan.new_contents["app/m.py"])  # raises if it doesn't


def test_semantically_equivalent_across_truth_table(tmp_path):
    before = textwrap.dedent("""\
        def f(a, b):
            out = []
            if a:
                if b:
                    out.append('hit')
            return out
    """)
    plan = _plan(tmp_path, "app/m.py", before)
    after = plan.new_contents["app/m.py"]
    assert after != before  # it did rewrite

    for a in (True, False, 1, 0, "", "x"):
        for b in (True, False, 1, 0, "", "x"):
            ns_before: dict = {}
            ns_after: dict = {}
            exec(before, ns_before)
            exec(after, ns_after)
            assert ns_before["f"](a, b) == ns_after["f"](a, b), (a, b)


def test_unparseable_module_blocks(tmp_path):
    plan = _plan(tmp_path, "app/m.py", "def broken(:\n    pass\n")
    assert plan.blockers
    assert not plan.new_contents


def test_no_match_is_empty_noop_plan(tmp_path):
    # A lone if with a plain body never matches — empty plan, not a failure.
    plan = _plan(tmp_path, "app/m.py", "if a:\n    do()\n    more()\n")
    assert not plan.new_contents and not plan.blockers
    assert not plan.ok  # an empty plan is a clean no-op, ok is False
