"""Mutation-hardening tests for the dedup/near-dup execution transforms.

This suite is a "never fakes green" moat for three modules:

  * ``app/execution/dedup_extract.py``       (already 100% mutation-killed)
  * ``app/execution/dedup_total_return.py``  (already 100% mutation-killed)
  * ``app/execution/near_dup_extract.py``    (the survivors are killed here)

It targets the SURVIVING mutants the existing suites left alive — overwhelmingly
in ``near_dup_extract``'s pure helpers (segment rendering, affix-token param
naming, hole splicing, the value-leaf gate) and its shape/blocker branches. Each
test pins ONE behaviour with a deterministic, value-level assertion so a seeded
single-token fault flips a real assertion rather than slipping through.

Determinism only: no timestamps, wall-clock, randomness, or unordered iteration
order is asserted on. Pure helpers are exercised directly; integration cases come
through the real detector or a hand-built group with a documented layout.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.near_dup import NearDuplicateGroup, find_near_duplicates
from app.execution.cross_file_rename import RenamePlan
from app.execution.dedup_extract import _Occurrence
from app.execution.near_dup_extract import (
    _apply_line_holes,
    _call_line,
    _common_affix_token,
    _gate_value_holes,
    _hole_edit,
    _hole_param_names,
    _segment,
    _validate_group_shape,
    plan_near_dup_extract,
)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _exec_module(source: str) -> dict:
    ns: dict = {}
    exec(compile(source, "<mod>", "exec"), ns)  # noqa: S102 - controlled test src
    return ns


def _load_name(ident: str) -> ast.Name:
    return ast.Name(id=ident, ctx=ast.Load())


class _Group:
    """A minimal duck-typed near-dup group for ``_validate_group_shape`` tests.

    Only the attributes explicitly passed exist, so a MISSING attribute exercises
    the ``getattr(..., default)`` branches (which seeded faults flip)."""

    def __init__(self, **fields) -> None:
        self.__dict__.update(fields)


# ──────────────────────────────────────────────────────────────────────────
# _segment — source-segment rendering with the three concrete fallbacks.
# A node carrying no position in ``source`` falls back per node kind; the
# return:value>None mutants on each fallback line die here.
# ──────────────────────────────────────────────────────────────────────────

def test_segment_constant_fallback_is_repr_of_value():
    # No source segment available -> the Constant branch returns repr(value).
    assert _segment("", ast.Constant(value=42)) == "42"


def test_segment_name_fallback_is_the_identifier():
    assert _segment("", _load_name("foo")) == "foo"


def test_segment_other_node_fallback_is_the_type_name():
    # A node that is neither Constant nor Name renders as its class name.
    assert _segment("", ast.Pass()) == "Pass"


def test_segment_prefers_real_source_segment_when_present():
    src = "x = 10 + 20\n"
    const = next(n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Constant) and n.value == 20)
    assert _segment(src, const) == "20"


# ──────────────────────────────────────────────────────────────────────────
# _common_affix_token — shared suffix/prefix token, with the reject gates.
# ──────────────────────────────────────────────────────────────────────────

def test_common_affix_token_shared_suffix_wins():
    # Patch|Semantic + Generator -> the shared LAST token "generator".
    assert _common_affix_token(["PatchGenerator", "SemanticGenerator"]) == "generator"


def test_common_affix_token_shared_prefix_when_no_common_suffix():
    # alpha_run / alpha_jump share the FIRST token but not the last.
    assert _common_affix_token(["alpha_run", "alpha_jump"]) == "alpha"


def test_common_affix_token_no_shared_affix_is_none():
    assert _common_affix_token(["alpha", "beta"]) is None


def test_common_affix_token_fewer_than_two_is_none():
    # The `len(names) < 2` guard: a single value never names a param.
    assert _common_affix_token(["solo"]) is None


def test_common_affix_token_empty_token_list_is_none():
    # A value with no usable tokens (just an underscore) -> None.
    assert _common_affix_token(["_", "beta_gen"]) is None


def test_common_affix_token_keyword_base_rejected():
    # class_for / x_for share the suffix token "for", which is a keyword -> None.
    assert _common_affix_token(["class_for", "x_for"]) is None


# ──────────────────────────────────────────────────────────────────────────
# _hole_param_names — descriptive names, collision suffixing, p<n> fallback.
# ──────────────────────────────────────────────────────────────────────────

def test_hole_param_names_descriptive_from_shared_name_affix():
    col = [(_load_name("PatchGenerator"), "PatchGenerator"),
           (_load_name("SemanticGenerator"), "SemanticGenerator")]
    assert _hole_param_names([col], []) == ["generator"]


def test_hole_param_names_collision_with_live_in_appends_suffix():
    col = [(_load_name("PatchGenerator"), "x"),
           (_load_name("SemanticGenerator"), "y")]
    # `generator` is already a live_in param -> generator_2 (the `range(2, 100)` loop).
    assert _hole_param_names([col], ["generator"]) == ["generator_2"]


def test_hole_param_names_two_descriptive_columns_dedup_via_suffix():
    col = [(_load_name("PatchGenerator"), "x"),
           (_load_name("SemanticGenerator"), "y")]
    # Both columns want "generator"; the second is suffixed -> generator_2.
    assert _hole_param_names([col, col], []) == ["generator", "generator_2"]


def test_hole_param_names_constant_columns_use_neutral_fallback():
    col = [(ast.Constant(1), "1"), (ast.Constant(2), "2")]
    assert _hole_param_names([col], []) == ["p0"]


def test_hole_param_names_fallback_skips_taken_p_names():
    col = [(ast.Constant(1), "1"), (ast.Constant(2), "2")]
    # p0 already taken by live_in -> the fallback advances to p1.
    assert _hole_param_names([col], ["p0"]) == ["p1"]


def test_hole_param_names_mixed_columns_preserve_order():
    name_col = [(_load_name("PatchGenerator"), "x"),
                (_load_name("SemanticGenerator"), "y")]
    const_col = [(ast.Constant(1), "1"), (ast.Constant(2), "2")]
    assert _hole_param_names([name_col, const_col], []) == ["generator", "p0"]


# ──────────────────────────────────────────────────────────────────────────
# _gate_value_holes — only Constants / loaded Names pass; anything else blocks.
# (Defence-in-depth gate; exercised directly because the detector never feeds
#  it a non-value leaf.)
# ──────────────────────────────────────────────────────────────────────────

def _occ_for_gate() -> _Occurrence:
    src = "def f():\n    x.attr = 1\n"
    return _Occurrence("f.py", src, src.splitlines(keepends=True), None, None,
                       [], [], [], 2, 2, False)


def test_gate_value_holes_passes_constant_and_loaded_name():
    occ = _occ_for_gate()
    leaves = [[("s0", ast.Constant(5))], [("s0", _load_name("g"))]]
    plan = RenamePlan(old="x", new="_s")
    assert _gate_value_holes([occ, occ], leaves, [0], plan) is True
    assert not plan.blockers


def test_gate_value_holes_blocks_attribute_leaf():
    occ = _occ_for_gate()
    attr = ast.Attribute(value=_load_name("x"), attr="a", ctx=ast.Load())
    leaves = [[("s0", ast.Constant(5))], [("s0", attr)]]
    plan = RenamePlan(old="x", new="_s")
    assert _gate_value_holes([occ, occ], leaves, [0], plan) is False
    assert any("not a value" in b for b in plan.blockers)


def test_gate_value_holes_blocks_stored_name():
    # A Name in Store context is NOT a value leaf -> blocks (kills the
    # `and`->`or` mutant that would wrongly accept a stored name).
    occ = _occ_for_gate()
    stored = ast.Name(id="g", ctx=ast.Store())
    leaves = [[("s0", ast.Constant(5))], [("s0", stored)]]
    plan = RenamePlan(old="x", new="_s")
    assert _gate_value_holes([occ, occ], leaves, [0], plan) is False
    assert any("not a value" in b for b in plan.blockers)


# ──────────────────────────────────────────────────────────────────────────
# _call_line — the three call shapes (tail-return / live-out / bare).
# ──────────────────────────────────────────────────────────────────────────

def test_call_line_bare_call_no_live_out_no_tail_return():
    occ = _occ_for_gate()
    line = _call_line(occ, ["1"], "_h", ["x"], [], False, "    ")
    assert line == "    _h(x, 1)\n"


def test_call_line_assigns_live_out():
    occ = _occ_for_gate()
    line = _call_line(occ, ["1"], "_h", ["x"], ["r"], False, "    ")
    assert line == "    r = _h(x, 1)\n"


def test_call_line_tail_return_form():
    occ = _occ_for_gate()
    line = _call_line(occ, ["1"], "_h", ["x"], [], True, "    ")
    assert line == "    return _h(x, 1)\n"


# ──────────────────────────────────────────────────────────────────────────
# _hole_edit — locating one constant span, with each refusal branch.
# ──────────────────────────────────────────────────────────────────────────

def _single_line_occurrence() -> tuple[_Occurrence, ast.Constant]:
    src = "def f():\n    d = c + 10\n    return d\n"
    fn = ast.parse(src).body[0]
    const = next(n for n in ast.walk(fn)
                 if isinstance(n, ast.Constant) and n.value == 10)
    lines = src.splitlines(keepends=True)
    # span is the single statement on line 2 (span_lo == span_hi == 2).
    occ = _Occurrence("f.py", src, lines, fn, fn, fn.body[0:1], [], [], 2, 2,
                      False)
    return occ, const


def test_hole_edit_locates_constant_span():
    occ, const = _single_line_occurrence()
    plan = RenamePlan(old="x", new="_s")
    # span_lo == 2, the constant '10' sits at columns 12..14 of its line.
    assert _hole_edit(occ, const, 1, "p0", plan) == (0, 12, 14, "p0")
    assert not plan.blockers


def test_hole_edit_blocks_when_index_outside_block():
    occ, const = _single_line_occurrence()
    plan = RenamePlan(old="x", new="_s")
    # n_block_lines == 0: idx 0 is NOT < 0 -> falls outside the run -> block.
    # (Kills the `idx < n_block_lines` boundary mutant.)
    assert _hole_edit(occ, const, 0, "p0", plan) is None
    assert any("outside the located run" in b for b in plan.blockers)


def test_hole_edit_blocks_missing_position_info():
    occ, _ = _single_line_occurrence()
    plan = RenamePlan(old="x", new="_s")

    class _NoPos:
        lineno = None
        col_offset = None
        end_lineno = None
        end_col_offset = None

    assert _hole_edit(occ, _NoPos(), 1, "p0", plan) is None
    assert any("lacks position info" in b for b in plan.blockers)


def test_hole_edit_blocks_multiline_span():
    occ, _ = _single_line_occurrence()
    plan = RenamePlan(old="x", new="_s")

    class _MultiLine:
        lineno = 2
        col_offset = 8
        end_lineno = 3
        end_col_offset = 2

    assert _hole_edit(occ, _MultiLine(), 1, "p0", plan) is None
    assert any("spans multiple lines" in b for b in plan.blockers)


# ──────────────────────────────────────────────────────────────────────────
# _apply_line_holes — right-to-left span splicing, with the range gate.
# ──────────────────────────────────────────────────────────────────────────

def test_apply_line_holes_single_hole():
    line = "    d = c + 10\n"
    plan = RenamePlan(old="x", new="_s")
    assert _apply_line_holes(line, [(12, 14, "p0")], plan) == "    d = c + p0\n"


def test_apply_line_holes_two_holes_apply_right_to_left():
    # '11' at 8..10 and '22' at 13..15. Right-to-left keeps the earlier columns
    # valid; left-to-right (the reverse/key mutants) would corrupt the line.
    line = "    x = 11 + 22\n"
    plan = RenamePlan(old="x", new="_s")
    out = _apply_line_holes(line, [(8, 10, "AAAA"), (13, 15, "B")], plan)
    assert out == "    x = AAAA + B\n"


def test_apply_line_holes_end_exactly_at_line_length_is_allowed():
    # c1 == len(line.rstrip("\n")) must NOT be out of range (kills the
    # `c1 > len`->`c1 >= len` boundary mutant on the `>` comparison).
    line = "    y = 99\n"
    plan = RenamePlan(old="x", new="_s")
    assert _apply_line_holes(line, [(8, 10, "Z")], plan) == "    y = Z\n"
    assert not plan.blockers


def test_apply_line_holes_end_past_line_length_blocks():
    line = "    y = 99\n"
    plan = RenamePlan(old="x", new="_s")
    assert _apply_line_holes(line, [(8, 11, "Z")], plan) is None
    assert any("out of range" in b for b in plan.blockers)


def test_apply_line_holes_zero_width_span_blocks():
    # c0 == c1 -> c0 >= c1 -> block (kills the `>=`->`>` mutant).
    line = "    y = 99\n"
    plan = RenamePlan(old="x", new="_s")
    assert _apply_line_holes(line, [(8, 8, "Z")], plan) is None
    assert any("out of range" in b for b in plan.blockers)


def test_apply_line_holes_negative_start_blocks():
    # c0 < 0 -> block (kills the `c0 < 0` boundary/number mutants).
    line = "    y = 99\n"
    plan = RenamePlan(old="x", new="_s")
    assert _apply_line_holes(line, [(-1, 10, "Z")], plan) is None
    assert any("out of range" in b for b in plan.blockers)


def test_apply_line_holes_start_at_column_zero_is_allowed():
    # c0 == 0 is a VALID start. The `c0 < 0` guard must accept it, so the
    # `< 0`->`<= 0` and `< 0`->`< 1` mutants (which would wrongly block) die here.
    line = "99\n"  # '99' occupies columns 0..2
    plan = RenamePlan(old="x", new="_s")
    assert _apply_line_holes(line, [(0, 2, "Z")], plan) == "Z\n"
    assert not plan.blockers


# ──────────────────────────────────────────────────────────────────────────
# _validate_group_shape — the shape gates and their `getattr` defaults.
# ──────────────────────────────────────────────────────────────────────────

def test_validate_group_shape_accepts_minimal_valid_group():
    g = _Group(occurrences=["a:1", "a:2"], lines=1, diff_count=1,
               differences=[["1", "2"]])
    plan = RenamePlan(old="x", new="_s")
    # A ONE-statement group is valid (kills the `n_statements < 1`->`< 2` and
    # `<`->`<=` mutants that would reject it).
    assert _validate_group_shape(g, plan) == (["a:1", "a:2"], 1, 1, [["1", "2"]])


def test_validate_group_shape_zero_statements_blocks():
    g = _Group(occurrences=["a:1", "a:2"], lines=0, diff_count=1,
               differences=[["1", "2"]])
    plan = RenamePlan(old="x", new="_s")
    assert _validate_group_shape(g, plan) is None
    assert any("no statements" in b for b in plan.blockers)


def test_validate_group_shape_missing_lines_defaults_to_block():
    # No `lines` attr -> default 0 -> "no statements" (kills the default `0`->`1`).
    g = _Group(occurrences=["a:1", "a:2"], diff_count=1, differences=[["1", "2"]])
    plan = RenamePlan(old="x", new="_s")
    assert _validate_group_shape(g, plan) is None
    assert any("no statements" in b for b in plan.blockers)


def test_validate_group_shape_zero_diff_count_blocks():
    # diff_count == 0 with non-empty differences -> blocks via `diff_count < 1`
    # (kills the `or`->`and` mutant that would let it through).
    g = _Group(occurrences=["a:1", "a:2"], lines=2, diff_count=0,
               differences=[["1", "2"]])
    plan = RenamePlan(old="x", new="_s")
    assert _validate_group_shape(g, plan) is None
    assert any("zero-diff" in b or "differing position" in b
               for b in plan.blockers)


def test_validate_group_shape_missing_diff_count_defaults_to_block():
    # No `diff_count` attr -> default 0 -> the zero-diff block (kills `0`->`1`).
    g = _Group(occurrences=["a:1", "a:2"], lines=2, differences=[["1", "2"]])
    plan = RenamePlan(old="x", new="_s")
    assert _validate_group_shape(g, plan) is None
    assert any("zero-diff" in b or "differing position" in b
               for b in plan.blockers)


# ──────────────────────────────────────────────────────────────────────────
# Integration: a non-tail bare-block parameterized extraction (no live-out).
# ──────────────────────────────────────────────────────────────────────────

_BARE_BLOCK_A = '''\
def alpha(store):
    a = 1
    b = a + 2
    c = b + 3
    store.append(c + 10)
'''

_BARE_BLOCK_B = '''\
def beta(store):
    a = 1
    b = a + 2
    c = b + 3
    store.append(c + 20)
'''


def test_bare_block_parameterized_extraction_exec_equivalent(tmp_path):
    # The block has no live-out and no tail return -> the call site is a BARE
    # `helper(...)` call (kills the bare-branch return:value>None in _call_line
    # via a real, exec-checked extraction).
    _write(tmp_path, "a.py", _BARE_BLOCK_A)
    _write(tmp_path, "b.py", _BARE_BLOCK_B)
    groups = find_near_duplicates(tmp_path, min_statements=4, min_occurrences=2)
    assert groups, "detector should see the near-duplicate block"
    plan = plan_near_dup_extract(tmp_path, groups[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"

    definer = plan.defined_in
    helper = plan.new
    def_src = plan.new_contents[definer]
    # The call site in the defining module is a bare call (not a return / assign).
    assert f"{helper}(" in def_src
    assert f"return {helper}(" not in def_src
    assert f"= {helper}(" not in def_src

    # Exec-equivalence on the defining module (it carries the helper def): the
    # rewritten function appends the same value to the passed-in list as before.
    fn_name = "alpha" if "def alpha" in def_src else "beta"
    src_before = _BARE_BLOCK_A if fn_name == "alpha" else _BARE_BLOCK_B
    s_before: list = []
    s_after: list = []
    _exec_module(src_before)[fn_name](s_before)
    _exec_module(def_src)[fn_name](s_after)
    assert s_before == s_after == [16]


# ──────────────────────────────────────────────────────────────────────────
# Integration: a METHOD-context block with a nested `if` — the helper must be
# de-indented to module level WITHOUT losing the nested relative indentation.
# This is what pins the `base_indent` arithmetic and the `_reindent` call.
# ──────────────────────────────────────────────────────────────────────────

_METHOD_NESTED = '''\
class C:
    def alpha(self, n):
        a = n + 1
        if a > 5:
            a = a + 10
        b = a * 2
        return b

    def beta(self, n):
        a = n + 1
        if a > 5:
            a = a + 20
        b = a * 2
        return b
'''


def test_method_context_nested_if_keeps_relative_indentation(tmp_path):
    _write(tmp_path, "mod.py", _METHOD_NESTED)
    groups = find_near_duplicates(tmp_path, min_statements=4, min_occurrences=2)
    assert groups, "detector should see the shared method block"
    plan = plan_near_dup_extract(tmp_path, groups[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]

    tree = ast.parse(new_src)  # a wrong base_indent would not re-parse
    helper = plan.new
    helper_def = next(n for n in tree.body
                      if isinstance(n, ast.FunctionDef) and n.name == helper)
    # The nested-if body must still be nested under the `if` inside the helper.
    ifs = [n for n in helper_def.body if isinstance(n, ast.If)]
    assert ifs, "the helper kept the nested if"
    assert any(isinstance(s, ast.Assign) for s in ifs[0].body), \
        "the if-body statement stayed nested under the if (relative indent kept)"

    # Exec-equivalence across both branches of the inner if.
    before = _exec_module(_METHOD_NESTED)
    after = _exec_module(new_src)
    bc, ac = before["C"](), after["C"]()
    for n in (3, 10):
        assert bc.alpha(n) == ac.alpha(n)
        assert bc.beta(n) == ac.beta(n)
    assert ac.alpha(10) == 42  # a=11 -> +10 -> 21 -> *2 = 42
    assert ac.alpha(3) == 8    # a=4 (<=5) -> *2 = 8


# ──────────────────────────────────────────────────────────────────────────
# Integration: same-file copy ABOVE the first-in-emit-order container, with an
# ASYMMETRIC layout (no blank gap, a large topmost block) so a wrong
# helper-insert offset shears the buffer and the emission no longer parses.
# This kills the `1 - (span_hi - span_lo + 1)` number mutant in the rebase.
# ──────────────────────────────────────────────────────────────────────────

_ABOVE_CONTAINER_ASYM = '''\
def bar(x):
    a = x + 1
    b = a + 2
    c = b + 3
    e = c + 4
    f = e + 100
    return f
def foo(x):
    a = x + 1
    b = a + 2
    c = b + 3
    e = c + 4
    f = e + 5
    return f
'''


def test_above_container_asymmetric_helper_stays_module_level(tmp_path):
    _write(tmp_path, "mod.py", _ABOVE_CONTAINER_ASYM)
    # bar's block (a..f) is lines 2-6; foo's is lines 9-13. Emit order
    # [foo, bar] makes `first` the BOTTOM function while bar's copy sits ABOVE
    # it with NO blank gap, so a mis-rebased insert lands the def inside a body
    # or shears statements -> the emission fails to parse and the plan blocks.
    group = NearDuplicateGroup(occurrences=["mod.py:9", "mod.py:2"], lines=5,
                               diff_count=1, differences=[["5", "100"]])
    plan = plan_near_dup_extract(tmp_path, group)
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]

    tree = ast.parse(new_src)
    helper = plan.new
    top_defs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert helper in top_defs, f"helper must be top-level; defs={top_defs}"
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef):
            assert not any(isinstance(n, ast.FunctionDef)
                           for n in ast.walk(fn) if n is not fn), \
                f"a function ended up nested:\n{new_src}"

    before = _exec_module(_ABOVE_CONTAINER_ASYM)
    after = _exec_module(new_src)
    for x in (-3, 0, 10):
        assert before["foo"](x) == after["foo"](x)
        assert before["bar"](x) == after["bar"](x)
    assert after["foo"](10) == 25 and after["bar"](10) == 120


# ──────────────────────────────────────────────────────────────────────────
# Integration: blocker branches of plan_near_dup_extract that returned `plan`.
# Each asserts on the RETURNED object so a `return plan`->`return None` mutant
# raises AttributeError and is killed.
# ──────────────────────────────────────────────────────────────────────────

def test_unreadable_module_blocks_and_returns_plan(tmp_path):
    group = NearDuplicateGroup(occurrences=["missing.py:1", "missing.py:5"],
                               lines=3, diff_count=1, differences=[["1", "2"]])
    plan = plan_near_dup_extract(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("cannot read" in b for b in plan.blockers)


_REDERIVE_MISMATCH = '''\
def bar(x):
    a = x + 1
    b = a * 2
    c = b + 100
    return c


def foo(x):
    a = x + 1
    b = a * 2
    c = b + 5
    return c
'''


def test_diff_report_mismatch_blocks_and_returns_plan(tmp_path):
    _write(tmp_path, "mod.py", _REDERIVE_MISMATCH)
    # The REAL differing values are 5 and 100; we lie and report ["9", "9"], so
    # the re-derived diff disagrees with the report -> the column mapping is
    # unsound -> block (and the function still returns the blocked plan).
    group = NearDuplicateGroup(occurrences=["mod.py:9", "mod.py:2"], lines=3,
                               diff_count=1, differences=[["9", "9"]])
    plan = plan_near_dup_extract(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("disagree" in b or "unsound" in b for b in plan.blockers)


# ──────────────────────────────────────────────────────────────────────────
# Integration: a non-value differing leaf reaching the value-hole gate would be
# rejected — exercised here through a real two-constant group to confirm the
# happy path emits exactly the right number of params (guards the diff scan).
# ──────────────────────────────────────────────────────────────────────────

_TWO_CONST_A = '''\
def alpha(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 10
    return d + 7
'''

_TWO_CONST_B = '''\
def beta(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 20
    return d + 9
'''


def test_two_constant_diffs_yield_two_params_exec_equivalent(tmp_path):
    _write(tmp_path, "a.py", _TWO_CONST_A)
    _write(tmp_path, "b.py", _TWO_CONST_B)
    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert len(groups) == 1
    assert groups[0].diff_count == 2
    plan = plan_near_dup_extract(tmp_path, groups[0])
    assert plan.ok, f"blockers={plan.blockers}"
    helper = plan.new
    def_src = plan.new_contents[plan.defined_in]
    helper_def = next(n for n in ast.parse(def_src).body
                      if isinstance(n, ast.FunctionDef) and n.name == helper)
    # n + two holes (p0, p1) -> three params total.
    assert len(helper_def.args.args) == 3

    after_def = _exec_module(def_src)
    fn = "alpha" if "def alpha" in def_src else "beta"
    src_before = _TWO_CONST_A if fn == "alpha" else _TWO_CONST_B
    ref = _exec_module(src_before)
    for n in (0, 5, 12):
        assert ref[fn](n) == after_def[fn](n)


# ──────────────────────────────────────────────────────────────────────────
# Integration: a block whose FIRST line carries LONG content while a later
# physical line (the nested-if body) carries SHORT content. ``base_indent`` is
# ``len(first_line) - len(first_line.lstrip())``; if the second ``len`` term
# read ``span_lo + 1`` (a `span_lo - 1` -> `span_lo + 1` fault) it would compute
# a hugely inflated indent from the short body line, over-strip the dedent, and
# emit an unparseable helper -> the plan blocks. A clean, exec-equivalent plan
# here therefore pins the base-indent line selection in BOTH ``len`` terms.
# ──────────────────────────────────────────────────────────────────────────

_LONG_FIRST_SHORT_BODY = '''\
def alpha(n):
    accumulated_running_total_value = n + 1
    if accumulated_running_total_value > 5:
        x = n + 10
    z = n + 3
    w = z + 4
    return w


def beta(n):
    accumulated_running_total_value = n + 1
    if accumulated_running_total_value > 5:
        x = n + 20
    z = n + 3
    w = z + 4
    return w
'''


def test_base_indent_measured_from_run_first_line(tmp_path):
    _write(tmp_path, "mod.py", _LONG_FIRST_SHORT_BODY)
    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert groups, "detector should see the shared block"
    plan = plan_near_dup_extract(tmp_path, groups[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]

    tree = ast.parse(new_src)  # an over-stripped helper would not parse
    helper = plan.new
    helper_def = next(n for n in tree.body
                      if isinstance(n, ast.FunctionDef) and n.name == helper)
    # The nested-if body survived inside the if (correct base-indent dedent).
    inner_if = next(n for n in helper_def.body if isinstance(n, ast.If))
    assert any(isinstance(s, ast.Assign) for s in inner_if.body)

    before = _exec_module(_LONG_FIRST_SHORT_BODY)
    after = _exec_module(new_src)
    for n in (3, 10):
        assert before["alpha"](n) == after["alpha"](n)
        assert before["beta"](n) == after["beta"](n)
    assert after["alpha"](10) == 17  # n=10 -> z=13 -> w=17 (the if-body x is unused)
    assert after["alpha"](3) == 10   # n=3 -> z=6 -> w=10


# ──────────────────────────────────────────────────────────────────────────
# Integration: occurrences that DISAGREE on tail-return shape -> BLOCK.
# One block tail-returns (`... ; return b + 10`), the parallel block ends in a
# plain assignment. The tail-return gate must reject them; a `resolved[0]` or
# `resolved[1:]` index fault would miss the disagreement and not block.
# ──────────────────────────────────────────────────────────────────────────

_TAIL_RETURN_DISAGREE = '''\
def alpha(n):
    a = n + 1
    b = a + 2
    return b + 10


def beta(n):
    a = n + 1
    b = a + 2
    c = b + 20
'''


def test_tail_return_shape_disagreement_blocks(tmp_path):
    _write(tmp_path, "mod.py", _TAIL_RETURN_DISAGREE)
    # alpha's 3-stmt run tail-returns; beta's ends in a plain assignment. The
    # constants 10 vs 20 keep the data-flow signature identical, so the only
    # divergence is the tail-return shape -> block.
    group = NearDuplicateGroup(occurrences=["mod.py:2", "mod.py:8"], lines=3,
                               diff_count=1, differences=[["10", "20"]])
    plan = plan_near_dup_extract(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("tail-return" in b for b in plan.blockers)


# ──────────────────────────────────────────────────────────────────────────
# Integration: occurrences whose value-leaf PATHS differ structurally -> BLOCK.
# alpha is `x = 1; y = g(2)`, beta is `x = g(1); y = 2`: same number of value
# leaves, but at different structural positions. ``_paths_match`` must reject
# them; a `per_occ_leaves[0]`/`[1:]` index fault would miss the mismatch.
# ──────────────────────────────────────────────────────────────────────────

_LEAF_PATHS_DIFFER = '''\
def alpha(n):
    x = 1
    y = g(2)
    return x + y


def beta(n):
    x = g(1)
    y = 2
    return x + y
'''


def test_value_leaf_path_mismatch_blocks(tmp_path):
    _write(tmp_path, "mod.py", _LEAF_PATHS_DIFFER)
    group = NearDuplicateGroup(occurrences=["mod.py:2", "mod.py:8"], lines=3,
                               diff_count=1, differences=[["1", "2"]])
    plan = plan_near_dup_extract(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("path" in b for b in plan.blockers)


# ──────────────────────────────────────────────────────────────────────────
# Integration: a MULTI-LINE string constant as the differing leaf cannot be
# spliced (this version refuses multi-line holes) -> _build_helper_block fails
# and the planner returns the BLOCKED plan (pins that blocker branch).
# ──────────────────────────────────────────────────────────────────────────

_MULTILINE_CONST = '''\
def alpha(n):
    a = n + 1
    b = a + 2
    c = b + 3
    d = """one
two"""
    return (a, b, c, d)


def beta(n):
    a = n + 1
    b = a + 2
    c = b + 3
    d = """three
four"""
    return (a, b, c, d)
'''


def test_multiline_constant_hole_blocks_and_returns_plan(tmp_path):
    _write(tmp_path, "mod.py", _MULTILINE_CONST)
    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert groups, "detector should see the near-duplicate block"
    plan = plan_near_dup_extract(tmp_path, groups[0])
    assert not plan.ok
    assert not plan.new_contents
    assert any("multiple lines" in b for b in plan.blockers)
