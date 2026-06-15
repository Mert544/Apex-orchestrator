"""Edge/error-path coverage for inline_function — per-call-site binding
rejections, helper internals, multi-line guards and plan re-verification.
Deterministic & hermetic (tmp_path)."""

from __future__ import annotations

import ast

from app.execution.inline_function import (
    _bare_object_names,
    _call_site_counts,
    _has_object_ref,
    _is_pure_simple,
    plan_inline,
    suggest_inlines,
)


def _write(tmp_path, rel, src):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return p


# ── helper internals ──

def test_is_pure_simple_rejects_call():
    node = ast.parse("f()", mode="eval").body
    assert _is_pure_simple(node) is False


def test_is_pure_simple_accepts_attribute_chain():
    node = ast.parse("a.b.c", mode="eval").body
    assert _is_pure_simple(node) is True


def test_has_object_ref_detects_attribute_use():
    tree = ast.parse("obj.fee\nfee(1)\n")
    # `obj.fee` is an Attribute whose attr matches → object ref (line 124).
    assert _has_object_ref({"m.py": tree}, "fee") is True


def test_bare_object_names_matches_has_object_ref():
    tree = ast.parse("g = fee\nfee(1)\nx.bar\n")
    trees = {"m.py": tree}
    bare = _bare_object_names(trees)
    for name in ("fee", "bar"):
        assert (name in bare) == _has_object_ref(trees, name)


def test_call_site_counts_matches_call_sites():
    tree = ast.parse("fee(1)\nfee(2)\nbar()\n")
    counts = _call_site_counts({"m.py": tree})
    assert counts["fee"] == 2
    assert counts["bar"] == 1


# ── plan_inline per-site binding rejections ──

def test_block_too_many_positional_args(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use():\n"
           "    return fee(1, 2)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("positional" in b for b in plan.blockers)
    assert not plan.new_contents


def test_block_unknown_keyword(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use():\n"
           "    return fee(y=3)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("is not a" in b and "parameter" in b for b in plan.blockers)
    assert not plan.new_contents


def test_block_missing_required_parameter(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x, y):\n"
           "    return x + y\n"
           "\n"
           "\n"
           "def use():\n"
           "    return fee(1)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("required parameter" in b for b in plan.blockers)
    assert not plan.new_contents


def test_block_double_star_unpacking(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(a, b):\n"
           "    return a + b\n"
           "\n"
           "\n"
           "def use(d):\n"
           "    return fee(**d)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("unpacking" in b for b in plan.blockers)


def test_block_multiline_call_site(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(a, b):\n"
           "    return a + b\n"
           "\n"
           "\n"
           "def use():\n"
           "    return fee(\n"
           "        1,\n"
           "        2,\n"
           "    )\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert plan.blockers
    assert any("spans multiple lines" in b for b in plan.blockers)
    assert not plan.new_contents


def test_substitute_handles_multiline_return_expr(tmp_path):
    # A return whose EXPR itself spans multiple lines, with a parameter used on
    # the SECOND line, exercises the per-line offset rebasing (line 230). The
    # single call site is single-line.
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return 1 + (\n"
           "        x + x)\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return fee(n)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert not plan.blockers, plan.blockers
    new = plan.new_contents["m.py"]
    assert "(n)" in new
    ns: dict = {}
    exec(compile(new, "x", "exec"), ns)
    assert ns["use"](4) == 9


def test_syntax_error_module_is_skipped(tmp_path):
    # A broken sibling module must not crash the scan; the good def still inlines.
    _write(tmp_path, "bad.py", "def broken(:\n    pass\n")
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return fee(n)\n")
    plan = plan_inline(str(tmp_path), "fee")
    assert not plan.blockers, plan.blockers
    assert "def fee" not in plan.new_contents["m.py"]


# ── suggest_inlines edge paths ──

def test_suggest_inlines_skips_syntax_error_module(tmp_path):
    _write(tmp_path, "bad.py", "def broken(:\n    pass\n")
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return fee(n)\n")
    out = suggest_inlines(str(tmp_path))
    assert [s["function"] for s in out] == ["fee"]


def test_suggest_inlines_skips_multi_definition(tmp_path):
    # Same name defined in two modules → defined-more-than-once, never suggested.
    _write(tmp_path, "a.py", "def fee(x):\n    return x\n")
    _write(tmp_path, "b.py",
           "def fee(x):\n"
           "    return x\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return fee(n)\n")
    out = suggest_inlines(str(tmp_path))
    assert "fee" not in {s["function"] for s in out}


def test_suggest_inlines_accepts_prebuilt_trees(tmp_path):
    _write(tmp_path, "m.py",
           "def fee(x):\n"
           "    return x * 2\n"
           "\n"
           "\n"
           "def use(n):\n"
           "    return fee(n)\n")
    src = (tmp_path / "m.py").read_text()
    trees = {"m.py": ast.parse(src)}
    out = suggest_inlines(str(tmp_path), trees)
    assert out == suggest_inlines(str(tmp_path))
