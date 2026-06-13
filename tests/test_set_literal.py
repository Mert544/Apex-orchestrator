from __future__ import annotations

import ast

from app.execution.set_literal import plan_set_literal


def _write(tmp_path, source: str) -> str:
    """Write ``source`` to app/m.py and return the module-relative path."""
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "m.py").write_text(source, encoding="utf-8")
    return "app/m.py"


def _project(tmp_path):
    _write(tmp_path, "x = 1\n")
    return tmp_path


def _eval_expr(src: str):
    """Evaluate a single-expression source line and return its value."""
    return eval(src, {})  # noqa: S307 — test-only, fixed inputs


# --- scaffold baseline -------------------------------------------------------

def test_noop_on_clean_module(tmp_path):
    _project(tmp_path)
    plan = plan_set_literal(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers  # empty no-op, not a failure


def test_missing_module_blocks(tmp_path):
    plan = plan_set_literal(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_fixture_subject_is_skipped(tmp_path):
    plan = plan_set_literal(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "set-literal" in available_objectives()  # discovered via the registry


# --- core rewrites -----------------------------------------------------------

def test_rewrites_list_literal(tmp_path):
    rel = _write(tmp_path, "s = set([1, 2, 3])\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert plan.new_contents[rel] == "s = {1, 2, 3}\n"
    assert plan.edits_by_file[rel] == 1


def test_rewrites_tuple_literal(tmp_path):
    rel = _write(tmp_path, "s = set((1, 2))\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert plan.new_contents[rel] == "s = {1, 2}\n"


def test_does_not_dedup(tmp_path):
    rel = _write(tmp_path, "s = set([1, 1])\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert plan.new_contents[rel] == "s = {1, 1}\n"


# --- never touched -----------------------------------------------------------

def test_empty_set_call_untouched(tmp_path):
    rel = _write(tmp_path, "s = set()\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_empty_list_arg_untouched(tmp_path):
    rel = _write(tmp_path, "s = set([])\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_name_arg_untouched(tmp_path):
    rel = _write(tmp_path, "x = [1, 2]\ns = set(x)\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_generator_arg_untouched(tmp_path):
    rel = _write(tmp_path, "s = set(i for i in range(3))\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_comprehension_arg_untouched(tmp_path):
    rel = _write(tmp_path, "s = set([i for i in range(3)])\n")
    plan = plan_set_literal(str(tmp_path), rel)
    # the arg is a ListComp, not a List literal — leave it (set comprehension is a
    # different transform).
    assert not plan.new_contents and not plan.blockers


def test_call_arg_untouched(tmp_path):
    rel = _write(tmp_path, "s = set(range(3))\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_starred_element_untouched(tmp_path):
    rel = _write(tmp_path, "a = [1, 2]\ns = set([*a])\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_starred_among_elements_untouched(tmp_path):
    rel = _write(tmp_path, "a = [1]\ns = set([0, *a, 2])\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_frozenset_untouched(tmp_path):
    rel = _write(tmp_path, "s = frozenset([1, 2])\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_attribute_set_untouched(tmp_path):
    rel = _write(tmp_path, "import builtins\ns = builtins.set([1, 2])\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_keyword_arg_untouched(tmp_path):
    # A bogus shape that still parses: set called with a keyword — not a builtin
    # set() call we rewrite. Stays untouched (no keywords allowed).
    rel = _write(tmp_path, "s = set([1, 2], foo=3)\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


def test_multiline_call_untouched(tmp_path):
    rel = _write(tmp_path, "s = set([\n    1,\n    2,\n])\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert not plan.new_contents and not plan.blockers


# --- element fidelity --------------------------------------------------------

def test_nested_brackets_preserved(tmp_path):
    rel = _write(tmp_path, "s = set([a[0], b])\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert plan.new_contents[rel] == "s = {a[0], b}\n"


def test_string_elements_preserved_verbatim(tmp_path):
    rel = _write(tmp_path, 's = set(["a, b", "c"])\n')
    plan = plan_set_literal(str(tmp_path), rel)
    assert plan.new_contents[rel] == 's = {"a, b", "c"}\n'
    # the comma inside the string must not have split the element
    assert _eval_expr(plan.new_contents[rel].split("=", 1)[1].strip()) == {"a, b", "c"}


def test_nested_set_call_element_preserved(tmp_path):
    rel = _write(tmp_path, "s = set([frozenset([1]), 2])\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert plan.new_contents[rel] == "s = {frozenset([1]), 2}\n"


# --- ordering ----------------------------------------------------------------

def test_multiple_occurrences_one_line(tmp_path):
    rel = _write(tmp_path, "pair = (set([1, 2]), set([3, 4]))\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert plan.new_contents[rel] == "pair = ({1, 2}, {3, 4})\n"
    assert plan.edits_by_file[rel] == 2


def test_nested_set_call_outer_wins(tmp_path):
    # An outer set whose element is itself a set([...]) call. The two spans
    # OVERLAP, so only the outer rewrite is applied; the inner call rides along
    # verbatim inside the new literal (still a valid, equivalent expression).
    rel = _write(tmp_path, "s = set([set([1]), 2])\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert plan.new_contents[rel] == "s = {set([1]), 2}\n"
    assert plan.edits_by_file[rel] == 1
    ast.parse(plan.new_contents[rel])  # the overlapping case must still re-parse


# --- robustness --------------------------------------------------------------

def test_unparseable_module_blocks(tmp_path):
    rel = _write(tmp_path, "def broken(:\n    pass\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert plan.blockers and not plan.new_contents


def test_result_reparses(tmp_path):
    rel = _write(tmp_path, "s = set([1, 2, 3])\nt = set((4, 5))\n")
    plan = plan_set_literal(str(tmp_path), rel)
    ast.parse(plan.new_contents[rel])  # must re-parse cleanly


def test_semantically_equivalent(tmp_path):
    cases = [
        "set([1, 2, 3])",
        "set((1, 2))",
        "set([1, 1, 2])",
        'set(["a, b", "c"])',
        "set([(1, 2), (3, 4)])",
    ]
    for expr in cases:
        rel = _write(tmp_path, f"s = {expr}\n")
        plan = plan_set_literal(str(tmp_path), rel)
        new_expr = plan.new_contents[rel].split("=", 1)[1].strip()
        before = _eval_expr(expr)
        after = _eval_expr(new_expr)
        assert before == after, f"{expr!r} -> {new_expr!r}"


def test_comments_elsewhere_survive(tmp_path):
    rel = _write(tmp_path, "# keep me\ns = set([1, 2])  # trailing\n")
    plan = plan_set_literal(str(tmp_path), rel)
    assert plan.new_contents[rel] == "# keep me\ns = {1, 2}  # trailing\n"
