"""Edge/error-path coverage for inline_function — per-call-site binding
rejections, helper internals, multi-line guards and plan re-verification.
Deterministic & hermetic (tmp_path)."""

from __future__ import annotations

import ast

from app.execution.inline_function import (
    _bare_and_call_index,
    _bare_object_names,
    _call_site_counts,
    _call_sites,
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


# ── characterization: the one-pass index hoist must not change output ──

def _representative_project(tmp_path):
    """A multi-module project exercising every suggestion branch: a clean
    single-use helper, a clean two-call helper, a many-call (over-cap) helper, a
    bare-referenced helper, a recursive helper, a decorated helper, a non-return
    helper, an attribute call site, and a zero-call helper."""
    _write(tmp_path, "app/pricing.py",
           "RATE = 3\n"
           "\n"
           "\n"
           "def fee(x):\n"
           "    return x * RATE\n"
           "\n"
           "\n"
           "def double(x):\n"
           "    return x + x\n"
           "\n"
           "\n"
           "def lonely(x):\n"
           "    return x - 1\n"
           "\n"
           "\n"
           "def quote(n):\n"
           "    return fee(n)\n")
    _write(tmp_path, "app/orders.py",
           "from app.pricing import double, fee\n"
           "import app.pricing as pricing\n"
           "\n"
           "\n"
           "@staticmethod\n"
           "def decorated(x):\n"
           "    return x\n"
           "\n"
           "\n"
           "def recur(x):\n"
           "    return recur(x)\n"
           "\n"
           "\n"
           "def noreturn(x):\n"
           "    y = x + 1\n"
           "    return y\n"
           "\n"
           "\n"
           "def total(a, b):\n"
           "    big = double(a) + double(b) + recur(a)\n"
           "    return big + pricing.fee(a) + decorated(b) + noreturn(a)\n")


# Pinned, byte-exact expected output of suggest_inlines on the representative
# project — recomputing the indices in one walk must reproduce this exactly.
_EXPECTED_SUGGESTIONS = [
    {"module": "app/pricing.py", "function": "fee", "line": 4, "call_sites": 1},
    {"module": "app/pricing.py", "function": "double", "line": 8, "call_sites": 2},
]


def test_suggest_inlines_characterization_pinned_output(tmp_path):
    _representative_project(tmp_path)
    out = suggest_inlines(str(tmp_path))
    # Exact list, exact order, every field — the byte-identical contract.
    assert out == _EXPECTED_SUGGESTIONS
    # Determinism: a second scan is identical.
    assert suggest_inlines(str(tmp_path)) == _EXPECTED_SUGGESTIONS


def test_bare_and_call_index_equals_standalone_helpers(tmp_path):
    # The one-walk combined index is byte-identical to running the two
    # characterized standalone helpers (membership + integer counts).
    _representative_project(tmp_path)
    trees = {
        "app/pricing.py": ast.parse((tmp_path / "app" / "pricing.py").read_text()),
        "app/orders.py": ast.parse((tmp_path / "app" / "orders.py").read_text()),
    }
    bare, counts = _bare_and_call_index(trees)
    assert bare == _bare_object_names(trees)
    assert counts == _call_site_counts(trees)
    for name in ("fee", "double", "lonely", "quote", "decorated", "recur",
                 "noreturn", "total", "RATE", "pricing", "missing"):
        assert (name in bare) == _has_object_ref(trees, name)
        assert counts.get(name, 0) == len(_call_sites(trees, name))


def test_bare_and_call_index_empty_trees():
    # Empty project: both indices empty, no crash.
    bare, counts = _bare_and_call_index({})
    assert bare == set()
    assert counts == {}


def test_bare_and_call_index_callee_in_nested_and_attr_positions():
    # A name that is BOTH a callee (count) and a bare object (set) elsewhere, plus
    # an attribute call whose attr is bare elsewhere — the shared-walk callee
    # guard must match the standalone helpers exactly on these tricky shapes.
    tree = ast.parse(
        "g = fee\n"
        "fee(1)\n"
        "fee(2)\n"
        "obj.fee()\n"
        "x = obj.bar\n"
        "obj.bar()\n"
        "outer(inner(z))\n")
    trees = {"m.py": tree}
    bare, counts = _bare_and_call_index(trees)
    assert bare == _bare_object_names(trees)
    assert counts == _call_site_counts(trees)
    assert counts["fee"] == 2  # the two bare-Name calls only (obj.fee() is Attr)
    assert "fee" in bare       # g = fee is a bare object ref


# ── Characterization: pin the exact plan after the plan_inline decomposition ──

def _pin(tmp_path, files, func):
    for rel, src in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    plan = plan_inline(str(tmp_path), func)
    return (plan.defined_in, sorted(plan.blockers),
            dict(sorted(plan.new_contents.items())),
            dict(sorted(plan.edits_by_file.items())))


def test_plan_inline_characterization_multi_site_multi_file(tmp_path):
    """A cross-file, multi-site, def-and-call-in-same-file plan, pinned exactly.
    Guards the mechanical decomposition: the produced plan stays byte-identical."""
    defined_in, blockers, new_contents, edits = _pin(
        tmp_path,
        {
            "a.py": (
                "RATE = 2\n"
                "\n"
                "def fee(x, rate=RATE):\n"
                "    return x * rate\n"
                "\n"
                "\n"
                "def total(price):\n"
                "    return fee(price) + fee(price, 3)\n"
            ),
            "b.py": (
                "from a import fee\n"
                "\n"
                "y = fee(7, rate=4)\n"
            ),
        },
        "fee",
    )
    assert blockers == []
    assert defined_in == "a.py"
    assert new_contents["a.py"] == (
        "RATE = 2\n"
        "\n"
        "\n"
        "def total(price):\n"
        "    return ((price) * (RATE)) + ((price) * (3))\n"
    )
    assert new_contents["b.py"] == (
        "from a import fee\n"
        "\n"
        "y = ((7) * (4))\n"
    )
    assert edits == {"a.py": 3, "b.py": 1}


def test_plan_inline_characterization_blocked_plan(tmp_path):
    """A blocked plan (side-effect duplication) leaves new_contents empty and
    pins the exact blocker text — the early-return decomposition is verbatim."""
    defined_in, blockers, new_contents, edits = _pin(
        tmp_path,
        {"m.py": "def twice(x):\n    return x + x\n\nz = twice(make())\n"},
        "twice",
    )
    assert defined_in == "m.py"
    assert new_contents == {}
    assert edits == {}
    assert blockers == [
        "m.py:4: parameter 'x' is used 2 times and its argument isn't a pure "
        "simple expression — inlining would duplicate a side-effecting evaluation"
    ]


def test_inline_cross_file_default_reads_defining_module_source(tmp_path):
    """A cross-file call that FALLS BACK to a parameter default must splice the
    default's TEXT from the DEFINING module, not the (shorter) call file.

    Regression: ``defs.py`` is longer than ``use.py``; the default ``y=2`` sits on
    a line beyond ``use.py``'s length. Reading the default segment against the call
    file produced an empty (or crashing) splice ``r = ((10) + ())``; reading it
    against the defining module yields the correct ``r = ((10) + (2))``."""
    defined_in, blockers, new_contents, edits = _pin(
        tmp_path,
        {
            "defs.py": (
                "PAD = 0\n"
                "\n"
                "\n"
                "def fee(x, y=2):\n"
                "    return x + y\n"
            ),
            "use.py": "r = fee(10)\n",
        },
        "fee",
    )
    assert blockers == []
    assert defined_in == "defs.py"
    # The default `2` is spliced verbatim — never empty, never a parse error.
    assert new_contents["use.py"] == "r = ((10) + (2))\n"
    assert "def fee" not in new_contents["defs.py"]
    assert edits == {"defs.py": 1, "use.py": 1}


def test_inline_same_module_default_still_byte_identical(tmp_path):
    """The same-module default path is unchanged: defining source == call source,
    so the default splice is byte-identical to before the cross-file fix."""
    defined_in, blockers, new_contents, edits = _pin(
        tmp_path,
        {"m.py": "def fee(x, y=9):\n    return x + y\n\nz = fee(1)\n"},
        "fee",
    )
    assert blockers == []
    assert defined_in == "m.py"
    assert new_contents["m.py"] == "z = ((1) + (9))\n"
