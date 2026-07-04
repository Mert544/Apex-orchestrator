"""Tests for the near-dup family's THIRD (and final) control-flow rung:
``plan_near_dup_guarded_return`` — parameterize a GUARD-RETURN near-duplicate
group (a guard ``return`` on some path AND a live fall-through) into one
shared, sentinel-projecting helper.

Layout mirrors ``tests/test_near_dup_total_return_eyml.py`` (the sibling
lane) and ``tests/test_dedup_guarded_return.py`` (the exact-dup shape this
lane parameterizes): every positive case asserts the result RE-PARSES and is
EXEC-EQUIVALENT to the original across guard-taken AND fall-through inputs;
every unsafe shape is asserted to BLOCK with empty ``new_contents`` (blocker
substring pinned). The group always comes through the real detector
(``find_near_duplicates``) except where the fixture is deliberately
hand-built (copy-above-container, staleness-adjacent shapes) — noted inline.

Completing the parameterized x {plain, total, guarded} matrix: routing is
disjoint by construction — a clean tail-return run always-returns
(refused as "dedup-total-return's job"); a plain run has no return at all
(refused as "dedup_extract's job") — so no explicit routing gate is coded
here (unlike the total-return sibling's own ``_block_reason`` check).

W99b-fix parity: the family-wide live-in bound-before-run rail (closed as
this wave's prerequisite fix) is exercised here too — a conditionally
pre-bound live-in name is refused with the SAME blocker text the exact
guarded-return lane and the other near-dup siblings emit.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.near_dup import NearDuplicateGroup, find_near_duplicates
from app.execution.dedup_guarded_return import _call_lines, _free_sentinel_name
from app.execution.near_dup_guarded_return import plan_near_dup_guarded_return
from app.execution.unused_imports import strip_unused_imports


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
# POSITIVES — exec-equivalence on guard-taken AND fall-through paths.
# ══════════════════════════════════════════════════════════════════════════

# ── 1. flagship: 1-diff live_out projection, guard-taken AND fall-through ──

_FLAGSHIP_A = '''\
def build_a(data, key, log):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 2
    log.append(name)
    return size


def build_b(data, key, log):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 3
    log.append(name)
    log.append(size)
    return size
'''


def test_flagship_live_out_projection_guard_taken_and_fallthrough(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "pkg/mod.py", _FLAGSHIP_A)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    group = _group_at(groups, "pkg/mod.py:2", "pkg/mod.py:12")
    assert group.diff_count == 1
    assert sorted(group.differences[0]) == ["2", "3"]

    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    assert plan.old == "near_dup_guarded_return"

    helper = plan.new
    new_src = plan.new_contents["pkg/mod.py"]
    ast.parse(new_src)
    assert "if item is None:" in new_src and 'return "missing"' in new_src
    # `log` is read only AFTER the run (not inside it), so it is not live-in.
    assert f"= {helper}(data, key, 2)" in new_src
    assert f"= {helper}(data, key, 3)" in new_src

    before = _exec_module(_FLAGSHIP_A)
    after = _exec_module(new_src)
    data = {"k": {"name": "n", "size": 4}}
    for fn in ("build_a", "build_b"):
        # Fall-through path (data present): exec-equivalent, side effects too.
        b_log: list = []
        a_log: list = []
        assert before[fn](data, "k", b_log) == after[fn](data, "k", a_log)
        assert b_log == a_log
        # Guard-taken path (missing key): returns "missing", no side effect.
        b_log2: list = []
        a_log2: list = []
        assert before[fn](data, "nope", b_log2) == after[fn](data, "nope", a_log2) \
            == "missing"
        assert b_log2 == a_log2 == []


# ── 2. live_out == [] — 3-line shape, guard + side-effect fall-through ──

_LIVE_OUT_EMPTY_A = '''\
def go_a(flag, out):
    if flag:
        return
    out.append(1)
    out.append(10)


def go_b(flag, out):
    if flag:
        return
    out.append(1)
    out.append(20)
'''


def test_live_out_empty_three_line_shape(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _LIVE_OUT_EMPTY_A)
    group = _only_group(tmp_path, min_statements=3)
    assert group.diff_count == 1

    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    helper = plan.new
    # live_out == [] -> the simple 3-line guard (no live-out rebind line).
    assert f"if _res is not _{helper.upper().lstrip('_')}_MISS:" in new_src or \
        "is not _" in new_src
    assert new_src.count("= object()") == 1

    before = _exec_module(_LIVE_OUT_EMPTY_A)
    after = _exec_module(new_src)
    for flag in (True, False):
        b_out: list = []
        a_out: list = []
        assert before["go_a"](flag, b_out) == after["go_a"](flag, a_out)
        assert b_out == a_out
        b_out2: list = []
        a_out2: list = []
        assert before["go_b"](flag, b_out2) == after["go_b"](flag, a_out2)
        assert b_out2 == a_out2


# ── 3. multi-name live_out — 2-tuple projection ──

_MULTI_LIVE_OUT_A = '''\
def build_a(data, key, log):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 2
    log.append(name)
    return f"{name}:{size}"


def build_b(data, key, log):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 3
    log.append(name)
    log.append(size)
    return f"{name}:{size}"
'''


def test_multi_name_live_out_two_tuple_projection(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _MULTI_LIVE_OUT_A)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    group = _group_at(groups, "mod.py:2", "mod.py:12")
    assert group.diff_count == 1

    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    assert new_src.count("name, size =") == 2  # live-out rebinds (sorted names)

    before = _exec_module(_MULTI_LIVE_OUT_A)
    after = _exec_module(new_src)
    data = {"k": {"name": "n", "size": 5}}
    for fn in ("build_a", "build_b"):
        assert before[fn](data, "k", []) == after[fn](data, "k", [])
        assert before[fn](data, "nope", []) == after[fn](data, "nope", []) == "missing"


# ── 4. single-name live_out — trailing-comma tuple unpack ──

_SINGLE_OUT_A = '''\
def scale_a(size, flag, out):
    if size < 0:
        return "bad"
    if flag:
        size = size * 2
    out.append(size)
    return f"A:{size}"


def scale_b(size, flag, out):
    if size < 0:
        return "bad"
    if flag:
        size = size * 3
    out.append(size)
    return f"B:{size}"
'''


def test_single_name_live_out_trailing_comma_unpack(tmp_path: Path) -> None:
    # Also the W100 acceptance shape: `size` is a PARAMETER (definitely
    # bound before the run) that the run rebinds only under `if flag:` —
    # sound, lands (the param-bound live-in name is always bound_before).
    _write(tmp_path, "mod.py", _SINGLE_OUT_A)
    groups = find_near_duplicates(tmp_path, min_statements=2)
    group = _group_at(groups, "mod.py:2", "mod.py:11")
    assert group.diff_count == 1

    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    ast.parse(new_src)
    assert new_src.count("(size,) =") == 2

    before = _exec_module(_SINGLE_OUT_A)
    after = _exec_module(new_src)
    for size, flag in ((-5, True), (-5, False), (3, True), (3, False)):
        b_out: list = []
        a_out: list = []
        assert before["scale_a"](size, flag, b_out) == after["scale_a"](size, flag, a_out)
        assert b_out == a_out
    assert after["scale_a"](3, True, []) == "A:6"
    assert after["scale_b"](3, False, []) == "B:3"


# ── 5. bare-return guard (None propagates) ──

_BARE_RETURN_A = '''\
def go_a(flag, out):
    if flag:
        return
    out.append(1)
    out.append(2)


def go_b(flag, out):
    if flag:
        return
    out.append(1)
    out.append(3)
'''


def test_bare_return_guard_none_propagates(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _BARE_RETURN_A)
    group = _only_group(tmp_path, min_statements=3)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]

    before = _exec_module(_BARE_RETURN_A)
    after = _exec_module(new_src)
    for flag in (True, False):
        b_out: list = []
        a_out: list = []
        assert before["go_a"](flag, b_out) == after["go_a"](flag, a_out) is None
        assert b_out == a_out


# ── 6. raise on a NON-guard path propagates through the lifted call ──

_RAISE_PROP_A = '''\
def go_a(flag, out):
    if flag:
        return None
    if out is None:
        raise ValueError("no out")
    out.append(1)
    out.append(2)


def go_b(flag, out):
    if flag:
        return None
    if out is None:
        raise ValueError("no out")
    out.append(1)
    out.append(3)
'''


def test_raise_on_non_guard_path_propagates(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _RAISE_PROP_A)
    group = _only_group(tmp_path, min_statements=4)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]

    before = _exec_module(_RAISE_PROP_A)
    after = _exec_module(new_src)
    # Guard-taken: returns None, no raise.
    assert before["go_a"](True, None) is after["go_a"](True, None) is None
    # Fall-through with out=None: BOTH raise identically.
    for fn in ("go_a", "go_b"):
        try:
            before[fn](False, None)
            raised_before = False
        except ValueError:
            raised_before = True
        try:
            after[fn](False, None)
            raised_after = False
        except ValueError:
            raised_after = True
        assert raised_before and raised_after
    # Fall-through, no raise: exec-equivalent.
    b_out: list = []
    a_out: list = []
    assert before["go_a"](False, b_out) == after["go_a"](False, a_out)
    assert b_out == a_out


# ── 7. W100 acceptance: conditional in-run rebind of a param-bound live-in
# name LANDS (see test 4 above, which doubles as this — see its docstring) ──

# ── 8. two Constant diffs on one line ──

_TWO_DIFFS_ONE_LINE_A = '''\
def go_a(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(2)
    pair = (2, 3)
    out.append(pair)


def go_b(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(2)
    pair = (4, 5)
    out.append(pair)
'''


def test_two_constant_diffs_one_line(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _TWO_DIFFS_ONE_LINE_A)
    group = _only_group(tmp_path, min_statements=5)
    assert group.diff_count == 2

    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    helper = plan.new
    assert "pair = (p0, p1)" in new_src
    assert f"= {helper}(flag, out, 2, 3)" in new_src
    assert f"= {helper}(flag, out, 4, 5)" in new_src

    before = _exec_module(_TWO_DIFFS_ONE_LINE_A)
    after = _exec_module(new_src)
    for flag in (True, False):
        b_out: list = []
        a_out: list = []
        before["go_a"](flag, b_out)
        after["go_a"](flag, a_out)
        assert b_out == a_out


# ── 9. three occurrences, one diff ──

_THREE_A = '''\
def alpha(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(10)
'''
_THREE_B = '''\
def beta(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(20)
'''
_THREE_C = '''\
def gamma(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(30)
'''


def test_three_occurrences_one_diff(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/a.py", _THREE_A)
    _write(tmp_path, "pkg/b.py", _THREE_B)
    _write(tmp_path, "pkg/c.py", _THREE_C)
    _write(tmp_path, "pkg/__init__.py", "")

    group = _only_group(tmp_path, min_statements=3, min_occurrences=3)
    assert len(group.occurrences) == 3

    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    all_src = "".join(plan.new_contents.values())
    helper = plan.new
    for const in ("10", "20", "30"):
        assert f"= {helper}(flag, out, {const})" in all_src
    for src in plan.new_contents.values():
        ast.parse(src)


# ── 10. cross-file group: import line carries BOTH the sentinel and helper ──

_CF_A = '''\
def alpha(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(10)
'''
_CF_B = '''\
def beta(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(20)
'''


def test_cross_file_group_import_carries_sentinel_and_helper(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/a.py", _CF_A)
    _write(tmp_path, "pkg/b.py", _CF_B)
    _write(tmp_path, "pkg/__init__.py", "")

    group = _only_group(tmp_path, min_statements=3)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"

    helper = plan.new
    first = plan.defined_in
    first_src = plan.new_contents[first]
    other = next(r for r in plan.new_contents if r != first)
    other_src = plan.new_contents[other]

    assert f"def {helper}(" in first_src
    assert "= object()" in first_src
    assert "import" in other_src and helper in other_src and "_MISS" in other_src
    assert "= object()" not in other_src
    assert f"def {helper}(" not in other_src

    for src in plan.new_contents.values():
        ast.parse(src)

    before_a = _exec_module(_CF_A)
    after_first = _exec_module(first_src)
    for flag in (True, False):
        b_out: list = []
        a_out: list = []
        assert before_a["alpha"](flag, b_out) == after_first["alpha"](flag, a_out)
        assert b_out == a_out


# ── 11. regression (H4): same-file copy ABOVE the first-in-emit-order
# container — the insert-index rebase must use the GUARDED call-line count ──

_ABOVE_CONTAINER = '''\
def bar(x, flag, out):
    if flag:
        return None
    out.append(x)
    out.append(100)


def foo(x, flag, out):
    if flag:
        return None
    out.append(x)
    out.append(5)
'''


def test_same_file_copy_above_container_keeps_helper_at_module_level(
        tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _ABOVE_CONTAINER)
    # bar's block starts at line 2 (topmost); foo's at line 9 (bottom). Hand
    # the planner emit order [foo, bar] so `first = resolved[0]` is the
    # BOTTOM function (mirrors the exact-lane's own H4 regression).
    group = NearDuplicateGroup(occurrences=["mod.py:9", "mod.py:2"], lines=3,
                               diff_count=1, differences=[["5", "100"]])
    plan = plan_near_dup_guarded_return(tmp_path, group)
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
    for x, flag in ((-5, False), (0, True), (10, False)):
        b_out: list = []
        a_out: list = []
        before["foo"](x, flag, b_out)
        after["foo"](x, flag, a_out)
        assert b_out == a_out
        b_out2: list = []
        a_out2: list = []
        before["bar"](x, flag, b_out2)
        after["bar"](x, flag, a_out2)
        assert b_out2 == a_out2


# ── 12. Constant diff inside the GUARD's own test (control-flow-affecting
# hole) — exec-equivalent on both the guard-taken and fall-through branches ──

_GUARD_TEST_DIFF_A = '''\
def go_a(n, out):
    if n > 2:
        return None
    out.append(1)
    out.append(2)
    out.append(3)


def go_b(n, out):
    if n > 5:
        return None
    out.append(1)
    out.append(2)
    out.append(3)
'''


def test_constant_diff_inside_guard_test_control_flow_affecting(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "mod.py", _GUARD_TEST_DIFF_A)
    group = _only_group(tmp_path, min_statements=4)
    assert group.diff_count == 1

    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    helper = plan.new
    assert "if n > p0:" in new_src
    assert f"= {helper}(n, out, 2)" in new_src
    assert f"= {helper}(n, out, 5)" in new_src

    before = _exec_module(_GUARD_TEST_DIFF_A)
    after = _exec_module(new_src)
    # n=3: guard_a fires (3>2), guard_b does not (3>5 false) -- both sides
    # of the CONTROL-FLOW-AFFECTING hole exercised.
    for n in (0, 3, 6):
        for fn in ("go_a", "go_b"):
            b_out: list = []
            a_out: list = []
            assert before[fn](n, b_out) == after[fn](n, a_out)
            assert b_out == a_out


# ── 13. rvar/sentinel collision fallbacks ──

_SENTINEL_TAKEN = '''\
_GO_MISS = 3


def go_a(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(2)


def go_b(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(3)
'''


def test_sentinel_name_collision_falls_to_next_free(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _SENTINEL_TAKEN)
    group = _only_group(tmp_path, min_statements=3)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    assert "_GO_MISS_2 = object()" in new_src
    assert new_src.count("_GO_MISS = 3") == 1  # the live binding untouched


_RVAR_TAKEN = '''\
def go_a(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(2)
    _res = 1
    out.append(_res)


def go_b(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(3)
    _res = 2
    out.append(_res)
'''


def test_result_name_collision_falls_to_next_free(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _RVAR_TAKEN)
    groups = find_near_duplicates(tmp_path, min_statements=3)
    group = _group_at(groups, "mod.py:2", "mod.py:11")
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    assert "_res_2 =" in new_src and "if _res_2 is not" in new_src

    before = _exec_module(_RVAR_TAKEN)
    after = _exec_module(new_src)
    b_out: list = []
    a_out: list = []
    before["go_a"](False, b_out)
    after["go_a"](False, a_out)
    assert b_out == a_out


# ── 14. H-B closure: a run-local named `p0` must not collide with the
# neutral `p<n>` fallback ──

_HB_P0 = '''\
def go_a(flag, out):
    if flag:
        return None
    p0 = 1
    out.append(p0)
    out.append(2)


def go_b(flag, out):
    if flag:
        return None
    p0 = 1
    out.append(p0)
    out.append(3)
'''


def test_param_seed_avoids_run_local_p0_h_b_fix(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _HB_P0)
    group = _only_group(tmp_path, min_statements=4)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    helper = plan.new
    assert f"def {helper}(flag, out, p1):" in new_src
    assert "p0 = 1" in new_src  # the run's own local survives untouched

    before = _exec_module(_HB_P0)
    after = _exec_module(new_src)
    b_out: list = []
    a_out: list = []
    before["go_a"](False, b_out)
    after["go_a"](False, a_out)
    assert b_out == a_out


# ══════════════════════════════════════════════════════════════════════════
# REFUSALS — one per rail, blocker substring pinned.
# ══════════════════════════════════════════════════════════════════════════

# ── routing complement 1: a plain block (no return anywhere) routes to
# dedup-parameterized/dedup_extract ──

_PLAIN_BLOCK = '''\
def alpha(n, log):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 10
    log.append(d)


def beta(n, log):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 20
    log.append(d)
'''


def test_routing_complement_refuses_plain_block(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _PLAIN_BLOCK)
    group = _only_group(tmp_path)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("dedup_extract's job" in b for b in plan.blockers)


# ── routing complement 1b: a CLEAN TAIL return (dedup-parameterized's own
# admissible shape) is ALSO refused here — but with the total-return
# blocker, since `_always_returns` only inspects the run's last statement
# (a lone tail return still "always returns"). dedup-parameterized itself
# still lands this shape (see test_dedup_parameterized.py precedent); the
# routing complement this lane needs is purely "has_return" + "always
# returns", not "is this dedup_extract's specific admissible shape" —
# intrinsic disjointness, not an extra gate. ──

_TAIL_RETURN_BLOCK = '''\
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


def test_clean_tail_return_routes_to_total_return_sibling(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _TAIL_RETURN_BLOCK)
    group = _only_group(tmp_path)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("dedup-total-return's job" in b for b in plan.blockers)


# ── routing complement 2: an always-returning block routes to the
# total-return sibling ──

_ALWAYS_RETURNS = '''\
def alpha(n, flag):
    if flag:
        return -1
    a = n + 1
    b = a * 2
    c = b + 10
    return c


def beta(n, flag):
    if flag:
        return -1
    a = n + 1
    b = a * 2
    c = b + 20
    return c
'''


def test_routing_complement_refuses_always_returning_block(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _ALWAYS_RETURNS)
    group = _only_group(tmp_path)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("dedup-total-return's job" in b for b in plan.blockers)


# ── W100 boundary: live_out conditionally-bound-ONLY is blocked ──

_COND_OUT = '''\
def fa(cond, flag, out):
    if not cond:
        return None
    if flag:
        val = 1
    out2 = 7
    out.append(out2)
    return val + out2


def fb(cond, flag, out):
    if not cond:
        return None
    if flag:
        val = 1
    out2 = 8
    out.append(out2)
    return val + out2
'''


def test_conditionally_bound_live_out_only_is_blocked(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _COND_OUT)
    groups = find_near_duplicates(tmp_path, min_statements=3)
    group = _group_at(groups, "mod.py:2", "mod.py:12")
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("val" in b and "unbound" in b for b in plan.blockers)


# ── W99b-fix: conditional PRE-run bind of a live-in name is refused (parity
# with the exact lane's own rail) ──

_COND_BEFORE_LIVE_IN = '''\
def ga(cond, flag, out):
    if cond:
        acc = 1
    if not cond:
        return None
    if flag:
        out.append(acc)
    total = 7
    out.append(total)


def gb(cond, flag, out):
    if cond:
        acc = len(out)
    if not cond:
        return None
    if flag:
        out.append(acc)
    total = 8
    out.append(total)
'''


def test_conditional_pre_run_bind_of_live_in_is_refused(tmp_path: Path) -> None:
    # W99b-fix parity: `acc` is live-in (read in the run) but bound only
    # under `if cond:` in the PRELUDE (outside the run) — the same
    # eager-eval hazard the family-wide rail closes, wired here through the
    # inherited (verbatim-delegated) resolver.
    _write(tmp_path, "mod.py", _COND_BEFORE_LIVE_IN)
    group = _only_group(tmp_path, min_statements=4)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("acc" in b and "unbound before the range even runs" in b
              for b in plan.blockers)


# ── del in the run ──

_DEL_IN_RUN = '''\
def fa(flag, d, out):
    if flag:
        return None
    d["k"] = 1
    del d["k"]
    out.append(1)


def fb(flag, d, out):
    if flag:
        return None
    d["k"] = 2
    del d["k"]
    out.append(1)
'''


def test_del_in_run_is_blocked(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _DEL_IN_RUN)
    group = _only_group(tmp_path, min_statements=4)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("`del`" in b for b in plan.blockers)


# ── super()/__class__ reference ──

_SUPER_REF = '''\
class Base:
    def alpha(self, flag, out):
        if flag:
            return None
        super().__init__()
        out.append(1)

    def beta(self, flag, out):
        if flag:
            return None
        super().__init__()
        out.append(2)
'''


def test_super_reference_is_blocked(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _SUPER_REF)
    group = _only_group(tmp_path, min_statements=3)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("references `super`" in b for b in plan.blockers)


# ── shadowed object/type/tuple/len builtins ──

_OBJECT_SHADOW = '''\
object = lambda: None


def fa(x, out):
    if x < 0:
        return
    out.append(x)
    out.append(1)


def fb(x, out):
    if x < 0:
        return
    out.append(x)
    out.append(2)
'''


def test_shadowed_object_builtin_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _OBJECT_SHADOW)
    group = _only_group(tmp_path, min_statements=3)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("`object` is shadowed" in b for b in plan.blockers)


# ── Name hole: Constant-only gate (W99c defers Name holes) ──

_NAME_HOLE = '''\
G = 100
H = 200


def alpha(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(G)


def beta(flag, out):
    if flag:
        return None
    out.append(1)
    out.append(H)
'''


def test_name_hole_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _NAME_HOLE)
    group = _only_group(tmp_path, min_statements=3)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("only constant holes are parameterized" in b for b in plan.blockers)


# ── f-string hole ──

_FSTRING_HOLE = '''\
def alpha(x, out):
    if x < 0:
        return None
    a = x + 1
    b = f"red {a}"
    out.append(b)


def beta(x, out):
    if x < 0:
        return None
    a = x + 1
    b = f"blue {a}"
    out.append(b)
'''


def test_fstring_hole_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _FSTRING_HOLE)
    groups = find_near_duplicates(tmp_path, min_statements=3)
    group = _group_at(groups, "mod.py:2", "mod.py:10")
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("inside an f-string" in b for b in plan.blockers)


# ── annotation hole ──

_ANNOTATION_HOLE = '''\
def alpha(n, out):
    if n < 0:
        return None
    a = n + 1
    x: int = a + 1
    out.append(x)


def beta(n, out):
    if n < 0:
        return None
    a = n + 1
    x: str = a + 1
    out.append(x)
'''


def test_annotation_hole_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _ANNOTATION_HOLE)
    groups = find_near_duplicates(tmp_path, min_statements=3)
    group = _group_at(groups, "mod.py:2", "mod.py:10")
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("sits inside an annotation" in b for b in plan.blockers)


# ── match-pattern hole ──

_MATCH_HOLE = '''\
def alpha(cmd, out):
    if cmd is None:
        return None
    match cmd:
        case 100:
            out.append("hit")
        case _:
            out.append("miss")
    out.append(1)


def beta(cmd, out):
    if cmd is None:
        return None
    match cmd:
        case 200:
            out.append("hit")
        case _:
            out.append("miss")
    out.append(2)
'''


def test_match_pattern_hole_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _MATCH_HOLE)
    group = _only_group(tmp_path, min_statements=3)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("a `match` pattern" in b for b in plan.blockers)


# ── multi-line string + docstring-position (inherited family rails) ──

_MLSTR_NONFIRST = '''\
def alpha(x, flag, out):
    if flag:
        return "one-line"
    out.append(x)
    out.append(1)


def beta(x, flag, out):
    if flag:
        return """multi
line"""
    out.append(x)
    out.append(2)
'''


def test_multiline_str_nonfirst_occurrence_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _MLSTR_NONFIRST)
    group = _only_group(tmp_path, min_statements=3)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("multi-line string constant" in b for b in plan.blockers)


_DOC_POSITION = '''\
def alpha(n, flag, out):
    """Compute A."""
    if flag:
        return None
    a = n + 1
    out.append(a)
    out.append(1)


def beta(n, flag, out):
    """Compute B."""
    if flag:
        return None
    a = n + 1
    out.append(a)
    out.append(2)
'''


def test_docstring_position_run_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _DOC_POSITION)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    group = _group_at(groups, "mod.py:2", "mod.py:11")
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("starts at the enclosing function's docstring" in b
              for b in plan.blockers)


# ── overlap: self-overlapping periodic guard-shaped body ──

_OVERLAP_GUARDED = '''\
def f(x):
    if x:
        return 1
    if x:
        return 1
    if x:
        return 1
    if x:
        return 1
    if x:
        return 2
'''


def test_overlap_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _OVERLAP_GUARDED)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    group = _group_at(groups, "mod.py:2", "mod.py:4")
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("overlap" in b for b in plan.blockers)


# ── template drift: the group goes stale between build and plan ──

_DRIFT_BASE = (
    "def f1(x, flag, out):\n"
    "    if flag:\n"
    "        return None\n"
    "    a = x - 3\n"
    "    d = a + 7\n"
    "    out.append(d)\n"
    "\n\n"
    "def f2(x, flag, out):\n"
    "    if flag:\n"
    "        return None\n"
    "    a = x - 3\n"
    "    d = a + 8\n"
    "    out.append(d)\n"
)
# Operator-only drift in f2: `d = a + 8` -> `d = a * 8` — the leaf walk
# never visits operator nodes, so only the re-derived structural TEMPLATE
# catches this.
_DRIFT_STALE = _DRIFT_BASE.replace("d = a + 8\n    out.append(d)",
                                   "d = a * 8\n    out.append(d)")


def test_template_drift_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "m.py", _DRIFT_BASE)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    group = _group_at(groups, "m.py:2", "m.py:10")
    # The file drifts AFTER the group was built.
    _write(tmp_path, "m.py", _DRIFT_STALE)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("no longer share one structural template" in b
              for b in plan.blockers)


# ── ClassDef in the run (family-wide rail) ──

_CLASSDEF_RUN = '''\
def alpha(flag, out):
    if flag:
        return None
    class Local:
        pass
    out.append(1)


def beta(flag, out):
    if flag:
        return None
    class Local:
        pass
    out.append(2)
'''


def test_classdef_in_run_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _CLASSDEF_RUN)
    group = _only_group(tmp_path, min_statements=3)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("defines a `class`" in b for b in plan.blockers)


# ── divergent live_out (and live_in) signatures ──

_SIG_DIVERGE = '''\
k = 7


def alpha(cond, k2, out):
    a = k2 + 1
    if not cond:
        return None
    b = a + 1
    out.append(b)
    return b


def beta(cond, out):
    a = k + 1
    if not cond:
        return None
    b = a + 1
    out.append(b)
    return b
'''


def test_divergent_signatures_block(tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", _SIG_DIVERGE)
    group = _only_group(tmp_path, min_statements=2)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("different data-flow signatures" in b for b in plan.blockers)


# ══════════════════════════════════════════════════════════════════════════
# HYGIENE — determinism, gate-clean imports, malformed inputs, default parity.
# ══════════════════════════════════════════════════════════════════════════

def test_determinism_two_runs_byte_identical(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _FLAGSHIP_A)
    groups = find_near_duplicates(tmp_path, min_statements=4)
    group = _group_at(groups, "pkg/mod.py:2", "pkg/mod.py:12")
    p1 = plan_near_dup_guarded_return(tmp_path, group)
    p2 = plan_near_dup_guarded_return(tmp_path, group)
    assert p1.ok and p2.ok
    assert p1.new == p2.new
    assert p1.new_contents == p2.new_contents
    assert p1.blockers == p2.blockers


_IMPORT_SAME_MODULE = '''\
import math


def alpha(n, flag, out):
    if flag:
        return None
    a = math.floor(n)
    out.append(a)
    out.append(1)


def beta(n, flag, out):
    if flag:
        return None
    a = math.floor(n)
    out.append(a)
    out.append(2)
'''


def test_gate_clean_import_used_by_block_stays_live(tmp_path: Path) -> None:
    # A cross-file group reading a free import name is refused by the family
    # rail (_cross_module_rebind_blocker) — the reachable, honest proof is
    # the SAME-MODULE lift: the helper lands beside the import it uses, so
    # the import stays referenced (never stranded) and the module is
    # gate-clean (no F401).
    _write(tmp_path, "mod.py", _IMPORT_SAME_MODULE)
    group = _only_group(tmp_path, min_statements=4)
    plan = plan_near_dup_guarded_return(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    ast.parse(new_src)
    assert strip_unused_imports(new_src) is None
    assert "import math" in new_src


def test_fewer_than_two_occurrences_blocks(tmp_path: Path) -> None:
    g = NearDuplicateGroup(occurrences=["pkg/mod.py:1"], lines=3, diff_count=1,
                           differences=[["10"]])
    plan = plan_near_dup_guarded_return(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents
    assert any("two occurrences" in b for b in plan.blockers)


def test_zero_statements_blocks(tmp_path: Path) -> None:
    g = NearDuplicateGroup(occurrences=["pkg/a.py:1", "pkg/b.py:1"], lines=0,
                           diff_count=1, differences=[["1", "2"]])
    plan = plan_near_dup_guarded_return(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents
    assert any("no statements" in b for b in plan.blockers)


def test_malformed_occurrence_locations_block(tmp_path: Path) -> None:
    g = NearDuplicateGroup(occurrences=["no-colon", "also/bad"], lines=3,
                           diff_count=1, differences=[["1", "2"]])
    plan = plan_near_dup_guarded_return(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents


def test_unreadable_module_blocks(tmp_path: Path) -> None:
    g = NearDuplicateGroup(occurrences=["gone.py:2", "gone2.py:2"], lines=3,
                           diff_count=1, differences=[["1", "2"]])
    plan = plan_near_dup_guarded_return(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents
    assert any("cannot read" in b for b in plan.blockers)


def test_zero_diff_group_blocks() -> None:
    """A zero-diff group is an exact duplicate (dedup-guarded-return's own
    job), never a parameterization target."""
    g = NearDuplicateGroup(occurrences=["a.py:1", "b.py:1"], lines=3,
                           diff_count=0, differences=[])
    plan = plan_near_dup_guarded_return(".", g)
    assert not plan.ok
    assert not plan.new_contents
    assert any("exact duplicate" in b for b in plan.blockers)


# ── share-in-place default-path parity: the generalized helpers' defaults
# byte-preserve the exact lane (extra_args=() / also_avoid=frozenset()) ──

def test_call_lines_default_extra_args_is_empty_tuple() -> None:
    import inspect
    sig = inspect.signature(_call_lines)
    assert sig.parameters["extra_args"].default == ()


def test_free_sentinel_name_default_also_avoid_is_empty_frozenset() -> None:
    import inspect
    sig = inspect.signature(_free_sentinel_name)
    assert sig.parameters["also_avoid"].default == frozenset()
