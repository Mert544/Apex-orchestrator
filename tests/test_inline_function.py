"""Tests for inline_function.plan_inline — the inverse of extract-method."""

from __future__ import annotations

import argparse

from app.execution.inline_function import plan_inline


def _write(tmp_path, rel, src):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return p


# ── Happy paths ──

def test_inline_substitutes_params_and_removes_def(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x, rate):\n"
           "    return x * rate\n"
           "\n"
           "\n"
           "def total(price):\n"
           "    return fee(price, 2) + 1\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    # The definition is gone.
    assert "def fee(" not in new
    # The call is replaced by the substituted, parenthesized return expr.
    assert "((price) * (2))" in new
    assert "fee(" not in new


def test_inline_with_default_value_substitution(tmp_path):
    _write(tmp_path, "m.py",
           "def scaled(x, factor=10):\n"
           "    return x * factor\n"
           "\n"
           "\n"
           "def use():\n"
           "    return scaled(3)\n")
    plan = plan_inline(str(tmp_path), "scaled")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    # The missing argument falls back to the parameter's default expression.
    assert "((3) * (10))" in new


def test_inline_with_keyword_argument(tmp_path):
    _write(tmp_path, "m.py",
           "def combine(a, b):\n"
           "    return a - b\n"
           "\n"
           "\n"
           "def use():\n"
           "    return combine(b=1, a=9)\n")
    plan = plan_inline(str(tmp_path), "combine")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    assert "((9) - (1))" in new


def test_inline_ignores_leading_docstring(tmp_path):
    _write(tmp_path, "m.py",
           "def doubler(x):\n"
           "    \"\"\"Double it.\"\"\"\n"
           "    return x + x\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return doubler(n)\n")
    # `x` is used twice, but `n` (a bare Name) is pure-simple, so it's safe.
    plan = plan_inline(str(tmp_path), "doubler")
    assert not plan.blockers, plan.blockers
    assert "((n) + (n))" in plan.new_contents["m.py"]


def test_inline_same_file_def_above_call(tmp_path):
    # The call sits ABOVE the def — deletion and call edit must stay ordered so
    # line numbers don't drift.
    _write(tmp_path, "m.py",
           "def use(n):\n"
           "    return fee(n)\n"
           "\n"
           "\n"
           "def fee(x):\n"
           "    return x * 2\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    assert "def fee" not in new
    assert "((n) * 2)" in new
    ns: dict = {}
    exec(compile(new, "x", "exec"), ns)
    assert ns["use"](5) == 10


def test_inline_across_two_files(tmp_path):
    _write(tmp_path, "helpers.py",
           "def fee(x):\n"
           "    return x * 2\n")
    _write(tmp_path, "main.py",
           "from helpers import fee\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return fee(n)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert not plan.blockers, plan.blockers
    # Definition removed from helpers.py, call replaced in main.py.
    assert "def fee" not in plan.new_contents["helpers.py"]
    assert "((n) * 2)" in plan.new_contents["main.py"]


# ── Blockers ──

def test_block_side_effect_duplication(tmp_path):
    _write(tmp_path, "m.py",
           "def sq(x):\n"
           "    return x * x\n"
           "\n"
           "\n"
           "def use():\n"
           "    return sq(compute())\n"
           "\n"
           "\n"
           "def compute():\n"
           "    return 5\n")
    plan = plan_inline(str(tmp_path), "sq")
    assert plan.blockers
    assert any("side-effecting" in b for b in plan.blockers)
    assert not plan.new_contents


def test_block_recursive(tmp_path):
    _write(tmp_path, "m.py",
           "def f(n):\n"
           "    return f(n)\n"
           "\n"
           "\n"
           "def use():\n"
           "    return f(2)\n")
    plan = plan_inline(str(tmp_path), "f")
    assert plan.blockers
    assert any("recursive" in b for b in plan.blockers)


def test_block_multiple_call_sites(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def a():\n"
           "    return fee(1)\n"
           "\n"
           "\n"
           "def b():\n"
           "    return fee(2)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("single call site" in b for b in plan.blockers)


def test_block_zero_call_sites(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("nothing to inline" in b for b in plan.blockers)


def test_block_object_reference(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use():\n"
           "    g = fee\n"
           "    return fee(1)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("bare object" in b for b in plan.blockers)


def test_block_args_kwargs(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(*args):\n"
           "    return args\n"
           "\n"
           "\n"
           "def use():\n"
           "    return fee(1, 2)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("args" in b for b in plan.blockers)


def test_block_not_single_return(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    y = x + 1\n"
           "    return y\n"
           "\n"
           "\n"
           "def use():\n"
           "    return fee(2)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("single `return EXPR`" in b for b in plan.blockers)


def test_block_decorator(tmp_path):
    _write(tmp_path, "m.py",
           "import functools\n"
           "\n"
           "\n"
           "@functools.cache\n"
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use():\n"
           "    return fee(1)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("decorator" in b for b in plan.blockers)


def test_block_star_unpacking_at_call(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(a, b):\n"
           "    return a + b\n"
           "\n"
           "\n"
           "def use(pair):\n"
           "    return fee(*pair)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("unpacking" in b for b in plan.blockers)


def test_block_defined_twice(tmp_path):
    _write(tmp_path, "a.py", "def fee(x):\n    return x\n")
    _write(tmp_path, "b.py", "def fee(x):\n    return x\n\n\ndef use():\n    return fee(1)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("exactly once" in b for b in plan.blockers)


# ── Functional equivalence ──

def test_functional_equivalence(tmp_path):
    src = ("def fee(x, rate=3):\n"
           "    return (x + 1) * rate\n"
           "\n"
           "\n"
           "def total(price):\n"
           "    return fee(price) + 100\n")
    _write(tmp_path, "m.py", src)
    plan = plan_inline(str(tmp_path), "fee")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]

    ns_old: dict = {}
    ns_new: dict = {}
    exec(compile(src, "old", "exec"), ns_old)
    exec(compile(new, "new", "exec"), ns_new)
    for v in (0, 5, -2):
        assert ns_old["total"](v) == ns_new["total"](v)


# ── CLI command ──

def test_cmd_inline_apply_and_dry_run(tmp_path, capsys):
    from app.cli_refactor import cmd_inline

    src = ("def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return fee(n)\n")
    _write(tmp_path, "m.py", src)

    # Dry run shows a diff, changes nothing.
    rc = cmd_inline(argparse.Namespace(
        function="fee", target=str(tmp_path),
        dry_run=True, no_verify=True, json=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry run" in out.lower()
    assert (tmp_path / "m.py").read_text() == src  # untouched

    # Real apply (no-verify since there's no test suite) rewrites the file.
    rc = cmd_inline(argparse.Namespace(
        function="fee", target=str(tmp_path),
        dry_run=False, no_verify=True, json=False))
    assert rc == 0
    result = (tmp_path / "m.py").read_text()
    assert "def fee" not in result
    assert "((n) * 2)" in result


def test_cmd_inline_blocked_returns_one(tmp_path, capsys):
    from app.cli_refactor import cmd_inline

    _write(tmp_path, "m.py", "def fee(x):\n    return x * 2\n")  # zero call sites
    rc = cmd_inline(argparse.Namespace(
        function="fee", target=str(tmp_path),
        dry_run=False, no_verify=True, json=False))
    assert rc == 1
    assert "blocked" in capsys.readouterr().out.lower()
