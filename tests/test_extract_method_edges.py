"""Edge/error-path coverage for extract_method — qualification and rejection
rules, helper internals, and plan re-verification. Deterministic & hermetic."""

from __future__ import annotations

import ast

from app.execution.extract_method import (
    _comp_targets,
    _function_covering,
    _function_param_names,
    _has_unenclosed_jump,
    _iter_closure_free_functions,
    _reindent,
    _selected_statements,
    plan_extract,
    suggest_extractions,
)


def _write(tmp_path, rel, src):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return p


# ── helper internals ──

def test_function_covering_empty_body_returns_none():
    fn = ast.parse("def f(): pass").body[0]
    fn.body = []  # force the empty-body guard (line 65)
    assert _function_covering(fn, 1, 1) is None


def test_selected_statements_excludes_incomplete_multiline_stmt():
    src = ("def f():\n"
           "    a = 1\n"
           "    b = (\n"
           "        2)\n"
           "    c = 3\n")
    fn = ast.parse(src).body[0]
    # Window 2..3 grabs only `a` (b ends at line 4, so it's excluded) — the run
    # stays contiguous, so just `a` is returned.
    chosen = _selected_statements(fn, 2, 3)
    assert [type(s).__name__ for s in chosen] == ["Assign"]
    assert chosen[0].lineno == 2


def test_selected_statements_noncontiguous_slice_rejected():
    # Build a body where the chosen set isn't a contiguous slice: select stmt 0
    # and stmt 2 by a range that excludes the line of stmt 1.
    src = "def f():\n    a = 1\n    b = 2\n    c = 3\n"
    fn = ast.parse(src).body[0]
    # Monkeypatch line numbers so `b` falls outside [2,4] but a and c are inside.
    fn.body[1].lineno = 99
    fn.body[1].end_lineno = 99
    assert _selected_statements(fn, 2, 4) == []  # gap → rejected (line 81)


def test_comp_targets_collects_iteration_vars():
    nodes = ast.parse("[i for i in range(3)]").body
    assert _comp_targets([nodes[0].value]) == {"i"}


def test_function_param_names_includes_vararg_and_kwarg():
    fn = ast.parse("def f(a, *args, **kw): pass").body[0]
    assert _function_param_names(fn) == {"a", "args", "kw"}


def test_has_unenclosed_jump_nested_scope_is_ignored():
    # A break inside a nested def belongs to that def's own loops — not ours.
    node = ast.parse("def inner():\n    for x in y:\n        break\n").body[0]
    assert _has_unenclosed_jump(node) is False


def test_has_unenclosed_jump_true_for_bare_break():
    node = ast.parse("if cond:\n    break\n").body[0]
    assert _has_unenclosed_jump(node) is True


def test_reindent_handles_blank_and_lstrip_fallback():
    # A blank line stays blank; a line with too-little indent falls to lstrip.
    out = _reindent(["        x = 1\n", "\n", "  y = 2\n"], base_indent=8)
    assert out[0] == "    x = 1"
    assert out[1] == ""
    assert out[2] == "    y = 2"


def test_iter_closure_free_functions_yields_methods():
    tree = ast.parse(
        "def top():\n    pass\n\n\nclass C:\n    def m(self):\n        pass\n")
    pairs = list(_iter_closure_free_functions(tree))
    names = {fn.name for fn, _ in pairs}
    assert names == {"top", "m"}
    # The method's container is the class.
    method_pair = [p for p in pairs if p[0].name == "m"][0]
    assert isinstance(method_pair[1], ast.ClassDef)


# ── plan_extract rejection / boundary paths ──

def test_break_in_partial_loop_selection_blocks(tmp_path):
    # Select the inner if (with break) but not its enclosing for → break escapes.
    _write(tmp_path, "m.py",
           "def f(items):\n"
           "    found = None\n"
           "    for it in items:\n"
           "        if it:\n"
           "            found = it\n"
           "            break\n"
           "        found = 0\n"
           "    return found\n")
    # Range 4-6 covers the `if` block at the for's body level — still nested
    # inside the loop, so it can't be a top-level run; force the break path by
    # selecting the if/elif chain that is a complete statement holding a bare
    # break is impossible at body level. Instead select a fabricated tree below.
    src = ("def f(items):\n"
           "    if items:\n"
           "        break\n"
           "    x = 1\n")
    _write(tmp_path, "b.py", src)
    plan = plan_extract(str(tmp_path), "b.py", 2, 3, "_h")
    assert any("break" in b or "continue" in b for b in plan.blockers)
    assert not plan.new_contents


def test_range_splitting_multiline_statement_snaps_to_complete_run(tmp_path):
    # Selecting lines 2-4 cuts the list literal mid-statement; the selection
    # snaps to the only complete statement fully inside (the `a = 1`).
    _write(tmp_path, "m.py",
           "def f(data):\n"
           "    a = 1\n"
           "    b = [\n"
           "        a,\n"
           "    ]\n"
           "    return b\n")
    plan = plan_extract(str(tmp_path), "m.py", 2, 4, "_h")
    # `a = 1` is self-contained: a one-statement extraction with a live-out `a`.
    assert not plan.blockers
    new = plan.new_contents["m.py"]
    assert "def _h():" in new
    assert "a = _h()" in new


def test_extract_no_params_no_returns_warns(tmp_path):
    # A self-contained run (only local temp use) yields a no-arg, void helper.
    _write(tmp_path, "m.py",
           "def f():\n"
           "    print('a')\n"
           "    print('b')\n"
           "    print('c')\n")
    plan = plan_extract(str(tmp_path), "m.py", 2, 4, "_show")
    assert not plan.blockers
    assert any("no parameters and returns" in w for w in plan.warnings)


def test_suggest_extractions_syntax_error_returns_empty():
    assert suggest_extractions("def f(:\n    pass\n") == []


def test_suggest_extractions_accepts_prebuilt_tree():
    body = "\n".join(f"    s{i} = {i}" for i in range(45))
    src = f"def big(start):\n    total = start\n{body}\n    return total\n"
    tree = ast.parse(src)
    assert suggest_extractions(src, tree) == suggest_extractions(src)


def test_suggest_extractions_finds_method_seam():
    body = "\n".join(f"        a{i} = {i}" for i in range(45))
    src = f"class C:\n    def big(self):\n{body}\n        return a0\n"
    sugs = suggest_extractions(src)
    assert any(s["function"] == "big" for s in sugs)
