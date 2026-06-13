"""Tests for parameterized-dedup extraction (near-dup detector → action).

This is the highest-risk transform in the repo, so the tests are deliberately
thorough: every positive case asserts the result RE-PARSES and is EXEC-EQUIVALENT
to the original across inputs, and every unsafe shape is asserted to BLOCK with
empty ``new_contents``. The group always comes through the real detector
(``find_near_duplicates``) so the pipeline under test is the production one.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.near_dup import NearDuplicateGroup, find_near_duplicates
from app.execution.near_dup_extract import plan_near_dup_extract


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _exec_module(source: str) -> dict:
    """Compile + run a module's source, returning its namespace."""
    ns: dict = {}
    exec(compile(source, "<mod>", "exec"), ns)  # noqa: S102 - controlled test src
    return ns


def _only_group(root: Path, **kw) -> NearDuplicateGroup:
    kw.setdefault("min_statements", 5)
    kw.setdefault("min_occurrences", 2)
    groups = find_near_duplicates(root, **kw)
    assert len(groups) == 1, f"expected exactly one near-dup group, got {groups}"
    return groups[0]


# ── 1. one differing constant → helper with ONE extra param, exec-equivalent ──

_ONE_CONST_A = '''\
def alpha(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 10
    return d
'''

_ONE_CONST_B = '''\
def beta(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 20
    return d
'''


def test_one_constant_diff_extracts_param_helper(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/a.py", _ONE_CONST_A)
    _write(tmp_path, "pkg/b.py", _ONE_CONST_B)
    _write(tmp_path, "pkg/__init__.py", "")

    group = _only_group(tmp_path)
    assert group.diff_count == 1
    assert sorted(group.differences[0]) == ["10", "20"]

    plan = plan_near_dup_extract(tmp_path, group)
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"

    helper = plan.new
    first = plan.defined_in
    first_src = plan.new_contents[first]
    other = next(r for r in plan.new_contents if r != first)
    other_src = plan.new_contents[other]

    # The helper has exactly the live-in param `n` plus ONE value param `p0`.
    assert f"def {helper}(n, p0):" in first_src
    # Each copy calls the helper with its OWN constant.
    assert f"return {helper}(n, 10)" in first_src
    assert f"return {helper}(n, 20)" in other_src
    # The other module imports the helper; it does not redefine it.
    assert f"import {helper}" in other_src
    assert f"def {helper}(" not in other_src

    # Everything re-parses.
    for src in plan.new_contents.values():
        ast.parse(src)

    # Exec-equivalent for BOTH functions across several inputs.
    before_a = _exec_module(_ONE_CONST_A)
    before_b = _exec_module(_ONE_CONST_B)
    after_first = _exec_module(first_src)
    # Rebuild the other module standalone by inlining the helper def so it can run
    # without the cross-module import: easier to just check the helper math here.
    for n in (-3, 0, 5, 17):
        assert after_first["alpha"](n) == before_a["alpha"](n)
    # The helper itself, run from the first module, reproduces beta's value too.
    for n in (-3, 0, 5, 17):
        assert after_first[helper](n, 20) == before_b["beta"](n)


# ── 1b. same-module one-constant diff → exec-equivalent for both copies ──

_SAME_MODULE_ONE = '''\
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


def test_same_module_one_constant_exec_equivalent(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _SAME_MODULE_ONE)
    group = _only_group(tmp_path)
    plan = plan_near_dup_extract(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"

    new_src = plan.new_contents["pkg/mod.py"]
    ast.parse(new_src)
    helper = plan.new
    assert f"def {helper}(n, p0):" in new_src
    # One def + two call sites referencing the helper.
    assert new_src.count(f"{helper}(") == 3
    # The duplicated body line that carried the constant is gone (now `c + p0`).
    assert "c + 10" not in new_src and "c + 20" not in new_src
    assert "c + p0" in new_src

    before = _exec_module(_SAME_MODULE_ONE)
    after = _exec_module(new_src)
    for n in (-5, 0, 4, 99):
        assert after["alpha"](n) == before["alpha"](n)
        assert after["beta"](n) == before["beta"](n)


# ── 2. TWO differing constants → two params, correct per-occurrence values ──

_TWO_DIFFS_A = '''\
def alpha(n):
    a = n + 5
    b = a * 2
    c = b + 3
    d = c + 10
    return d


def beta(n):
    a = n + 7
    b = a * 2
    c = b + 3
    d = c + 20
    return d
'''


def test_two_constant_diffs_two_params(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _TWO_DIFFS_A)
    group = _only_group(tmp_path)
    assert group.diff_count == 2

    plan = plan_near_dup_extract(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]
    ast.parse(new_src)
    helper = plan.new

    # Two value params p0, p1 in addition to the live-in `n`.
    assert f"def {helper}(n, p0, p1):" in new_src
    # alpha carried (5, 10); beta carried (7, 20) — order matters and must match
    # each occurrence's own values. The detector sorts occurrences by location,
    # alpha before beta, so the calls appear in that order.
    assert f"{helper}(n, 5, 10)" in new_src
    assert f"{helper}(n, 7, 20)" in new_src

    before = _exec_module(_TWO_DIFFS_A)
    after = _exec_module(new_src)
    for n in (-2, 0, 11, 50):
        assert after["alpha"](n) == before["alpha"](n)
        assert after["beta"](n) == before["beta"](n)


# ── 3. a differing NAME (not a constant) → BLOCKED, no new_contents ──

# G and H are module GLOBALS, so the differing leaf is a loaded `Name` that is
# NOT live-in (the data-flow only counts params and prior local stores). This
# keeps the live-in/live-out signature IDENTICAL across the two copies, so the
# block lands specifically on the constant-only gate (a differing Name → BLOCK),
# not on the upstream signature gate.
_NAME_DIFF_A = '''\
G = 100
H = 200


def alpha(n):
    base = n + 1
    a = base + 1
    b = a + 1
    c = b + G
    return c


def beta(n):
    base = n + 1
    a = base + 1
    b = a + 1
    c = b + H
    return c
'''


def test_differing_name_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _NAME_DIFF_A)
    group = _only_group(tmp_path)
    # The detector groups a differing LOADED name as a near-dup...
    assert group.diff_count == 1
    assert sorted(group.differences[0]) == ["G", "H"]

    # ...but our conservative extractor refuses: only differing CONSTANTS qualify.
    plan = plan_near_dup_extract(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("constant" in b for b in plan.blockers)


# ── 3b. a differing live-in NAME → blocked by the signature gate ──

# Here the differing loaded name is a PARAMETER (g vs h), so it is live-in: the
# signatures diverge and the upstream data-flow gate blocks first. Either way a
# differing name never produces an extraction.
_NAME_LIVE_IN = '''\
def alpha(n, g, h):
    base = n + 1
    a = base + g
    b = a + 1
    c = b + 1
    return c


def beta(n, g, h):
    base = n + 1
    a = base + h
    b = a + 1
    c = b + 1
    return c
'''


def test_differing_live_in_name_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _NAME_LIVE_IN)
    group = _only_group(tmp_path)
    assert group.diff_count == 1
    plan = plan_near_dup_extract(tmp_path, group)
    assert not plan.ok
    assert not plan.new_contents
    assert any("signature" in b or "data-flow" in b for b in plan.blockers)


# ── 4. divergent live-in/live-out signature across occurrences → BLOCKED ──

# Both blocks are structurally identical with one differing constant, but `d` is
# read AFTER the block in beta (live_out there) and not in alpha — so the helper
# return signature would differ between copies.
_DIVERGENT_SIG = '''\
def alpha(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 10
    e = d + 1
    return e


def beta(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 20
    e = d + 1
    return d + e
'''


def test_divergent_signature_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _DIVERGENT_SIG)
    # 6-statement window so the run is the block BEFORE the trailing return that
    # makes `d` live-out in beta only.
    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert groups, "detector should still see the structurally-identical block"
    plan = plan_near_dup_extract(tmp_path, groups[0])
    assert not plan.ok, "divergent live-out should block"
    assert not plan.new_contents
    assert any("signature" in b or "data-flow" in b for b in plan.blockers)


# ── 5. an EARLY (non-tail) return in the block → BLOCKED ──

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


def test_early_return_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _EARLY_RETURN)
    groups = find_near_duplicates(tmp_path, min_statements=5, min_occurrences=2)
    assert groups, "detector should see the near-dup block"
    plan = plan_near_dup_extract(tmp_path, groups[0])
    assert not plan.ok
    assert not plan.new_contents
    assert plan.blockers


# ── 6. tail-return near-dup with a constant diff → returning helper, exec-eq ──

_TAIL_RETURN_A = '''\
def alpha(x):
    a = x + 1
    b = a * 2
    c = b - 3
    d = c + 4
    return d + 100
'''

_TAIL_RETURN_B = '''\
def beta(x):
    a = x + 1
    b = a * 2
    c = b - 3
    d = c + 4
    return d + 200
'''


def test_tail_return_constant_diff(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/a.py", _TAIL_RETURN_A)
    _write(tmp_path, "pkg/b.py", _TAIL_RETURN_B)
    _write(tmp_path, "pkg/__init__.py", "")

    group = _only_group(tmp_path)
    assert group.diff_count == 1
    assert sorted(group.differences[0]) == ["100", "200"]

    plan = plan_near_dup_extract(tmp_path, group)
    assert plan.ok, f"tail-return constant diff should extract, blockers={plan.blockers}"

    helper = plan.new
    first = plan.defined_in
    first_src = plan.new_contents[first]
    other = next(r for r in plan.new_contents if r != first)
    other_src = plan.new_contents[other]

    # The block's own `return <expr>` lives inside the helper; call sites return.
    assert f"def {helper}(x, p0):" in first_src
    assert "return d + p0" in first_src
    assert f"return {helper}(x, 100)" in first_src
    assert f"return {helper}(x, 200)" in other_src

    for src in plan.new_contents.values():
        ast.parse(src)

    before_a = _exec_module(_TAIL_RETURN_A)
    before_b = _exec_module(_TAIL_RETURN_B)
    after_first = _exec_module(first_src)
    for x in (-7, 0, 3, 42):
        assert after_first["alpha"](x) == before_a["alpha"](x)
        # The helper with beta's constant reproduces beta's value.
        assert after_first[helper](x, 200) == before_b["beta"](x)


# ── 7. determinism: same input → identical plan ──

def test_determinism(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _SAME_MODULE_ONE)
    group = _only_group(tmp_path)
    p1 = plan_near_dup_extract(tmp_path, group)
    p2 = plan_near_dup_extract(tmp_path, group)
    assert p1.new == p2.new
    assert p1.new_contents == p2.new_contents
    assert p1.blockers == p2.blockers
    assert p1.ok and p2.ok


# ── 8. empty / malformed groups → clean blockers, no new_contents ──

def test_empty_group_blocks(tmp_path: Path) -> None:
    g = NearDuplicateGroup(occurrences=[], lines=5, diff_count=1,
                           differences=[["1", "2"]])
    plan = plan_near_dup_extract(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents
    assert any("two occurrences" in b for b in plan.blockers)


def test_single_occurrence_blocks(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _SAME_MODULE_ONE)
    g = NearDuplicateGroup(occurrences=["pkg/mod.py:1"], lines=5, diff_count=1,
                           differences=[["10"]])
    plan = plan_near_dup_extract(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents


def test_zero_diff_group_blocks(tmp_path: Path) -> None:
    # A zero-diff group is an EXACT duplicate (dedup_extract's job), not ours.
    g = NearDuplicateGroup(occurrences=["pkg/a.py:1", "pkg/b.py:1"], lines=5,
                           diff_count=0, differences=[])
    plan = plan_near_dup_extract(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents
    assert any("exact duplicate" in b or "differing position" in b
               for b in plan.blockers)


def test_malformed_occurrence_blocks(tmp_path: Path) -> None:
    g = NearDuplicateGroup(occurrences=["no-colon", "also/bad"], lines=5,
                           diff_count=1, differences=[["1", "2"]])
    plan = plan_near_dup_extract(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents


def test_malformed_differences_blocks(tmp_path: Path) -> None:
    # differences column not parallel to occurrences.
    g = NearDuplicateGroup(occurrences=["pkg/a.py:1", "pkg/b.py:1"], lines=5,
                           diff_count=1, differences=[["1"]])
    plan = plan_near_dup_extract(tmp_path, g)
    assert not plan.ok
    assert not plan.new_contents


# ── 9. three occurrences, one constant diff → three correct call sites ──

_THREE_A = '''\
def alpha(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 10
    return d
'''

_THREE_B = '''\
def beta(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 20
    return d
'''

_THREE_C = '''\
def gamma(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c + 30
    return d
'''


def test_three_occurrences_one_diff(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/a.py", _THREE_A)
    _write(tmp_path, "pkg/b.py", _THREE_B)
    _write(tmp_path, "pkg/c.py", _THREE_C)
    _write(tmp_path, "pkg/__init__.py", "")

    group = _only_group(tmp_path, min_occurrences=3)
    assert len(group.occurrences) == 3
    assert sorted(group.differences[0]) == ["10", "20", "30"]

    plan = plan_near_dup_extract(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    helper = plan.new
    first_src = plan.new_contents[plan.defined_in]
    assert f"def {helper}(n, p0):" in first_src

    # Every occurrence's own constant reaches its own call site.
    all_src = "".join(plan.new_contents.values())
    for const in ("10", "20", "30"):
        assert f"{helper}(n, {const})" in all_src

    for src in plan.new_contents.values():
        ast.parse(src)

    after_first = _exec_module(first_src)
    before_a = _exec_module(_THREE_A)
    for n in (-1, 0, 8):
        assert after_first["alpha"](n) == before_a["alpha"](n)
        assert after_first[helper](n, 20) == before_a["alpha"](n) + 10
        assert after_first[helper](n, 30) == before_a["alpha"](n) + 20


# ── 10. string-constant diff → rendered as a Python literal, exec-equivalent ──

_STR_A = '''\
def alpha(n):
    a = str(n)
    b = a + "x"
    c = b + "y"
    d = c + "left"
    return d
'''

_STR_B = '''\
def beta(n):
    a = str(n)
    b = a + "x"
    c = b + "y"
    d = c + "right"
    return d
'''


def test_string_constant_diff(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _STR_A + "\n\n" + _STR_B)
    group = _only_group(tmp_path)
    assert group.diff_count == 1

    plan = plan_near_dup_extract(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]
    ast.parse(new_src)
    helper = plan.new
    assert f"def {helper}(n, p0):" in new_src
    assert "c + p0" in new_src
    assert f'{helper}(n, "left")' in new_src
    assert f'{helper}(n, "right")' in new_src

    before = _exec_module(_STR_A + "\n\n" + _STR_B)
    after = _exec_module(new_src)
    for n in (0, 3, 9):
        assert after["alpha"](n) == before["alpha"](n)
        assert after["beta"](n) == before["beta"](n)


# ── 11. param-name collision avoidance: a live-in named `p0` → helper uses `p1` ──

_COLLIDE_A = '''\
def alpha(p0):
    a = p0 + 1
    b = a * 2
    c = b + 3
    d = c + 10
    return d


def beta(p0):
    a = p0 + 1
    b = a * 2
    c = b + 3
    d = c + 20
    return d
'''


def test_param_name_collision_avoided(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", _COLLIDE_A)
    group = _only_group(tmp_path)
    plan = plan_near_dup_extract(tmp_path, group)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]
    ast.parse(new_src)
    helper = plan.new
    # live-in is `p0`, so the value param must avoid it → `p1`.
    assert f"def {helper}(p0, p1):" in new_src
    assert f"{helper}(p0, 10)" in new_src
    assert f"{helper}(p0, 20)" in new_src

    before = _exec_module(_COLLIDE_A)
    after = _exec_module(new_src)
    for v in (-4, 0, 6):
        assert after["alpha"](v) == before["alpha"](v)
        assert after["beta"](v) == before["beta"](v)
