"""Tests for the near-dup family's SECOND control-flow rung:
``plan_near_dup_total_return`` — parameterize an ALWAYS-RETURNING near-duplicate
group into one shared returning helper.

Layout mirrors ``tests/test_near_dup_extract.py`` (the sibling lane) and
``tests/test_objective_dedup_total_return.py:44-88`` (the objective style):
every positive case asserts the result RE-PARSES and is EXEC-EQUIVALENT to the
original across several inputs, and every unsafe shape is asserted to BLOCK
with empty ``new_contents`` (blocker substring pinned). The group always comes
through the real detector (``find_near_duplicates``) except where the fixture
is deliberately hand-built (H4, staleness-adjacent shapes) — noted inline.

W99a shipped-bug closures exercised here: H-A (a differing free NAME read
after an in-run mutation would be evaluated EAGERLY at the call site — now
refused outright by the Constant-only gate) and H-B (a run binding local
``p0`` used to collide with the neutral fallback name — the widened seed now
skips it, landing a positive with ``p1``).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.near_dup import NearDuplicateGroup, find_near_duplicates
from app.execution.near_dup_total_return import plan_near_dup_total_return


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _exec_module(source: str) -> dict:
    ns: dict = {}
    exec(compile(source, "<mod>", "exec"), ns)  # noqa: S102 - controlled test src
    return ns


def _only_group(root: Path, **kw) -> NearDuplicateGroup:
    kw.setdefault("min_statements", 5)
    kw.setdefault("min_occurrences", 2)
    groups = find_near_duplicates(root, **kw)
    assert len(groups) == 1, f"expected exactly one near-dup group, got {groups}"
    return groups[0]


def _group_at(groups: list[NearDuplicateGroup], *locs: str) -> NearDuplicateGroup:
    want = sorted(locs)
    for g in groups:
        if list(g.occurrences) == want:
            return g
    raise AssertionError(f"no group at {want}; got {[g.occurrences for g in groups]}")


# ══════════════════════════════════════════════════════════════════════════
# POSITIVES — exec-equivalence on ≥3 inputs, byte-level helper/call-line pins.
# ══════════════════════════════════════════════════════════════════════════

# ── 1. flagship: guard return + tail return, one constant diff (the SAME
# fixture as tests/test_near_dup_extract.py:313-330, verbatim) ──

_EARLY_RETURN = '''\
def alpha(n):
    a = n + 1
    if a > 5:
        return a
    b = a * 2
    c = b + 10
    return c


def beta(n):
    a = n + 1
    if a > 5:
        return a
    b = a * 2
    c = b + 20
    return c
'''


def test_early_return_flagship_extracts(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _EARLY_RETURN)
    group = _only_group(tmp_path)
    assert group.diff_count == 1
    assert sorted(group.differences[0]) == ["10", "20"]

    plan = plan_near_dup_total_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    assert plan.old == "near_dup_total_return"

    helper = plan.new
    new_src = plan.new_contents["pkg/mod.py"]
    ast.parse(new_src)
    # Guard stays intact inside the helper; call sites RETURN the helper.
    assert "if a > 5:" in new_src and "return a" in new_src
    assert f"return {helper}(n, 10)" in new_src
    assert f"return {helper}(n, 20)" in new_src

    before = _exec_module(_EARLY_RETURN)
    after = _exec_module(new_src)
    for n in (-3, 0, 5, 6, 20):
        assert after["alpha"](n) == before["alpha"](n)
        assert after["beta"](n) == before["beta"](n)


# ── 2. if/else BOTH branches return, a string diff ──

_IFELSE_A = '''\
def alpha(n):
    a = n + 1
    b = a * 2
    c = b + 1
    d = c - 1
    if d > 0:
        return "pos"
    else:
        return "neg"
'''

_IFELSE_B = '''\
def beta(n):
    a = n + 1
    b = a * 2
    c = b + 1
    d = c - 1
    if d > 0:
        return "positive"
    else:
        return "neg"
'''


def test_if_else_both_return_string_diff(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _IFELSE_A + "\n\n" + _IFELSE_B)
    group = _only_group(tmp_path)
    assert group.diff_count == 1

    plan = plan_near_dup_total_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]
    ast.parse(new_src)
    helper = plan.new
    assert f"{helper}(n, \"pos\")" in new_src
    assert f"{helper}(n, \"positive\")" in new_src
    assert '"neg"' in new_src  # the shared branch survives verbatim

    before = _exec_module(_IFELSE_A + "\n\n" + _IFELSE_B)
    after = _exec_module(new_src)
    for n in (-5, 0, 1, 8):
        assert after["alpha"](n) == before["alpha"](n)
        assert after["beta"](n) == before["beta"](n)


# ── 3. TWO differing constants ──

_TWO_DIFFS_A = '''\
def alpha(n, flag):
    if flag:
        return -1
    a = n + 5
    b = a * 2
    c = b + 10
    return c
'''

_TWO_DIFFS_B = '''\
def beta(n, flag):
    if flag:
        return -1
    a = n + 7
    b = a * 2
    c = b + 20
    return c
'''


def test_two_constant_diffs(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _TWO_DIFFS_A + "\n\n" + _TWO_DIFFS_B)
    group = _only_group(tmp_path)
    assert group.diff_count == 2

    plan = plan_near_dup_total_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]
    helper = plan.new
    assert f"{helper}(flag, n, 5, 10)" in new_src
    assert f"{helper}(flag, n, 7, 20)" in new_src

    before = _exec_module(_TWO_DIFFS_A + "\n\n" + _TWO_DIFFS_B)
    after = _exec_module(new_src)
    for n, flag in ((-2, False), (0, True), (11, False)):
        assert after["alpha"](n, flag) == before["alpha"](n, flag)
        assert after["beta"](n, flag) == before["beta"](n, flag)


# ── 4. three occurrences, one constant diff ──

_THREE_A = '''\
def alpha(n, flag):
    if flag:
        return -1
    a = n + 1
    b = a * 2
    c = b + 10
    return c
'''

_THREE_B = '''\
def beta(n, flag):
    if flag:
        return -1
    a = n + 1
    b = a * 2
    c = b + 20
    return c
'''

_THREE_C = '''\
def gamma(n, flag):
    if flag:
        return -1
    a = n + 1
    b = a * 2
    c = b + 30
    return c
'''


def test_three_occurrences_one_diff(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/a.py", _THREE_A)
    _write(tmp_path, "pkg/b.py", _THREE_B)
    _write(tmp_path, "pkg/c.py", _THREE_C)
    _write(tmp_path, "pkg/__init__.py", "")

    group = _only_group(tmp_path, min_occurrences=3)
    assert len(group.occurrences) == 3

    plan = plan_near_dup_total_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    all_src = "".join(plan.new_contents.values())
    helper = plan.new
    for const in ("10", "20", "30"):
        assert f"{helper}(flag, n, {const})" in all_src

    for src in plan.new_contents.values():
        ast.parse(src)


# ── 5. cross-file group: import line + per-site constant args ──

_CF_A = '''\
def alpha(n, flag):
    if flag:
        return -1
    a = n + 1
    b = a * 2
    c = b + 10
    return c
'''

_CF_B = '''\
def beta(n, flag):
    if flag:
        return -1
    a = n + 1
    b = a * 2
    c = b + 20
    return c
'''


def test_cross_file_group_import_and_call_args(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/a.py", _CF_A)
    _write(tmp_path, "pkg/b.py", _CF_B)
    _write(tmp_path, "pkg/__init__.py", "")

    group = _only_group(tmp_path)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"

    helper = plan.new
    first = plan.defined_in
    first_src = plan.new_contents[first]
    other = next(r for r in plan.new_contents if r != first)
    other_src = plan.new_contents[other]

    assert f"def {helper}(" in first_src
    assert f"return {helper}(flag, n, 10)" in first_src
    assert f"import {helper}" in other_src
    assert f"return {helper}(flag, n, 20)" in other_src
    assert f"def {helper}(" not in other_src

    for src in plan.new_contents.values():
        ast.parse(src)

    before_a = _exec_module(_CF_A)
    before_b = _exec_module(_CF_B)
    after_first = _exec_module(first_src)
    for n, flag in ((-7, False), (0, True), (10, False)):
        assert after_first["alpha"](n, flag) == before_a["alpha"](n, flag)
        assert after_first[helper](flag, n, 20) == before_b["beta"](n, flag)


# ── 6. regression (H4): same-file copy ABOVE the first-in-emit-order container ──

_ABOVE_CONTAINER = '''\
def bar(x, flag):
    if flag:
        return -1
    a = x + 1
    b = a * 2
    c = b + 100
    return c


def foo(x, flag):
    if flag:
        return -1
    a = x + 1
    b = a * 2
    c = b + 5
    return c
'''


def test_same_file_copy_above_container_inserts_helper_at_module_level(
        tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _ABOVE_CONTAINER)
    # bar's body starts at line 2 (topmost); foo's at line 11 (bottom). Hand the
    # planner emit order [foo, bar] so `first = resolved[0]` is the BOTTOM
    # function (mirrors test_near_dup_extract.py's H4 regression exactly).
    group = NearDuplicateGroup(occurrences=["mod.py:11", "mod.py:2"], lines=5,
                               diff_count=1, differences=[["5", "100"]])
    plan = plan_near_dup_total_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]

    tree = ast.parse(new_src)
    helper = plan.new
    top_defs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert helper in top_defs, (
        f"helper must be top-level, not nested; module defs={top_defs}\n{new_src}")
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef):
            assert not any(isinstance(n, ast.FunctionDef)
                           for n in ast.walk(fn) if n is not fn)

    before = _exec_module(_ABOVE_CONTAINER)
    after = _exec_module(new_src)
    for x, flag in ((-5, False), (0, True), (10, False), (33, False)):
        assert before["foo"](x, flag) == after["foo"](x, flag)
        assert before["bar"](x, flag) == after["bar"](x, flag)


# ── 7. UnaryOp negative constants — the Constant is the magnitude, USub stays
# part of the template ──

_UNARY_A = '''\
def alpha(n, flag):
    if flag:
        return -1
    a = n + 1
    b = a * 2
    c = b + 1
    return c
'''

_UNARY_B = '''\
def beta(n, flag):
    if flag:
        return -2
    a = n + 1
    b = a * 2
    c = b + 1
    return c
'''


def test_unary_negative_constants(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _UNARY_A + "\n\n" + _UNARY_B)
    group = _only_group(tmp_path)
    assert group.diff_count == 1

    plan = plan_near_dup_total_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]
    helper = plan.new
    assert "return -p0" in new_src
    assert f"{helper}(flag, n, 1)" in new_src
    assert f"{helper}(flag, n, 2)" in new_src

    before = _exec_module(_UNARY_A + "\n\n" + _UNARY_B)
    after = _exec_module(new_src)
    for n in (-4, 0, 6):
        for flag in (True, False):
            assert after["alpha"](n, flag) == before["alpha"](n, flag)
            assert after["beta"](n, flag) == before["beta"](n, flag)


# ── 8. bytes/str cross-type column ──

_BYTES_A = '''\
def alpha(n, flag):
    if flag:
        return b"A"
    a = n + 1
    b = a * 2
    c = b + 1
    return c
'''

_BYTES_B = '''\
def beta(n, flag):
    if flag:
        return "A"
    a = n + 1
    b = a * 2
    c = b + 1
    return c
'''


def test_bytes_str_cross_type_column(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _BYTES_A + "\n\n" + _BYTES_B)
    group = _only_group(tmp_path)
    assert group.diff_count == 1

    plan = plan_near_dup_total_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]
    helper = plan.new
    assert f'{helper}(flag, n, b"A")' in new_src
    assert f'{helper}(flag, n, "A")' in new_src

    before = _exec_module(_BYTES_A + "\n\n" + _BYTES_B)
    after = _exec_module(new_src)
    assert after["alpha"](3, True) == before["alpha"](3, True) == b"A"
    assert after["beta"](3, True) == before["beta"](3, True) == "A"
    assert after["alpha"](3, False) == before["alpha"](3, False)


# ── 9. tuple element diff — two holes on one line, right-to-left splice ──

_TUPLE_A = '''\
def alpha(n, flag):
    if flag:
        return (1, 2)
    a = n + 1
    b = a * 2
    c = b + 1
    return c
'''

_TUPLE_B = '''\
def beta(n, flag):
    if flag:
        return (3, 4)
    a = n + 1
    b = a * 2
    c = b + 1
    return c
'''


def test_tuple_element_diff_two_holes_one_line(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _TUPLE_A + "\n\n" + _TUPLE_B)
    group = _only_group(tmp_path)
    assert group.diff_count == 2

    plan = plan_near_dup_total_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]
    helper = plan.new
    assert "return (p0, p1)" in new_src
    assert f"{helper}(flag, n, 1, 2)" in new_src
    assert f"{helper}(flag, n, 3, 4)" in new_src

    before = _exec_module(_TUPLE_A + "\n\n" + _TUPLE_B)
    after = _exec_module(new_src)
    assert after["alpha"](3, True) == before["alpha"](3, True) == (1, 2)
    assert after["beta"](3, True) == before["beta"](3, True) == (3, 4)


# ── 10. H-B (SHIPPED bug, closed this wave): a run-local named `p0` must not
# collide with the fallback param — positive, green after the widened seed ──

_HB_A = '''\
def alpha(n, flag):
    if flag:
        return -1
    p0 = n + 1
    b = p0 * 2
    c = b + 10
    return c
'''

_HB_B = '''\
def beta(n, flag):
    if flag:
        return -1
    p0 = n + 1
    b = p0 * 2
    c = b + 20
    return c
'''


def test_param_seed_avoids_run_local_p0_h_b_fix(tmp_path: Path) -> None:
    # H-B: the OLD fallback seed was `set(live_in)` only, missing names the
    # run binds ITSELF — a run binding local `p0` got a helper param ALSO
    # named `p0`, silently shadowing the argument (probe-confirmed silent
    # wrong value on the sibling lane). The widened seed now skips `p0`.
    _write(tmp_path, "pkg/mod.py", _HB_A + "\n\n" + _HB_B)
    group = _only_group(tmp_path)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]
    helper = plan.new
    assert f"def {helper}(flag, n, p1):" in new_src
    assert "p0 = n + 1" in new_src  # the run's own local survives untouched

    before = _exec_module(_HB_A + "\n\n" + _HB_B)
    after = _exec_module(new_src)
    for n in (-3, 0, 3, 17):
        assert after["alpha"](n, False) == before["alpha"](n, False)
        assert after[helper](False, n, 20) == before["beta"](n, False)


# ══════════════════════════════════════════════════════════════════════════
# REFUSALS — one per rail, blocker substring pinned.
# ══════════════════════════════════════════════════════════════════════════

# ── routing complement: a plain/tail-return block is dedup-parameterized's job ──

_PLAIN_TAIL = '''\
def alpha(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 10
    return d


def beta(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 20
    return d
'''


def test_routing_complement_refuses_plain_tail_block(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _PLAIN_TAIL)
    group = _only_group(tmp_path)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("that is dedup-parameterized's job" in b for b in plan.blockers)


# ── Name hole: Constant-only gate (W99c defers Name holes) ──

_NAME_HOLE = '''\
G = 100
H = 200


def alpha(n, flag):
    if flag:
        return -1
    base = n + 1
    a = base + 1
    b = a + G
    return b


def beta(n, flag):
    if flag:
        return -1
    base = n + 1
    a = base + 1
    b = a + H
    return b
'''


def test_name_hole_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _NAME_HOLE)
    group = _only_group(tmp_path)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("only constant holes are parameterized" in b for b in plan.blockers)


# ── H-A (SHIPPED bug, closed this wave): eager-eval free-name hole ──

_HA_EAGER = '''\
G = 1
H = 1


def bump():
    global G, H
    G = 99
    H = 99


def alpha(n, flag):
    if flag:
        return -1
    a = n + 1
    bump()
    b = a + G
    return b


def beta(n, flag):
    if flag:
        return -1
    a = n + 1
    bump()
    b = a + H
    return b
'''


def test_eager_eval_free_name_hole_blocks_h_a(tmp_path: Path) -> None:
    # H-A: a differing FREE name read AFTER an in-run mutation (`bump()`)
    # would, if parameterized, be evaluated EAGERLY at the CALL site (before
    # the run's own `bump()` executes) — a silent wrong value. The
    # Constant-only gate refuses ANY Name hole, closing the whole class.
    _write(tmp_path, "pkg/mod.py", _HA_EAGER)
    group = _only_group(tmp_path)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("only constant holes are parameterized" in b for b in plan.blockers)


# ── f-string hole ──

_FSTRING = '''\
def alpha(x, flag):
    if flag:
        return -1
    a = x + 1
    b = f"red {a}"
    c = b + "!"
    return c


def beta(x, flag):
    if flag:
        return -1
    a = x + 1
    b = f"blue {a}"
    c = b + "!"
    return c
'''


def test_fstring_diff_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _FSTRING)
    group = _only_group(tmp_path)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("inside an f-string" in b for b in plan.blockers)


# ── f-string nested format-spec hole ──

_FSTRING_SPEC = '''\
def alpha(n, flag):
    if flag:
        return -1
    a = n + 1
    b = a * 2
    s = f"{b:{5}}"
    return s


def beta(n, flag):
    if flag:
        return -1
    a = n + 1
    b = a * 2
    s = f"{b:{7}}"
    return s
'''


def test_fstring_nested_format_spec_diff_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _FSTRING_SPEC)
    group = _only_group(tmp_path)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("inside an f-string" in b for b in plan.blockers)


# ── annotation hole ──

_ANNOTATION = '''\
def alpha(n, flag):
    if flag:
        return -1
    a = n + 1
    b = a * 2
    x: int = b + 1
    return x


def beta(n, flag):
    if flag:
        return -1
    a = n + 1
    b = a * 2
    x: str = b + 1
    return x
'''


def test_annotation_diff_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _ANNOTATION)
    group = _only_group(tmp_path)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("sits inside an annotation" in b for b in plan.blockers)


# ── docstring-position total-return run ──

_DOC_POSITION = '''\
def alpha(n, flag):
    """Compute A."""
    if flag:
        return -1
    a = n + 1
    b = a * 2
    return b


def beta(n, flag):
    """Compute B."""
    if flag:
        return -1
    a = n + 1
    b = a * 2
    return b
'''


def test_docstring_position_run_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _DOC_POSITION)
    group = _only_group(tmp_path)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("starts at the enclosing function's docstring" in b
              for b in plan.blockers)


# ── multi-line differing str in a NON-first occurrence (family rail) ──

_MLSTR_NONFIRST = '''\
def alpha(x, flag):
    if flag:
        return "one-line"
    a = x + 1
    b = a * 2
    c = b + 1
    return c


def beta(x, flag):
    if flag:
        return """multi
line"""
    a = x + 1
    b = a * 2
    c = b + 1
    return c
'''


def test_multiline_str_nonfirst_occurrence_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _MLSTR_NONFIRST)
    group = _only_group(tmp_path)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("multi-line string constant" in b for b in plan.blockers)


# ── overlap: self-overlapping periodic total-return body ──

_OVERLAP_TOTAL_RETURN = '''\
def f(x):
    return 1
    return 1
    return 1
    return 1
    return 1
    return 2
'''


def test_overlap_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _OVERLAP_TOTAL_RETURN)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    group = _group_at(groups, "mod.py:2", "mod.py:3")
    plan = plan_near_dup_total_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("overlap" in b for b in plan.blockers)


# ── template drift: the group goes stale between build and plan ──

_DRIFT_BASE = (
    "def f1(x, flag):\n"
    "    if flag:\n"
    "        return -1\n"
    "    a = x + 1\n"
    "    b = a - 3\n"
    "    d = b + 7\n"
    "    return d\n"
    "\n\n"
    "def f2(x, flag):\n"
    "    if flag:\n"
    "        return -1\n"
    "    a = x + 1\n"
    "    b = a - 3\n"
    "    d = b + 8\n"
    "    return d\n"
)
# Operator-only drift in f2: `d = b + 8` -> `d = b * 8` (value-leaf paths and
# segments stay identical — the leaf walk never visits operator nodes — so
# only the re-derived structural TEMPLATE catches this).
_DRIFT_STALE = _DRIFT_BASE.replace("d = b + 8\n    return d",
                                   "d = b * 8\n    return d")


def test_template_drift_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "m.py", _DRIFT_BASE)
    groups = find_near_duplicates(tmp_path, min_statements=5)
    group = _group_at(groups, "m.py:2", "m.py:11")
    # The file drifts AFTER the group was built.
    _write(tmp_path, "m.py", _DRIFT_STALE)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("no longer share one structural template" in b
              for b in plan.blockers)


# ── global-decl store variant on the new lane + negative control ──

_GLOBAL_STORE = '''\
G = 0


def probe():
    return G


def alpha(x, flag):
    global G
    if flag:
        return -1
    G = x + 1
    r = probe() + 10
    return r


def beta(x, flag):
    global G
    if flag:
        return -1
    G = x + 1
    r = probe() + 20
    return r
'''


def test_global_declared_store_variant_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _GLOBAL_STORE)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    group = _group_at(groups, "mod.py:10", "mod.py:19")
    plan = plan_near_dup_total_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("declares `G` global/nonlocal" in b and "binds or reads it" in b
              for b in plan.blockers)


_GLOBAL_UNTOUCHED = '''\
def alpha(x, flag):
    global G
    if flag:
        return -1
    r = x + 10
    s = r + 1
    return s


def beta(x, flag):
    global G
    if flag:
        return -1
    r = x + 20
    s = r + 1
    return s
'''


def test_global_decl_negative_control_untouched_run_lands(tmp_path: Path) -> None:
    # Negative control: the enclosing functions DO declare `global G`, but the
    # window itself (excluding the declaration and the guard) neither binds
    # nor reads G — still lands, exec-equivalent.
    _write(tmp_path, "mod.py", _GLOBAL_UNTOUCHED)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    group = _group_at(groups, "mod.py:12", "mod.py:3")
    plan = plan_near_dup_total_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    before = _exec_module(_GLOBAL_UNTOUCHED)
    after = _exec_module(new_src)
    for x, flag in ((1, False), (5, False)):
        assert after["alpha"](x, flag) == before["alpha"](x, flag)
        assert after["beta"](x, flag) == before["beta"](x, flag)


# ── not-always-returns: an early return with a NON-returning tail — neither
# dedup-parameterized's job nor total-return ──

_NOT_ALWAYS_RETURNS = '''\
def alpha(n, sink):
    a = n + 1
    if a > 5:
        return a
    b = a * 2
    c = b + 1
    sink.append(c + 10)


def beta(n, sink):
    a = n + 1
    if a > 5:
        return a
    b = a * 2
    c = b + 1
    sink.append(c + 20)
'''


def test_not_always_returns_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _NOT_ALWAYS_RETURNS)
    group = _only_group(tmp_path)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("does not always return" in b for b in plan.blockers)


# ══════════════════════════════════════════════════════════════════════════
# ROBUSTNESS — malformed inputs, determinism, gate-clean imports.
# ══════════════════════════════════════════════════════════════════════════

def test_fewer_than_two_occurrences_blocks(tmp_path: Path) -> None:
    g = NearDuplicateGroup(occurrences=["pkg/mod.py:1"], lines=5, diff_count=1,
                           differences=[["10"]])
    plan = plan_near_dup_total_return(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents
    assert any("two occurrences" in b for b in plan.blockers)


def test_zero_statements_blocks(tmp_path: Path) -> None:
    g = NearDuplicateGroup(occurrences=["pkg/a.py:1", "pkg/b.py:1"], lines=0,
                           diff_count=1, differences=[["1", "2"]])
    plan = plan_near_dup_total_return(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents
    assert any("no statements" in b for b in plan.blockers)


def test_malformed_occurrence_locations_block(tmp_path: Path) -> None:
    g = NearDuplicateGroup(occurrences=["no-colon", "also/bad"], lines=5,
                           diff_count=1, differences=[["1", "2"]])
    plan = plan_near_dup_total_return(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents


def test_unreadable_module_blocks(tmp_path: Path) -> None:
    g = NearDuplicateGroup(occurrences=["gone.py:2", "gone2.py:2"], lines=5,
                           diff_count=1, differences=[["1", "2"]])
    plan = plan_near_dup_total_return(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents
    assert any("cannot read" in b for b in plan.blockers)


def test_determinism_two_runs_byte_identical(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _EARLY_RETURN)
    group = _only_group(tmp_path)
    p1 = plan_near_dup_total_return(tmp_path, group)
    p2 = plan_near_dup_total_return(tmp_path, group)
    assert p1.ok and p2.ok
    assert p1.new == p2.new
    assert p1.new_contents == p2.new_contents
    assert p1.blockers == p2.blockers


# ── gate-clean: an import used by the lifted block stays live (same-module) ──

_IMPORT_SAME_MODULE = '''\
import math


def alpha(n, flag):
    if flag:
        return -1
    a = math.floor(n)
    b = a * 2
    c = b + 10
    return c


def beta(n, flag):
    if flag:
        return -1
    a = math.floor(n)
    b = a * 2
    c = b + 20
    return c
'''


def test_gate_clean_import_used_by_block_stays_live(tmp_path: Path) -> None:
    # A cross-file group reading a free import name is refused by the family
    # rail (_cross_module_rebind_blocker — see test_dedup_gateclean.py's own
    # precedent: that shape is no longer reachable post-W97 rails). The
    # reachable, honest proof is the SAME-MODULE lift: the helper lands
    # BESIDE the import it uses, so the import stays referenced (never
    # stranded) and the module is gate-clean (no F401).
    from app.execution.unused_imports import strip_unused_imports

    _write(tmp_path, "mod.py", _IMPORT_SAME_MODULE)
    group = _only_group(tmp_path)
    plan = plan_near_dup_total_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    ast.parse(new_src)
    assert strip_unused_imports(new_src) is None
    assert "import math" in new_src
    assert "math.floor" in new_src
