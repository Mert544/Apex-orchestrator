from __future__ import annotations

import ast

from app.execution.combine_augmented_assign import plan_combine_augmented_assign


def _project(tmp_path, body):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(body, encoding="utf-8")
    return tmp_path


def _rewrite(tmp_path, body):
    """Run the plan over ``body`` and return the rewritten module source (or
    ``None`` if nothing changed)."""
    _project(tmp_path, body)
    plan = plan_combine_augmented_assign(str(tmp_path), "app/m.py")
    assert not plan.blockers
    return plan.new_contents.get("app/m.py")


# --- the core rewrites --------------------------------------------------------

def test_name_add(tmp_path):
    out = _rewrite(tmp_path, "x = x + 1\n")
    assert out == "x += 1\n"


def test_name_mult(tmp_path):
    out = _rewrite(tmp_path, "total = total * 2\n")
    assert out == "total *= 2\n"


def test_attribute_sub(tmp_path):
    out = _rewrite(tmp_path, "self.n = self.n - 1\n")
    assert out == "self.n -= 1\n"


def test_subscript_add(tmp_path):
    out = _rewrite(tmp_path, "d[k] = d[k] + 1\n")
    assert out == "d[k] += 1\n"


def test_subscript_constant_index(tmp_path):
    out = _rewrite(tmp_path, "row[0] = row[0] | mask\n")
    assert out == "row[0] |= mask\n"


def test_floor_div(tmp_path):
    out = _rewrite(tmp_path, "x = x // 2\n")
    assert out == "x //= 2\n"


def test_pow(tmp_path):
    out = _rewrite(tmp_path, "x = x ** 2\n")
    assert out == "x **= 2\n"


def test_bitwise_ops(tmp_path):
    out = _rewrite(
        tmp_path,
        "a = a & b\n"
        "c = c | d\n"
        "e = e ^ f\n"
        "g = g >> 1\n"
        "h = h << 2\n",
    )
    assert out == (
        "a &= b\n"
        "c |= d\n"
        "e ^= f\n"
        "g >>= 1\n"
        "h <<= 2\n"
    )


def test_mod_and_div(tmp_path):
    out = _rewrite(tmp_path, "a = a % m\nb = b / 3\n")
    assert out == "a %= m\nb /= 3\n"


def test_complex_right_operand_kept_verbatim(tmp_path):
    # get_source_segment recovers the BinOp's right operand; the redundant outer
    # parens aren't part of that node, so they drop — still equivalent, since
    # ``x op= RIGHT`` always applies to the whole right-hand expression.
    out = _rewrite(tmp_path, "x = x + (a * b + c)\n")
    assert out == "x += a * b + c\n"


def test_parens_drop_stays_equivalent(tmp_path):
    # x = x * (a + b) -> x *= a + b ; the whole right side is the multiplicand.
    before = "x = 5\na = 2\nb = 3\nx = x * (a + b)\nresult = x\n"
    after = _rewrite(tmp_path, before)
    assert after == "x = 5\na = 2\nb = 3\nx *= a + b\nresult = x\n"
    ns_before, ns_after = {}, {}
    exec(compile(before, "<b>", "exec"), ns_before)
    exec(compile(after, "<a>", "exec"), ns_after)
    assert ns_before["result"] == ns_after["result"] == 25


def test_preserves_indentation_and_surroundings(tmp_path):
    out = _rewrite(
        tmp_path,
        "def f(x):\n"
        "    # a running total\n"
        "    x = x + 1  # bump\n"
        "    return x\n",
    )
    assert out == (
        "def f(x):\n"
        "    # a running total\n"
        "    x += 1  # bump\n"
        "    return x\n"
    )


def test_multiple_rewrites_one_module(tmp_path):
    out = _rewrite(tmp_path, "x = x + 1\ny = y * 3\nz = z - 4\n")
    assert out == "x += 1\ny *= 3\nz -= 4\n"


# --- the cases that must be LEFT ALONE ----------------------------------------

def test_target_not_left_operand_untouched(tmp_path):
    # x = 1 + x : commutativity is not assumed; += puts x on the left.
    assert _rewrite(tmp_path, "x = 1 + x\n") is None


def test_different_target_untouched(tmp_path):
    assert _rewrite(tmp_path, "x = y + 1\n") is None


def test_side_effecting_target_untouched(tmp_path):
    # f().x has a Call — evaluating it once vs twice would differ.
    assert _rewrite(tmp_path, "f().x = f().x + 1\n") is None


def test_call_subscript_index_untouched(tmp_path):
    # d[g()] index is side-effecting.
    assert _rewrite(tmp_path, "d[g()] = d[g()] + 1\n") is None


def test_compound_subscript_index_untouched(tmp_path):
    # a richer index expression is not a plain Name/Constant.
    assert _rewrite(tmp_path, "a[b + c] = a[b + c] + 1\n") is None


def test_multi_target_untouched(tmp_path):
    # a = b = a + 1 : a chained (multi-target) assignment.
    assert _rewrite(tmp_path, "a = b = a + 1\n") is None


def test_multiline_statement_untouched(tmp_path):
    assert _rewrite(tmp_path, "x = (\n    x + 1\n)\n") is None


def test_matmul_not_rewritten(tmp_path):
    # @ is outside the requested operator set, so x = x @ m is left alone.
    assert _rewrite(tmp_path, "x = x @ m\n") is None


def test_annotated_assign_untouched(tmp_path):
    # AnnAssign (x: int = x + 1) is not an ast.Assign — not in scope.
    assert _rewrite(tmp_path, "x: int = x + 1\n") is None


def test_attribute_chain_mismatch_untouched(tmp_path):
    # self.a = self.b + 1 : left operand differs from target.
    assert _rewrite(tmp_path, "self.a = self.b + 1\n") is None


# --- semantic / exec equivalence ----------------------------------------------

def test_exec_equivalence(tmp_path):
    before = (
        "x = 10\n"
        "x = x + 5\n"
        "d = {'k': 3}\n"
        "d['k'] = d['k'] * 4\n"
        "result = (x, d['k'])\n"
    )
    after = _rewrite(tmp_path, before)
    assert after is not None and after != before

    ns_before: dict = {}
    ns_after: dict = {}
    exec(compile(before, "<before>", "exec"), ns_before)
    exec(compile(after, "<after>", "exec"), ns_after)
    assert ns_before["result"] == ns_after["result"] == (15, 12)


# --- blockers / no-op / safety ------------------------------------------------

def test_no_op_on_clean_module(tmp_path):
    _project(tmp_path, "x = 1\n")
    plan = plan_combine_augmented_assign(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers


def test_missing_module_blocks(tmp_path):
    plan = plan_combine_augmented_assign(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_unparseable_module_blocks(tmp_path):
    _project(tmp_path, "def (:\n")
    plan = plan_combine_augmented_assign(str(tmp_path), "app/m.py")
    assert plan.blockers and not plan.new_contents


def test_fixture_subject_is_skipped(tmp_path):
    plan = plan_combine_augmented_assign(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_result_reparses(tmp_path):
    out = _rewrite(tmp_path, "self.count = self.count + step\n")
    assert out is not None
    ast.parse(out)  # must be valid Python


def test_deterministic(tmp_path):
    body = "x = x + 1\ny = y * 2\n"
    _project(tmp_path, body)
    first = plan_combine_augmented_assign(str(tmp_path), "app/m.py").new_contents
    second = plan_combine_augmented_assign(str(tmp_path), "app/m.py").new_contents
    assert first == second


# --- self registration --------------------------------------------------------

def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "combine-augmented-assign" in available_objectives()
