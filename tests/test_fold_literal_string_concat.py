from __future__ import annotations

import ast

from app.execution.fold_literal_string_concat import (
    plan_fold_literal_string_concat,
)


def _project(tmp_path, body="x = 1\n"):
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "m.py").write_text(body, encoding="utf-8")
    return tmp_path


def _rewrite(tmp_path, body):
    """Run the plan over a one-module project; return new source (or None for an
    empty no-op) and the plan itself."""
    _project(tmp_path, body)
    plan = plan_fold_literal_string_concat(str(tmp_path), "app/m.py")
    new = plan.new_contents.get("app/m.py")
    return new, plan


# --- scaffold invariants -------------------------------------------------

def test_noop_on_clean_module(tmp_path):
    _project(tmp_path)
    plan = plan_fold_literal_string_concat(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers  # empty no-op


def test_missing_module_blocks(tmp_path):
    plan = plan_fold_literal_string_concat(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_fixture_subject_is_skipped(tmp_path):
    # A test/example/fixture module is never a subject (its concats may be
    # deliberate). The path filter short-circuits before reading.
    plan = plan_fold_literal_string_concat(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "fold-literal-string-concat" in available_objectives()  # via registry


def test_unparseable_module_blocks(tmp_path):
    new, plan = _rewrite(tmp_path, "def broken(:\n    pass\n")
    assert new is None and plan.blockers


# --- the folds ------------------------------------------------------------

def test_two_literal_fold(tmp_path):
    new, _ = _rewrite(tmp_path, 'r = "foo" + "bar"\n')
    assert new == "r = 'foobar'\n"


def test_three_literal_chain_fold(tmp_path):
    new, plan = _rewrite(tmp_path, 'r = "a" + "b" + "c"\n')
    assert new == "r = 'abc'\n"
    # The whole chain folds as ONE edit (topmost BinOp only).
    assert plan.edits_by_file["app/m.py"] == 1


def test_single_quote_operands_fold(tmp_path):
    new, _ = _rewrite(tmp_path, "r = 'foo' + 'bar'\n")
    assert new == "r = 'foobar'\n"


def test_repr_handles_quotes_and_escapes(tmp_path):
    # repr() guarantees a valid, re-parseable literal regardless of content —
    # the original quote style is intentionally not preserved.
    new, _ = _rewrite(tmp_path, """r = "it's " + "a test"\n""")
    assert new is not None
    folded = new[len("r = "):].rstrip("\n")
    assert ast.literal_eval(folded) == "it's a test"
    ast.parse(new)  # re-parses


def test_empty_string_operands_fold(tmp_path):
    new, _ = _rewrite(tmp_path, 'r = "" + "x"\n')
    assert new == "r = 'x'\n"


def test_four_literal_chain_fold(tmp_path):
    new, plan = _rewrite(tmp_path, 'r = "a" + "b" + "c" + "d"\n')
    assert new == "r = 'abcd'\n"
    assert plan.edits_by_file["app/m.py"] == 1


# --- the SKIP cases -------------------------------------------------------

def test_mixed_name_operand_not_folded(tmp_path):
    # "a" + x + "b" — the "a" + x part isn't two literals; never partially fold.
    new, plan = _rewrite(tmp_path, 'r = "a" + x + "b"\n')
    assert new is None and not plan.blockers


def test_mixed_left_name_not_folded(tmp_path):
    new, plan = _rewrite(tmp_path, 'r = x + "b"\n')
    assert new is None and not plan.blockers


def test_fstring_operand_skipped(tmp_path):
    # An f-string operand is a JoinedStr, not a plain str Constant — skip.
    new, plan = _rewrite(tmp_path, 'r = f"a{x}" + "b"\n')
    assert new is None and not plan.blockers


def test_concat_inside_fstring_skipped(tmp_path):
    # A "+" living within an f-string's formatted value is excluded wholesale.
    body = 'r = f"""{\'a\' + \'b\'}"""\n'
    new, plan = _rewrite(tmp_path, body)
    assert new is None and not plan.blockers


def test_bytes_skipped(tmp_path):
    new, plan = _rewrite(tmp_path, 'r = b"a" + b"b"\n')
    assert new is None and not plan.blockers


def test_bytes_str_mix_skipped(tmp_path):
    new, plan = _rewrite(tmp_path, 'r = "a" + b"b"\n')
    assert new is None and not plan.blockers


def test_number_operand_skipped(tmp_path):
    # Integer Add is not a string concat — left alone.
    new, plan = _rewrite(tmp_path, "r = 1 + 2\n")
    assert new is None and not plan.blockers


def test_non_add_op_skipped(tmp_path):
    # "a" * 3 is repetition, not concatenation — only Add folds.
    new, plan = _rewrite(tmp_path, 'r = "a" * 3\n')
    assert new is None and not plan.blockers


def test_multiline_concat_skipped(tmp_path):
    # A concat spanning lines is skipped — the column splice only fits one line.
    new, plan = _rewrite(tmp_path, 'r = (\n    "a"\n    + "b"\n)\n')
    assert new is None and not plan.blockers


def test_implicit_adjacency_is_not_a_binop(tmp_path):
    # "a" "b" (implicit literal concatenation) parses to ONE Constant, no BinOp —
    # there is nothing to fold and nothing changes.
    new, plan = _rewrite(tmp_path, 'r = "a" "b"\n')
    assert new is None and not plan.blockers


# --- correctness guarantees -----------------------------------------------

def test_folded_value_matches_via_literal_eval(tmp_path):
    # The emitted literal must literal_eval back to the exact concatenation. Note
    # ast.literal_eval refuses to evaluate "+" over strings, so we compare the
    # emitted literal's value against the Python-level concatenation directly.
    new, _ = _rewrite(tmp_path, 'r = "foo" + "bar" + "baz"\n')
    assert new is not None
    folded = new[len("r = "):].rstrip("\n")
    assert ast.literal_eval(folded) == "foo" + "bar" + "baz"
    # And each operand individually literal_evals to its piece.
    assert ast.literal_eval(folded) == (
        ast.literal_eval('"foo"') + ast.literal_eval('"bar"')
        + ast.literal_eval('"baz"'))


def test_reparse_guarantee(tmp_path):
    new, _ = _rewrite(tmp_path, 'r = "tab\\t" + "newline-safe"\n')
    assert new is not None
    ast.parse(new)  # the spliced module re-parses


def test_two_occurrences_one_line(tmp_path):
    new, plan = _rewrite(tmp_path, 'r = ("a" + "b", "c" + "d")\n')
    assert new == "r = ('ab', 'cd')\n"
    assert plan.edits_by_file["app/m.py"] == 2


def test_two_occurrences_two_lines(tmp_path):
    new, plan = _rewrite(tmp_path, 'p = "a" + "b"\nq = "c" + "d"\n')
    assert new == "p = 'ab'\nq = 'cd'\n"
    assert plan.edits_by_file["app/m.py"] == 2


def test_mixed_chain_with_eligible_sibling(tmp_path):
    # ("a" + "b") folds; (x + "c") does not — only the eligible one is rewritten.
    # The untouched "c" keeps its ORIGINAL quote style (a column splice never
    # rewrites code it doesn't fold).
    new, plan = _rewrite(tmp_path, 'r = ("a" + "b", x + "c")\n')
    assert new == 'r = (\'ab\', x + "c")\n'
    assert plan.edits_by_file["app/m.py"] == 1


def test_no_double_fold_of_nested_chain(tmp_path):
    # The inner BinOp of "a" + "b" + "c" must not be folded separately — exactly
    # one edit lands, anchored at the topmost node.
    new, plan = _rewrite(tmp_path, 'r = "a" + "b" + "c"\n')
    assert new == "r = 'abc'\n"
    assert plan.edits_by_file["app/m.py"] == 1


# --- determinism ----------------------------------------------------------

def test_determinism(tmp_path):
    body = 'p = "a" + "b"\nq = "c" + "d" + "e"\nr = ("f" + "g", x + "h")\n'
    _project(tmp_path, body)
    first = plan_fold_literal_string_concat(str(tmp_path), "app/m.py")
    second = plan_fold_literal_string_concat(str(tmp_path), "app/m.py")
    assert first.new_contents == second.new_contents
    assert first.edits_by_file == second.edits_by_file


# --- exec-equivalence -----------------------------------------------------

def _exec_value(src_expr):
    """Evaluate ``src_expr`` (a single expression) in a fresh namespace."""
    return eval(compile(ast.parse(src_expr, mode="eval"), "<x>", "eval"), {}, {})


def test_exec_equivalence_representative_inputs(tmp_path):
    cases = [
        '"foo" + "bar"',
        '"a" + "b" + "c"',
        '"x" + "" + "y"',
        '"line1\\n" + "line2"',
        '"with \\"quotes\\"" + " here"',
    ]
    for expr in cases:
        new, _ = _rewrite(tmp_path, f"r = {expr}\n")
        assert new is not None, expr
        rewritten = new[len("r = "):].rstrip("\n")
        assert _exec_value(expr) == _exec_value(rewritten), (expr, rewritten)
