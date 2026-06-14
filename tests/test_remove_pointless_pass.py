from __future__ import annotations

import ast

from app.execution.remove_pointless_pass import plan_remove_pointless_pass


def _project(tmp_path, body="x = 1\n"):
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "m.py").write_text(body, encoding="utf-8")
    return tmp_path


def _rewrite(tmp_path, body):
    """Helper: run the plan over a one-module project, return new source (or None
    if the plan is an empty no-op) and the plan itself."""
    _project(tmp_path, body)
    plan = plan_remove_pointless_pass(str(tmp_path), "app/m.py")
    new = plan.new_contents.get("app/m.py")
    return new, plan


# --- scaffold invariants -------------------------------------------------

def test_noop_on_clean_module(tmp_path):
    _project(tmp_path)
    plan = plan_remove_pointless_pass(str(tmp_path), "app/m.py")
    assert not plan.new_contents and not plan.blockers  # empty no-op, not a failure


def test_missing_module_blocks(tmp_path):
    plan = plan_remove_pointless_pass(str(tmp_path), "app/nope.py")
    assert plan.blockers


def test_fixture_subject_is_skipped(tmp_path):
    # Even though the body has a removable pass, a test_-prefixed path is skipped.
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_x.py").write_text(
        "def f():\n    x = 1\n    pass\n", encoding="utf-8")
    plan = plan_remove_pointless_pass(str(tmp_path), "tests/test_x.py")
    assert not plan.new_contents and not plan.blockers


def test_self_registers():
    from app.engine.objective_compiler import available_objectives
    assert "remove-pointless-pass" in available_objectives()  # via the registry


def test_unparseable_module_blocks(tmp_path):
    new, plan = _rewrite(tmp_path, "def broken(:\n    pass\n")
    assert new is None and plan.blockers


# --- the removal cases ---------------------------------------------------

def test_pass_among_other_statements_removed(tmp_path):
    new, plan = _rewrite(tmp_path, "def f():\n    x = 1\n    pass\n    return x\n")
    assert new == "def f():\n    x = 1\n    return x\n"
    assert plan.edits_by_file["app/m.py"] == 1


def test_trailing_pass_after_real_statement_removed(tmp_path):
    new, _ = _rewrite(tmp_path, "def f():\n    x = 1\n    pass\n")
    assert new == "def f():\n    x = 1\n"


def test_pass_in_if_body_with_other_stmt_removed(tmp_path):
    new, _ = _rewrite(tmp_path, "if c:\n    do()\n    pass\n")
    assert new == "if c:\n    do()\n"


def test_pass_in_loop_with_other_stmt_removed(tmp_path):
    new, _ = _rewrite(tmp_path, "for i in xs:\n    use(i)\n    pass\n")
    assert new == "for i in xs:\n    use(i)\n"


def test_docstring_plus_pass_removes_pass_keeps_docstring(tmp_path):
    # A docstring is a real statement, so [docstring, pass] has two statements —
    # the pass is pointless and removed; the docstring survives as the sole body.
    new, _ = _rewrite(tmp_path, 'def f():\n    """doc"""\n    pass\n')
    assert new == 'def f():\n    """doc"""\n'
    ast.parse(new)


# --- the SKIP cases (intentional empty bodies left untouched) ------------

def test_empty_function_sole_pass_untouched(tmp_path):
    new, plan = _rewrite(tmp_path, "def f():\n    pass\n")
    assert new is None and not plan.blockers


def test_except_sole_pass_untouched(tmp_path):
    new, plan = _rewrite(tmp_path, "try:\n    risky()\nexcept Exception:\n    pass\n")
    assert new is None and not plan.blockers


def test_empty_class_sole_pass_untouched(tmp_path):
    new, plan = _rewrite(tmp_path, "class C:\n    pass\n")
    assert new is None and not plan.blockers


def test_match_case_sole_pass_untouched(tmp_path):
    new, plan = _rewrite(
        tmp_path, "match x:\n    case 1:\n        y = 1\n    case _:\n        pass\n")
    # case 1 has no pass; case _ has a SOLE pass — nothing to remove.
    assert new is None and not plan.blockers


def test_no_pass_is_noop(tmp_path):
    new, plan = _rewrite(tmp_path, "def f():\n    x = 1\n    return x\n")
    assert new is None and not plan.blockers


# --- mixed: some pass removed, some left -------------------------------

def test_sole_pass_kept_while_pointless_pass_removed(tmp_path):
    body = (
        "def empty():\n"
        "    pass\n"
        "def real():\n"
        "    x = 1\n"
        "    pass\n"
        "    return x\n"
    )
    new, plan = _rewrite(tmp_path, body)
    assert new == (
        "def empty():\n"
        "    pass\n"
        "def real():\n"
        "    x = 1\n"
        "    return x\n"
    )
    assert plan.edits_by_file["app/m.py"] == 1


def test_match_case_with_other_stmt_removes_pass(tmp_path):
    body = (
        "match x:\n"
        "    case 1:\n"
        "        y = 1\n"
        "        pass\n"
        "    case _:\n"
        "        pass\n"
    )
    new, plan = _rewrite(tmp_path, body)
    # case 1 has a real stmt + pass -> pass removed; case _ sole pass -> kept.
    assert new == (
        "match x:\n"
        "    case 1:\n"
        "        y = 1\n"
        "    case _:\n"
        "        pass\n"
    )
    assert plan.edits_by_file["app/m.py"] == 1


# --- multiple in one module ----------------------------------------------

def test_multiple_pointless_pass_in_one_module(tmp_path):
    body = (
        "def a():\n"
        "    x = 1\n"
        "    pass\n"
        "def b():\n"
        "    y = 2\n"
        "    pass\n"
        "    return y\n"
        "if cond:\n"
        "    go()\n"
        "    pass\n"
    )
    new, plan = _rewrite(tmp_path, body)
    assert new == (
        "def a():\n"
        "    x = 1\n"
        "def b():\n"
        "    y = 2\n"
        "    return y\n"
        "if cond:\n"
        "    go()\n"
    )
    assert plan.edits_by_file["app/m.py"] == 3


# --- re-parse guarantee & determinism ------------------------------------

def test_result_reparses(tmp_path):
    new, _ = _rewrite(
        tmp_path,
        "def f():\n    x = 1\n    pass\nfor i in r:\n    use(i)\n    pass\n")
    assert new is not None
    ast.parse(new)  # re-parses cleanly


def test_deterministic(tmp_path):
    body = "def f():\n    x = 1\n    pass\n    return x\n"
    _project(tmp_path, body)
    first = plan_remove_pointless_pass(str(tmp_path), "app/m.py").new_contents
    second = plan_remove_pointless_pass(str(tmp_path), "app/m.py").new_contents
    assert first == second  # same input -> identical output


# --- exec-equivalence on a representative case ---------------------------

def test_exec_equivalence_representative_case(tmp_path):
    # A `pass` among other statements is a true no-op: the function before and
    # after the rewrite must compute the identical result for every input.
    before = (
        "def classify(n):\n"
        "    if n > 0:\n"
        "        label = 'pos'\n"
        "        pass\n"
        "    else:\n"
        "        label = 'nonpos'\n"
        "        pass\n"
        "    return label\n"
    )
    new, _ = _rewrite(tmp_path, before)
    assert new is not None and "pass" not in new
    ns_before, ns_after = {}, {}
    exec(compile(ast.parse(before), "<b>", "exec"), ns_before)
    exec(compile(ast.parse(new), "<a>", "exec"), ns_after)
    for n in (-5, -1, 0, 1, 42):
        assert ns_before["classify"](n) == ns_after["classify"](n) == (
            "pos" if n > 0 else "nonpos")
