from __future__ import annotations

import ast
import textwrap

from app.execution.dict_comprehension import plan_dict_comprehension


def _write(tmp_path, source: str, rel: str = "app/m.py"):
    """Write ``source`` (dedented) at ``rel`` under ``tmp_path``; return the
    project root as a string."""
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return str(tmp_path)


def _exec_dict(source: str, name: str, ns_setup: str = "") -> dict:
    """Execute ``source`` in a fresh namespace (optionally after ``ns_setup``)
    and return the value bound to ``name`` — used to prove semantic equivalence
    of the before/after sources."""
    ns: dict = {}
    if ns_setup:
        exec(textwrap.dedent(ns_setup), ns)
    exec(textwrap.dedent(source), ns)
    return ns[name]


# --- the canonical rewrite --------------------------------------------------

def test_canonical_loop_becomes_dict_comprehension(tmp_path):
    root = _write(tmp_path, """
        def build(items):
            out = {}
            for x in items:
                out[x] = x * 2
            return out
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert plan.new_contents
    new = plan.new_contents["app/m.py"]
    assert "out = {x: x * 2 for x in items}" in new
    assert "out = {}" not in new
    assert ".append" not in new
    assert plan.edits_by_file["app/m.py"] == 1
    ast.parse(new)  # re-parses


def test_tuple_target(tmp_path):
    root = _write(tmp_path, """
        def invert(items):
            d = {}
            for k, v in items.items():
                d[v] = k
            return d
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert plan.new_contents
    new = plan.new_contents["app/m.py"]
    assert "d = {v: k for k, v in items.items()}" in new
    ast.parse(new)


def test_semantically_equivalent(tmp_path):
    before = """
        def build(items):
            out = {}
            for x in items:
                out[x] = x * 2
            return out
        result = build(range(5))
    """
    root = _write(tmp_path, before)
    plan = plan_dict_comprehension(root, "app/m.py")
    after = plan.new_contents["app/m.py"]
    assert after != textwrap.dedent(before)
    assert _exec_dict(before, "result") == _exec_dict(after, "result")
    assert _exec_dict(after, "result") == {0: 0, 1: 2, 2: 4, 3: 6, 4: 8}


def test_multiple_occurrences(tmp_path):
    root = _write(tmp_path, """
        def a(items):
            out = {}
            for x in items:
                out[x] = x
            return out

        def b(items):
            res = {}
            for k in items:
                res[k] = k + 1
            return res
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert plan.edits_by_file["app/m.py"] == 2
    new = plan.new_contents["app/m.py"]
    assert "out = {x: x for x in items}" in new
    assert "res = {k: k + 1 for k in items}" in new
    assert "{}" not in new
    ast.parse(new)


def test_nested_block_indentation_preserved(tmp_path):
    root = _write(tmp_path, """
        def build(rows):
            if rows:
                out = {}
                for x in rows:
                    out[x] = x
                return out
            return {}
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    new = plan.new_contents["app/m.py"]
    assert "        out = {x: x for x in rows}" in new  # 8-space indent kept
    ast.parse(new)


# --- conservative skips (untouched) ----------------------------------------

def test_rhs_not_empty_dict_untouched(tmp_path):
    root = _write(tmp_path, """
        def build(items):
            d = {1: 2}
            for x in items:
                d[x] = x
            return d
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_set_literal_rhs_untouched(tmp_path):
    # ``d = {1}`` is an ast.Set, not an empty Dict — must not match.
    root = _write(tmp_path, """
        def build(items):
            d = {1}
            for x in items:
                d[x] = x
            return d
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_two_statement_body_untouched(tmp_path):
    root = _write(tmp_path, """
        def build(items):
            out = {}
            for x in items:
                out[x] = x
                print(x)
            return out
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_subscript_to_different_name_untouched(tmp_path):
    root = _write(tmp_path, """
        def build(items, other):
            out = {}
            for x in items:
                other[x] = x
            return out
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_for_else_untouched(tmp_path):
    root = _write(tmp_path, """
        def build(items):
            out = {}
            for x in items:
                out[x] = x
            else:
                pass
            return out
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_non_subscript_body_untouched(tmp_path):
    root = _write(tmp_path, """
        def build(items):
            out = {}
            for x in items:
                out.update({x: x})
            return out
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_body_reuses_name_untouched(tmp_path):
    # ``out[x] = out`` references ``out`` beyond the receiver — not trivial.
    root = _write(tmp_path, """
        def build(items):
            out = {}
            for x in items:
                out[x] = out
            return out
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_attribute_target_loop_var_untouched(tmp_path):
    # ``for self.x in ...`` is not a plain Name/Tuple target — skip.
    root = _write(tmp_path, """
        class C:
            def build(self, items):
                out = {}
                for self.x in items:
                    out[self.x] = 1
                return out
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_chained_assignment_body_untouched(tmp_path):
    # ``out[x] = y = value`` is a multi-target Assign — skip.
    root = _write(tmp_path, """
        def build(items):
            out = {}
            for x in items:
                out[x] = y = x
            return out
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_multiline_value_skipped(tmp_path):
    # The value EXPRESSION node spans two lines — single-line guard skips it.
    root = _write(tmp_path, """
        def build(items):
            out = {}
            for x in items:
                out[x] = (x +
                          x)
            return out
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_multiline_key_skipped(tmp_path):
    # The key expression node spans two lines — skip the occurrence.
    root = _write(tmp_path, """
        def build(items):
            out = {}
            for x in items:
                out[(x,
                     x)] = x
            return out
    """)
    plan = plan_dict_comprehension(root, "app/m.py")
    assert not plan.new_contents and not plan.blockers


# --- module-level edge / error paths ---------------------------------------

def test_unparseable_blocks(tmp_path):
    root = _write(tmp_path, "def broken(:\n    pass\n")
    plan = plan_dict_comprehension(root, "app/m.py")
    assert plan.blockers and not plan.new_contents


def test_missing_module_blocks(tmp_path):
    plan = plan_dict_comprehension(str(tmp_path), "app/nope.py")
    assert plan.blockers and not plan.new_contents


def test_empty_plan_on_clean_module(tmp_path):
    root = _write(tmp_path, "x = 1\n")
    plan = plan_dict_comprehension(root, "app/m.py")
    assert not plan.new_contents and not plan.blockers  # empty no-op, not a failure


def test_fixture_subject_is_skipped(tmp_path):
    # Even a perfect match under tests/ is excluded as a subject.
    root = _write(tmp_path, """
        def build(items):
            out = {}
            for x in items:
                out[x] = x
            return out
    """, rel="tests/test_x.py")
    plan = plan_dict_comprehension(root, "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_deterministic(tmp_path):
    root = _write(tmp_path, """
        def build(items):
            out = {}
            for x in items:
                out[x] = x
            return out
    """)
    first = plan_dict_comprehension(root, "app/m.py").new_contents
    second = plan_dict_comprehension(root, "app/m.py").new_contents
    assert first == second


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "dict-comprehension" in available_objectives()  # discovered via the registry
