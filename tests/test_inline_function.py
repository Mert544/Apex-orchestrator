"""Tests for inline_function.plan_inline — the inverse of extract-method."""

from __future__ import annotations

import argparse

from app.execution.inline_function import plan_inline, suggest_inlines


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


# ── Multiple call sites ──

def test_inline_two_sites_same_file(tmp_path):
    # Two call sites in ONE file, both below the def. Both get folded and the
    # def is removed; edits within the file apply bottom-up so line numbers
    # don't drift.
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
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    assert "def fee" not in new
    assert "fee(" not in new
    assert "((1) * 2)" in new
    assert "((2) * 2)" in new
    assert plan.edits_by_file["m.py"] == 3  # two splices + the deletion
    ns: dict = {}
    exec(compile(new, "x", "exec"), ns)
    assert ns["a"]() == 2
    assert ns["b"]() == 4


def test_inline_two_sites_same_file_def_between(tmp_path):
    # A call ABOVE the def and a call BELOW it in the same file — the bottom-up
    # ordering has to keep the above-def call's line index valid after the
    # deletion removes the def block under it.
    _write(tmp_path, "m.py",
           "def above():\n"
           "    return fee(3)\n"
           "\n"
           "\n"
           "def fee(x):\n"
           "    return x + 1\n"
           "\n"
           "\n"
           "def below():\n"
           "    return fee(7)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    assert "def fee" not in new
    assert "((3) + 1)" in new
    assert "((7) + 1)" in new
    ns: dict = {}
    exec(compile(new, "x", "exec"), ns)
    assert ns["above"]() == 4
    assert ns["below"]() == 8


def test_inline_two_sites_across_files(tmp_path):
    _write(tmp_path, "helpers.py",
           "def fee(x):\n"
           "    return x * 2\n")
    _write(tmp_path, "one.py",
           "from helpers import fee\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return fee(n)\n")
    _write(tmp_path, "two.py",
           "from helpers import fee\n"
           "\n"
           "\n"
           "def other(m):\n"
           "    return fee(m) + 1\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert not plan.blockers, plan.blockers
    assert "def fee" not in plan.new_contents["helpers.py"]
    assert "((n) * 2)" in plan.new_contents["one.py"]
    assert "((m) * 2)" in plan.new_contents["two.py"]
    assert plan.edits_by_file["helpers.py"] == 1
    assert plan.edits_by_file["one.py"] == 1
    assert plan.edits_by_file["two.py"] == 1


def test_inline_sites_pass_different_arguments(tmp_path):
    # Each site is bound independently: positional, keyword, and a default.
    _write(tmp_path, "m.py",
           "def fee(x, rate=10):\n"
           "    return x * rate\n"
           "\n"
           "\n"
           "def a():\n"
           "    return fee(2, 5)\n"
           "\n"
           "\n"
           "def b():\n"
           "    return fee(rate=3, x=4)\n"
           "\n"
           "\n"
           "def c():\n"
           "    return fee(7)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    assert "((2) * (5))" in new
    assert "((4) * (3))" in new
    assert "((7) * (10))" in new
    ns: dict = {}
    exec(compile(new, "x", "exec"), ns)
    assert ns["a"]() == 10
    assert ns["b"]() == 12
    assert ns["c"]() == 70


def test_block_when_one_of_many_sites_is_unsafe(tmp_path):
    # Two sites: the first is safe, the second duplicates a side-effecting call
    # into a twice-used parameter. The WHOLE operation must block, and the
    # message must name the offending site.
    _write(tmp_path, "m.py",
           "def sq(x):\n"
           "    return x * x\n"
           "\n"
           "\n"
           "def safe():\n"
           "    return sq(4)\n"
           "\n"
           "\n"
           "def unsafe():\n"
           "    return sq(compute())\n"
           "\n"
           "\n"
           "def compute():\n"
           "    return 5\n")
    plan = plan_inline(str(tmp_path), "sq")
    assert plan.blockers
    assert any("side-effecting" in b for b in plan.blockers)
    assert any("m.py:10" in b for b in plan.blockers)  # names the unsafe site
    assert not plan.new_contents


def test_functional_equivalence_two_sites(tmp_path):
    src = ("def fee(x, rate=3):\n"
           "    return (x + 1) * rate\n"
           "\n"
           "\n"
           "def total(price):\n"
           "    return fee(price) + 100\n"
           "\n"
           "\n"
           "def discounted(price):\n"
           "    return fee(price, 2) - 5\n")
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
        assert ns_old["discounted"](v) == ns_new["discounted"](v)


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


# ── suggest_inlines: which helpers would `apex inline` cleanly accept? ──

def test_suggest_inlines_finds_single_use_return_helper(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return fee(n)\n")
    out = suggest_inlines(str(tmp_path))
    assert len(out) == 1
    s = out[0]
    assert s == {"module": "m.py", "function": "fee", "line": 1, "call_sites": 1}


def test_suggest_inlines_allows_two_call_sites(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use(a, b):\n"
           "    return fee(a) + fee(b)\n")
    out = suggest_inlines(str(tmp_path))
    assert [s["function"] for s in out] == ["fee"]
    assert out[0]["call_sites"] == 2


def test_suggest_inlines_ignores_many_call_sites(tmp_path):
    # Three call sites — inlining would bloat code, so it's not a candidate.
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use(a, b, c):\n"
           "    return fee(a) + fee(b) + fee(c)\n")
    assert suggest_inlines(str(tmp_path)) == []


def test_suggest_inlines_ignores_recursive_decorated_and_nonreturn(tmp_path):
    _write(tmp_path, "rec.py",
           "def fac(n):\n"
           "    return n * fac(n - 1)\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return fac(n)\n")
    _write(tmp_path, "deco.py",
           "import functools\n"
           "\n"
           "\n"
           "@functools.cache\n"
           "def cached(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use2(n):\n"
           "    return cached(n)\n")
    _write(tmp_path, "body.py",
           "def two_stmt(x):\n"
           "    y = x * 2\n"
           "    return y\n"
           "\n"
           "\n"
           "def use3(n):\n"
           "    return two_stmt(n)\n")
    names = {s["function"] for s in suggest_inlines(str(tmp_path))}
    assert "fac" not in names      # recursive
    assert "cached" not in names   # decorated
    assert "two_stmt" not in names # body isn't a single return


def test_suggest_inlines_ignores_bare_referenced_helper(tmp_path):
    # `fee` travels as a bare object (passed to map), so its identity is used.
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use(items):\n"
           "    return list(map(fee, items))\n")
    assert suggest_inlines(str(tmp_path)) == []


def test_suggest_inlines_ignores_starargs_and_zero_sites(tmp_path):
    _write(tmp_path, "m.py",
           "def variadic(*args):\n"
           "    return sum(args)\n"
           "\n"
           "\n"
           "def orphan(x):\n"     # defined but never called
           "    return x + 1\n"
           "\n"
           "\n"
           "def use(a, b):\n"
           "    return variadic(a, b)\n")
    names = {s["function"] for s in suggest_inlines(str(tmp_path))}
    assert "variadic" not in names  # *args
    assert "orphan" not in names    # zero call sites
    assert "use" not in names       # not a single-return helper


def test_suggest_inlines_is_deterministic_and_sorted(tmp_path):
    _write(tmp_path, "b.py",
           "def beta(x):\n"
           "    return x + 1\n"
           "\n"
           "\n"
           "def ub(a, c):\n"        # two call sites
           "    return beta(a) + beta(c)\n")
    _write(tmp_path, "a.py",
           "def alpha(x):\n"
           "    return x - 1\n"
           "\n"
           "\n"
           "def ua(n):\n"           # one call site
           "    return alpha(n)\n")
    out = suggest_inlines(str(tmp_path))
    again = suggest_inlines(str(tmp_path))
    assert out == again  # deterministic
    # Fewest call sites first, then module: alpha (1 site) before beta (2 sites).
    assert [(s["function"], s["call_sites"]) for s in out] == [("alpha", 1), ("beta", 2)]


def test_suggested_helper_actually_inlines_cleanly(tmp_path):
    # Round-trip: a suggested helper's plan_inline must apply, not block.
    _write(tmp_path, "m.py",
           "RATE = 3\n"
           "\n"
           "\n"
           "def fee(x):\n"
           "    return x * RATE\n"
           "\n"
           "\n"
           "def total(price):\n"
           "    return fee(price) + 1\n")
    out = suggest_inlines(str(tmp_path))
    assert out, "expected a suggestion"
    name = out[0]["function"]
    plan = plan_inline(str(tmp_path), name)
    assert not plan.blockers, plan.blockers
    assert plan.new_contents  # it produced a real edit
