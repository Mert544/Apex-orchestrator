"""Tests for the fix-assert-tuple transform.

The classic always-true assert typo: ``assert (cond, "msg")`` asserts a
non-empty 2-tuple — ALWAYS truthy — so it silently never fires. The author meant
``assert cond, "msg"``. This transform is the one behaviour-CHANGING bug fix in
the family: it turns "always passes" into "actually checks". The tests below pin
the conservative shape-match, the splice fidelity, the skip set, and prove (by
exec) that the rewritten assert really raises where the buggy original did not.
"""

from __future__ import annotations

import ast

import pytest

from app.execution.fix_assert_tuple import plan_fix_assert_tuple


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
    plan = plan_fix_assert_tuple(str(tmp_path), rel)
    assert not plan.blockers, plan.blockers
    assert plan.new_contents, "expected a rewrite"
    new = plan.new_contents[rel]
    ast.parse(new)  # must re-parse
    return new


def _noop(tmp_path, body: str, rel: str = "app/m.py") -> None:
    """Assert the plan leaves ``body`` untouched (no rewrite, no blocker)."""
    _write(tmp_path, body, rel)
    plan = plan_fix_assert_tuple(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


# --- core rewrite ----------------------------------------------------------

def test_basic_typo(tmp_path):
    new = _rewrite(tmp_path, 'assert (x, "m")\n')
    assert new == 'assert x, "m"\n'


def test_comparison_condition(tmp_path):
    new = _rewrite(tmp_path, 'assert (x > 0, "x must be positive")\n')
    assert new == 'assert x > 0, "x must be positive"\n'


def test_call_condition_preserved(tmp_path):
    new = _rewrite(tmp_path, 'assert (is_ok(a, b), "not ok")\n')
    assert new == 'assert is_ok(a, b), "not ok"\n'


def test_boolop_condition_preserved(tmp_path):
    new = _rewrite(tmp_path, 'assert (a and b, "both required")\n')
    assert new == 'assert a and b, "both required"\n'


def test_indented_assert(tmp_path):
    body = "def f(x):\n    assert (x, \"need x\")\n    return x\n"
    new = _rewrite(tmp_path, body)
    assert new == "def f(x):\n    assert x, \"need x\"\n    return x\n"


def test_single_quote_message_preserved(tmp_path):
    new = _rewrite(tmp_path, "assert (x, 'm')\n")
    assert new == "assert x, 'm'\n"


# --- shapes we must NOT touch ----------------------------------------------

def test_three_tuple_skipped(tmp_path):
    # 3 elements — not the classic typo shape.
    _noop(tmp_path, 'assert (x, "m", y)\n')


def test_one_tuple_skipped(tmp_path):
    # A 1-tuple `(x,)` — only one element, never the typo.
    _noop(tmp_path, 'assert (x,)\n')


def test_empty_tuple_skipped(tmp_path):
    # `assert ()` — the detector wouldn't even flag it (empty tuple is falsy),
    # and there's no message to recover.
    _noop(tmp_path, "assert ()\n")


def test_non_string_second_element_skipped(tmp_path):
    # 2nd element is a Name, not a string constant — could be a deliberate tuple.
    _noop(tmp_path, "assert (x, y)\n")


def test_numeric_second_element_skipped(tmp_path):
    _noop(tmp_path, "assert (x, 42)\n")


def test_fstring_message_skipped(tmp_path):
    # An f-string is a JoinedStr, not a plain str Constant — splicing is unsafe.
    _noop(tmp_path, 'assert (x, f"need {x}")\n')


def test_existing_message_skipped(tmp_path):
    # `assert (a, b), c` already has a real message — a genuine 3-way assert.
    _noop(tmp_path, 'assert (a, b), "real message"\n')


def test_tuple_condition_skipped(tmp_path):
    # First element is itself a tuple — splicing it beside `assert` re-creates the
    # bug, so we refuse.
    _noop(tmp_path, 'assert ((a, b), "m")\n')


def test_proper_assert_untouched(tmp_path):
    # Already `assert cond, "msg"` — nothing to do.
    _noop(tmp_path, 'assert x, "m"\n')


def test_plain_assert_untouched(tmp_path):
    _noop(tmp_path, "assert x\n")


def test_multiline_assert_skipped(tmp_path):
    # The Assert spans two lines — the single-line splice is skipped.
    _noop(tmp_path, 'assert (\n    x, "m")\n')


# --- multiple occurrences --------------------------------------------------

def test_multiple_across_lines(tmp_path):
    body = 'assert (a, "ma")\nassert (b, "mb")\nassert (c, "mc")\n'
    rel = _write(tmp_path, body)
    plan = plan_fix_assert_tuple(str(tmp_path), rel)
    assert plan.edits_by_file[rel] == 3
    assert plan.new_contents[rel] == (
        'assert a, "ma"\nassert b, "mb"\nassert c, "mc"\n'
    )


# --- the BUG is actually fixed (exec before vs after) ----------------------

def test_rewrite_fixes_the_bug(tmp_path):
    # The whole point: original always passes (asserts a truthy tuple); the
    # rewritten one actually checks the condition and raises on False.
    before = 'def f():\n    assert (False, "must hold")\n'
    rel = _write(tmp_path, before)
    after = plan_fix_assert_tuple(str(tmp_path), rel).new_contents[rel]

    ns_before: dict = {}
    ns_after: dict = {}
    exec(compile(before, "<before>", "exec"), ns_before)
    exec(compile(after, "<after>", "exec"), ns_after)

    # BUG present in the original: assert (False, "...") silently passes.
    ns_before["f"]()  # does NOT raise — the always-true tuple assert

    # FIXED: the rewritten assert really checks the condition.
    with pytest.raises(AssertionError) as exc:
        ns_after["f"]()
    assert "must hold" in str(exc.value)


def test_rewrite_passes_when_condition_true(tmp_path):
    # When the condition is genuinely true, the fixed assert passes (no raise).
    before = 'def f():\n    assert (True, "must hold")\n'
    rel = _write(tmp_path, before)
    after = plan_fix_assert_tuple(str(tmp_path), rel).new_contents[rel]
    ns: dict = {}
    exec(compile(after, "<after>", "exec"), ns)
    ns["f"]()  # does not raise


# --- failure / no-op / fixture / determinism / registration ----------------

def test_reparse_guard_blocks_bad_rewrite(tmp_path, monkeypatch):
    # Force the rewrite to produce un-parseable source and confirm the re-parse
    # guard blocks the plan instead of emitting broken contents.
    import app.execution.fix_assert_tuple as mod

    def _bad_apply(source, rewrites):
        return "assert (def\n"  # not valid Python

    monkeypatch.setattr(mod, "_apply", _bad_apply)
    rel = _write(tmp_path, 'assert (x, "m")\n')
    plan = plan_fix_assert_tuple(str(tmp_path), rel)
    assert plan.blockers
    assert not plan.new_contents


def test_unparseable_module_blocks(tmp_path):
    rel = _write(tmp_path, "def broken(:\n")
    plan = plan_fix_assert_tuple(str(tmp_path), rel)
    assert plan.blockers
    assert not plan.new_contents


def test_missing_module_blocks(tmp_path):
    plan = plan_fix_assert_tuple(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_noop_on_clean_module(tmp_path):
    _noop(tmp_path, "x = 1\n")


def test_fixture_subject_is_skipped(tmp_path):
    # A test_ subject is excluded even though it has the matching shape.
    _noop(tmp_path, 'assert (x, "m")\n', rel="tests/test_x.py")


def test_deterministic(tmp_path):
    body = 'assert (a, "ma")\nassert (b, "mb")\n'
    rel = _write(tmp_path, body)
    first = plan_fix_assert_tuple(str(tmp_path), rel).new_contents[rel]
    second = plan_fix_assert_tuple(str(tmp_path), rel).new_contents[rel]
    assert first == second


def test_self_registers():
    from app.engine.objective_compiler import available_objectives

    assert "fix-assert-tuple" in available_objectives()  # discovered via registry


def test_facet_routes_to_objective():
    # The assert-on-tuple detector phrase routes to this objective end-to-end.
    from app.engine.facet_develop import facet_to_objective

    phrase = "assert on a tuple is always true — remove the parentheses"
    assert facet_to_objective(phrase) == "fix-assert-tuple"
