"""Tests for the use-enumerate develop objective.

This transform rewrites the loop BODY, so it is the riskiest of the wave; the
tests below cover the canonical rewrite and its exec-equivalence, every guarded
SKIP (i used elsewhere, store ``seq[i] =``, the start-stop ``range`` forms,
for/else, a nested function that captures ``i``, seq rebound), the attribute-seq
shape, a multi-use rewrite, the no-op / blocker / fixture paths, and the
self-registration. Decisions enforced here:

  - the index is bound to ``_`` (``for _, <elem> in enumerate(seq):``) because
    the match proves ``i`` is unused after every ``seq[i]`` becomes ``<elem>``;
  - the element name is a fresh ``<seq-last-name>_item`` that avoids collisions.
"""

from __future__ import annotations

import ast
import textwrap

from app.execution.use_enumerate import plan_use_enumerate


def _write(tmp_path, source: str, rel: str = "app/m.py"):
    """Write ``source`` (dedented) to ``rel`` under a fresh ``app`` package."""
    (tmp_path / "app").mkdir(exist_ok=True)
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def _plan(tmp_path, source: str, rel: str = "app/m.py"):
    _write(tmp_path, source, rel)
    return plan_use_enumerate(str(tmp_path), rel)


def _rewritten(plan, rel: str = "app/m.py") -> str:
    return plan.new_contents[rel]


# --------------------------------------------------------------------------- #
# the canonical rewrite + exec-equivalence
# --------------------------------------------------------------------------- #

def test_canonical_for_index_rewrites_to_enumerate(tmp_path):
    src = """\
        def total(xs):
            total = 0
            for i in range(len(xs)):
                total += xs[i]
            return total
    """
    plan = _plan(tmp_path, src)
    out = _rewritten(plan)
    assert "for _, xs_item in enumerate(xs):" in out
    assert "total += xs_item" in out
    assert "xs[i]" not in out
    assert "range(len(xs))" not in out
    ast.parse(out)  # re-parses
    assert plan.edits_by_file["app/m.py"] == 1


def test_canonical_is_exec_equivalent(tmp_path):
    src = """\
        def total(xs):
            total = 0
            for i in range(len(xs)):
                total += xs[i]
            return total
    """
    before = textwrap.dedent(src)
    plan = _plan(tmp_path, src)
    after = _rewritten(plan)

    sample = [3, 1, 4, 1, 5, 9, 2, 6]
    ns_before: dict = {}
    ns_after: dict = {}
    exec(compile(before, "<before>", "exec"), ns_before)
    exec(compile(after, "<after>", "exec"), ns_after)
    assert ns_before["total"](list(sample)) == ns_after["total"](list(sample))
    assert ns_after["total"](list(sample)) == sum(sample)


def test_multiple_seq_index_uses_all_replaced(tmp_path):
    src = """\
        def pairs(xs):
            out = []
            for i in range(len(xs)):
                out.append((xs[i], xs[i] * 2))
            return out
    """
    before = textwrap.dedent(src)
    plan = _plan(tmp_path, src)
    after = _rewritten(plan)
    assert after.count("xs[i]") == 0
    assert "out.append((xs_item, xs_item * 2))" in after  # both loads replaced
    assert "for _, xs_item in enumerate(xs):" in after

    ns_b: dict = {}
    ns_a: dict = {}
    exec(compile(before, "<b>", "exec"), ns_b)
    exec(compile(after, "<a>", "exec"), ns_a)
    sample = [1, 2, 3]
    assert ns_b["pairs"](sample) == ns_a["pairs"](sample)


# --------------------------------------------------------------------------- #
# the attribute-chain seq
# --------------------------------------------------------------------------- #

def test_attribute_seq_handled(tmp_path):
    src = """\
        class Bag:
            def __init__(self, items):
                self.items = items

            def total(self):
                s = 0
                for i in range(len(self.items)):
                    s += self.items[i]
                return s
    """
    before = textwrap.dedent(src)
    plan = _plan(tmp_path, src)
    after = _rewritten(plan)
    assert "for _, items_item in enumerate(self.items):" in after
    assert "s += items_item" in after
    assert "self.items[i]" not in after

    ns_b: dict = {}
    ns_a: dict = {}
    exec(compile(before, "<b>", "exec"), ns_b)
    exec(compile(after, "<a>", "exec"), ns_a)
    assert ns_b["Bag"]([4, 5, 6]).total() == ns_a["Bag"]([4, 5, 6]).total() == 15


# --------------------------------------------------------------------------- #
# the guarded SKIPs — these stay UNTOUCHED
# --------------------------------------------------------------------------- #

def test_i_used_elsewhere_untouched(tmp_path):
    # ``i`` is printed too, so dropping its name would lose a use — skip.
    src = """\
        def show(xs):
            for i in range(len(xs)):
                print(i, xs[i])
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_i_used_in_arithmetic_untouched(tmp_path):
    src = """\
        def neighbours(xs):
            out = []
            for i in range(len(xs)):
                out.append(xs[i] + i)
            return out
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_store_subscript_untouched(tmp_path):
    # ``seq[i] = ...`` is a Store, not a Load — skip (we'd lose the index).
    src = """\
        def zero(xs):
            for i in range(len(xs)):
                xs[i] = 0
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_store_then_load_subscript_untouched(tmp_path):
    # A load is present, but there is also a store of seq[i] (i used in store) —
    # the store ``i`` is not an accounted-for load, so the whole loop is skipped.
    src = """\
        def bump(xs):
            for i in range(len(xs)):
                xs[i] = xs[i] + 1
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_range_zero_len_untouched(tmp_path):
    # The two-arg start-stop form is NOT the bare range(len(seq)) shape — skip.
    src = """\
        def total(xs):
            s = 0
            for i in range(0, len(xs)):
                s += xs[i]
            return s
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_range_len_a_len_b_untouched(tmp_path):
    src = """\
        def f(a, b):
            s = 0
            for i in range(len(a), len(b)):
                s += a[i]
            return s
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_for_else_untouched(tmp_path):
    src = """\
        def find(xs):
            for i in range(len(xs)):
                if xs[i] == 0:
                    return i
            else:
                return -1
    """
    # Note: this also uses ``i`` in ``return i`` so it would be skipped anyway,
    # but the for/else guard is exercised separately below.
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_for_else_with_clean_body_untouched(tmp_path):
    # ``i`` is used only as xs[i]; the ONLY reason to skip is the for/else.
    src = """\
        def total(xs):
            s = 0
            for i in range(len(xs)):
                s += xs[i]
            else:
                s = -1
            return s
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_nested_function_using_i_untouched(tmp_path):
    # A nested def captures ``i``; dropping its name would break the closure.
    src = """\
        def make(xs):
            out = []
            for i in range(len(xs)):
                def grab():
                    return i
                out.append((xs[i], grab))
            return out
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_lambda_using_i_untouched(tmp_path):
    src = """\
        def make(xs):
            out = []
            for i in range(len(xs)):
                out.append(lambda: i)
            return out
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_seq_rebound_in_body_untouched(tmp_path):
    # ``xs`` is reassigned mid-loop, so seq[i] no longer indexes the iterated
    # sequence — skip.
    src = """\
        def f(xs):
            s = 0
            for i in range(len(xs)):
                s += xs[i]
                xs = []
            return s
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_attribute_seq_head_rebound_untouched(tmp_path):
    src = """\
        class Bag:
            def total(self):
                s = 0
                for i in range(len(self.items)):
                    s += self.items[i]
                    self = None
                return s
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_index_passed_to_call_untouched(tmp_path):
    src = """\
        def f(xs):
            out = []
            for i in range(len(xs)):
                out.append(helper(i, xs[i]))
            return out
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_target_not_i_untouched(tmp_path):
    # Only the literal target name ``i`` is handled (a deliberate, narrow match).
    src = """\
        def total(xs):
            s = 0
            for j in range(len(xs)):
                s += xs[j]
            return s
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


def test_other_sequence_indexed_untouched(tmp_path):
    # range(len(xs)) but the body indexes ys[i], not xs[i] — i is not used as
    # the iterated seq's index, so skip (ys may be a different length).
    src = """\
        def f(xs, ys):
            out = []
            for i in range(len(xs)):
                out.append(ys[i])
            return out
    """
    plan = _plan(tmp_path, src)
    assert not plan.new_contents and not plan.blockers


# --------------------------------------------------------------------------- #
# fresh-name uniqueness
# --------------------------------------------------------------------------- #

def test_elem_name_avoids_collision(tmp_path):
    # ``xs_item`` already exists in the function, so the fresh name must differ.
    src = """\
        def total(xs):
            xs_item = 0
            for i in range(len(xs)):
                xs_item += xs[i]
            return xs_item
    """
    plan = _plan(tmp_path, src)
    after = _rewritten(plan)
    assert "for _, xs_item_2 in enumerate(xs):" in after
    assert "xs_item += xs_item_2" in after
    ast.parse(after)


# --------------------------------------------------------------------------- #
# infrastructure: no-op, blocker, fixture, registration
# --------------------------------------------------------------------------- #

def test_noop_on_clean_module(tmp_path):
    _write(tmp_path, "x = 1\n")
    plan = plan_use_enumerate(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_unparseable_module_blocks(tmp_path):
    _write(tmp_path, "def f(:\n    pass\n")
    plan = plan_use_enumerate(str(tmp_path), "app/m.py")
    assert plan.blockers


def test_missing_module_blocks(tmp_path):
    plan = plan_use_enumerate(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_fixture_subject_is_skipped(tmp_path):
    _write(tmp_path, """\
        def total(xs):
            s = 0
            for i in range(len(xs)):
                s += xs[i]
            return s
    """, rel="tests/test_x.py")
    plan = plan_use_enumerate(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_determinism(tmp_path):
    src = """\
        def total(xs):
            s = 0
            for i in range(len(xs)):
                s += xs[i]
            return s
    """
    _write(tmp_path, src)
    first = plan_use_enumerate(str(tmp_path), "app/m.py").new_contents
    second = plan_use_enumerate(str(tmp_path), "app/m.py").new_contents
    assert first == second


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "use-enumerate" in available_objectives()
