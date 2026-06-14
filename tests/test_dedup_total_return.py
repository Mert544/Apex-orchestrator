"""Tests for the dedup total-return transform.

This covers the conservative control-flow-aware extraction: an EXACT-duplicate
block whose EVERY exit path is a ``return`` (guard returns and/or a final return,
or all-returning if/elif/else) lifts into a returning helper, each call site
becoming ``return _shared_n(...)``. Everything else BLOCKS. The suite is
exhaustive by intent — this is high-risk, so correctness over coverage.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.dedup import DuplicateBlock, find_duplicates
from app.execution.dedup_total_return import _always_returns, plan_dedup_total_return


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _exec_module(source: str) -> dict:
    ns: dict = {}
    exec(compile(source, "<mod>", "exec"), ns)  # noqa: S102 - controlled test src
    return ns


def _parse_stmts(src: str) -> list[ast.stmt]:
    """Parse a snippet and return the body statements of its single function."""
    fn = ast.parse(src).body[0]
    assert isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
    return fn.body


# ──────────────────────────────────────────────────────────────────────────
# _always_returns — the precise admissibility rule, unit-tested in isolation.
# ──────────────────────────────────────────────────────────────────────────

def test_always_returns_empty_is_false():
    assert _always_returns([]) is False


def test_always_returns_tail_return_is_true():
    assert _always_returns(_parse_stmts(
        "def f():\n    x = 1\n    return x\n")) is True


def test_always_returns_tail_raise_is_true():
    assert _always_returns(_parse_stmts(
        "def f():\n    x = 1\n    raise ValueError(x)\n")) is True


def test_always_returns_guard_then_return_is_true():
    # `if cond: return a` then `return b` — both paths return.
    assert _always_returns(_parse_stmts(
        "def f(cond, a, b):\n"
        "    if cond:\n"
        "        return a\n"
        "    return b\n")) is True


def test_always_returns_if_elif_else_all_return_is_true():
    assert _always_returns(_parse_stmts(
        "def f(n):\n"
        "    if n > 0:\n"
        "        return 1\n"
        "    elif n < 0:\n"
        "        return -1\n"
        "    else:\n"
        "        return 0\n")) is True


def test_always_returns_if_without_else_is_false():
    # An `if` with no `else` falls through when cond is False.
    assert _always_returns(_parse_stmts(
        "def f(cond, a):\n"
        "    if cond:\n"
        "        return a\n")) is False


def test_always_returns_if_else_one_branch_falls_through_is_false():
    assert _always_returns(_parse_stmts(
        "def f(cond, a):\n"
        "    if cond:\n"
        "        return a\n"
        "    else:\n"
        "        a = a + 1\n")) is False


def test_always_returns_plain_tail_is_false():
    assert _always_returns(_parse_stmts(
        "def f():\n    x = 1\n    y = 2\n")) is False


def test_always_returns_loop_tail_is_false():
    # A loop whose body returns can still fall through with zero iterations.
    assert _always_returns(_parse_stmts(
        "def f(items):\n"
        "    for it in items:\n"
        "        return it\n")) is False


def test_always_returns_nested_if_in_else_is_true():
    # The else branch is itself a fully-returning if/else.
    assert _always_returns(_parse_stmts(
        "def f(n):\n"
        "    if n == 0:\n"
        "        return 'z'\n"
        "    else:\n"
        "        if n > 0:\n"
        "            return 'p'\n"
        "        else:\n"
        "            return 'n'\n")) is True


# ──────────────────────────────────────────────────────────────────────────
# Positive: guard-return + final-return block lifts into a returning helper.
# ──────────────────────────────────────────────────────────────────────────

_GUARD_RETURN = '''\
def alpha(cond, a, b):
    z = a + b
    w = z * 2
    if cond:
        return w
    return z


def beta(cond, a, b):
    z = a + b
    w = z * 2
    if cond:
        return w
    return z
'''


def test_guard_plus_final_return_lifts_into_returning_helper(tmp_path):
    root = tmp_path
    _write(root, "pkg/mod.py", _GUARD_RETURN)
    blocks = find_duplicates(root, min_statements=4, min_occurrences=2)
    assert blocks, "the detector should find the shared total-return block"
    block = blocks[0]

    plan = plan_dedup_total_return(root, block)
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]

    tree = ast.parse(new_src)  # re-parses
    helper_name = plan.new
    defs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert helper_name in defs
    # Each call site is a `return _shared_n(...)`.
    assert new_src.count(f"return {helper_name}(") == 2
    # The duplicated body is no longer literally repeated.
    assert new_src.count("w = z * 2") == 1
    # The helper keeps the block's own returns verbatim (guard + final).
    helper = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == helper_name)
    returns = [n for n in ast.walk(helper) if isinstance(n, ast.Return)]
    assert len(returns) == 2

    # Exec-equivalence across cond true/false.
    before = _exec_module(_GUARD_RETURN)
    after = _exec_module(new_src)
    for cond in (True, False):
        assert before["alpha"](cond, 3, 4) == after["alpha"](cond, 3, 4)
        assert before["beta"](cond, 3, 4) == after["beta"](cond, 3, 4)
    # Sanity on the actual values: w=14 when cond, z=7 otherwise.
    assert after["alpha"](True, 3, 4) == 14
    assert after["alpha"](False, 3, 4) == 7


# ──────────────────────────────────────────────────────────────────────────
# Positive: if/elif/else all-return block lifts, exec-equivalent.
# ──────────────────────────────────────────────────────────────────────────

_IF_ELIF_ELSE = '''\
def sign_alpha(n):
    base = n
    scaled = base
    if scaled > 0:
        return "pos"
    elif scaled < 0:
        return "neg"
    else:
        return "zero"


def sign_beta(n):
    base = n
    scaled = base
    if scaled > 0:
        return "pos"
    elif scaled < 0:
        return "neg"
    else:
        return "zero"
'''


def test_if_elif_else_all_return_lifts(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _IF_ELIF_ELSE)
    blocks = find_duplicates(root, min_statements=3, min_occurrences=2)
    assert blocks, "the detector should find the shared block"
    plan = plan_dedup_total_return(root, blocks[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]

    ast.parse(new_src)
    helper_name = plan.new
    assert new_src.count(f"return {helper_name}(") == 2
    assert new_src.count('return "neg"') == 1  # body collapsed to one copy

    before = _exec_module(_IF_ELIF_ELSE)
    after = _exec_module(new_src)
    for n in (5, -2, 0):
        assert before["sign_alpha"](n) == after["sign_alpha"](n)
        assert before["sign_beta"](n) == after["sign_beta"](n)
    assert after["sign_alpha"](5) == "pos"
    assert after["sign_alpha"](0) == "zero"


# ──────────────────────────────────────────────────────────────────────────
# Positive: cross-file total-return block — helper + import in second module.
# ──────────────────────────────────────────────────────────────────────────

_CROSS_A = '''\
def alpha(cond, x):
    y = x + 1
    z = y + 1
    if cond:
        return y
    return z
'''

_CROSS_B = '''\
def beta(cond, x):
    y = x + 1
    z = y + 1
    if cond:
        return y
    return z
'''


def test_cross_file_total_return_imports_helper(tmp_path):
    root = tmp_path
    _write(root, "a.py", _CROSS_A)
    _write(root, "b.py", _CROSS_B)
    blocks = find_duplicates(root, min_statements=4, min_occurrences=2)
    assert blocks, "the detector should find the cross-file block"
    plan = plan_dedup_total_return(root, blocks[0])
    assert plan.ok, f"blockers={plan.blockers}"
    helper_name = plan.new
    a_src = plan.new_contents["a.py"]
    b_src = plan.new_contents["b.py"]
    # Helper defined in the FIRST module; imported into the second.
    assert f"def {helper_name}(" in a_src
    assert f"from b import {helper_name}" in b_src or \
        f"from a import {helper_name}" in b_src or \
        f"import {helper_name}" in b_src
    # The module that gets the import is the one NOT defining the helper.
    definer = "a.py" if f"def {helper_name}(" in a_src else "b.py"
    importer = "b.py" if definer == "a.py" else "a.py"
    assert f"import {helper_name}" in plan.new_contents[importer]
    assert plan.new_contents[definer].count(f"return {helper_name}(") == 1
    assert plan.new_contents[importer].count(f"return {helper_name}(") == 1


# ──────────────────────────────────────────────────────────────────────────
# BLOCK: return in the MIDDLE with reachable code after (NOT total-return).
# ──────────────────────────────────────────────────────────────────────────

_MID_RETURN = '''\
def alpha(cond, a):
    b = a + 1
    if cond:
        return b
    c = b + 2
    d = c + 3
    return d


def beta(cond, a):
    b = a + 1
    if cond:
        return b
    c = b + 2
    d = c + 3
    return d
'''


def test_mid_block_return_with_code_after_is_total_return(tmp_path):
    # NB: this block actually IS total-return when the window includes the final
    # `return d` — the guard returns OR control reaches the final return. So we
    # take a window that STOPS before the final return: it then has a reachable
    # tail (`d = c + 3`) and must BLOCK.
    root = tmp_path
    _write(root, "mod.py", _MID_RETURN)
    # A 4-statement window starting at `b = a + 1` ends at `d = c + 3` (plain
    # tail) in each function → not total-return → blocked.
    blocks = find_duplicates(root, min_statements=4, min_occurrences=2)
    assert blocks
    # Pick the block whose run ends on a plain assignment (the 4-stmt window).
    block = next(b for b in blocks if b.lines == 4)
    plan = plan_dedup_total_return(root, block)
    assert not plan.ok, "a return-in-the-middle window with a plain tail must block"
    assert any("always return" in b for b in plan.blockers)
    assert not plan.new_contents


# ──────────────────────────────────────────────────────────────────────────
# BLOCK: block ending in a plain statement (dedup_extract's job, not ours).
# ──────────────────────────────────────────────────────────────────────────

_PLAIN_TAIL = '''\
def alpha():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e


def beta():
    a = 1
    b = 2
    c = a + b
    d = c * 3
    e = d - 1
    return e + 100
'''


def test_plain_tail_block_is_blocked(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _PLAIN_TAIL)
    # A 5-statement window covers the assignments only (no return) → plain tail.
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks
    block = blocks[0]
    plan = plan_dedup_total_return(root, block)
    assert not plan.ok, "a plain-tail block is dedup_extract's job, not ours"
    assert any("always return" in b for b in plan.blockers)
    assert not plan.new_contents


# ──────────────────────────────────────────────────────────────────────────
# BLOCK: yield / await / break-continue / nested-def in the block.
# ──────────────────────────────────────────────────────────────────────────

def _block_for(src_template: str, root: Path, *, min_statements: int) -> DuplicateBlock:
    """Write two identical copies and return the detected duplicate block."""
    _write(root, "mod.py", src_template)
    blocks = find_duplicates(root, min_statements=min_statements, min_occurrences=2)
    assert blocks, "the detector should still see the identical block"
    return blocks[0]


_WITH_YIELD = '''\
def alpha(items):
    total = 0
    for it in items:
        yield it
    return total


def beta(items):
    total = 0
    for it in items:
        yield it
    return total
'''


def test_yield_in_block_is_blocked(tmp_path):
    root = tmp_path
    block = _block_for(_WITH_YIELD, root, min_statements=3)
    plan = plan_dedup_total_return(root, block)
    assert not plan.ok
    assert any("yield" in b for b in plan.blockers)
    assert not plan.new_contents


_WITH_AWAIT = '''\
async def alpha(x):
    y = x + 1
    z = await something(y)
    return z


async def beta(x):
    y = x + 1
    z = await something(y)
    return z
'''


def test_await_in_block_is_blocked(tmp_path):
    root = tmp_path
    block = _block_for(_WITH_AWAIT, root, min_statements=3)
    plan = plan_dedup_total_return(root, block)
    assert not plan.ok
    assert any("await" in b for b in plan.blockers)
    assert not plan.new_contents


def test_escaping_break_in_block_is_blocked(tmp_path):
    # The 2-statement window `if it: break` / `return out` selects the `break`
    # but NOT its enclosing `for` loop, so the break escapes the lifted run.
    root = tmp_path
    _write(root, "mod.py", _BREAK_ESCAPES)
    blocks = find_duplicates(root, min_statements=2, min_occurrences=2)
    assert blocks
    # The 2-statement window `if it: break` / `return out` selects the break but
    # NOT its enclosing `for` → the break escapes → blocked.
    block = next(b for b in blocks if b.lines == 2)
    plan = plan_dedup_total_return(root, block)
    assert not plan.ok
    assert any("break" in b or "always return" in b for b in plan.blockers)
    assert not plan.new_contents


_BREAK_ESCAPES = '''\
def alpha(items):
    out = []
    for it in items:
        if it:
            break
        return out


def beta(items):
    out = []
    for it in items:
        if it:
            break
        return out
'''


_WITH_NESTED_DEF = '''\
def alpha(x):
    def inner(y):
        return y + 1
    z = inner(x)
    return z


def beta(x):
    def inner(y):
        return y + 1
    z = inner(x)
    return z
'''


def test_nested_def_in_block_is_blocked(tmp_path):
    root = tmp_path
    # min_statements=3 picks the whole-body window, which includes `def inner`.
    block = _block_for(_WITH_NESTED_DEF, root, min_statements=3)
    plan = plan_dedup_total_return(root, block)
    assert not plan.ok
    assert any("nested function" in b for b in plan.blockers)
    assert not plan.new_contents


# ──────────────────────────────────────────────────────────────────────────
# BLOCK: differing data-flow signatures across occurrences.
# ──────────────────────────────────────────────────────────────────────────

def test_differing_signatures_block(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _SIG_DIVERGE)
    blocks = find_duplicates(root, min_statements=4, min_occurrences=2)
    assert blocks
    plan = plan_dedup_total_return(root, blocks[0])
    assert not plan.ok, "divergent live-in must block"
    assert any("signature" in b or "data-flow" in b for b in plan.blockers)
    assert not plan.new_contents


# The identical 4-statement block reads `k`. In alpha `k` is a PARAMETER, so it
# is live_in (a helper param); in beta `k` is a module GLOBAL (not a param, not
# assigned before the block), so it is NOT live_in → the two copies would need
# different helper signatures → the plan must block.
_SIG_DIVERGE = '''\
k = 7  # module global referenced by beta (alpha takes `k` as a parameter)


def alpha(cond, k):
    a = k + 1
    b = a + 1
    if cond:
        return a
    return b


def beta(cond):
    a = k + 1
    b = a + 1
    if cond:
        return a
    return b
'''


# ──────────────────────────────────────────────────────────────────────────
# Determinism & robustness.
# ──────────────────────────────────────────────────────────────────────────

def test_plan_is_deterministic(tmp_path):
    root = tmp_path
    _write(root, "pkg/mod.py", _GUARD_RETURN)
    block = find_duplicates(root, min_statements=4, min_occurrences=2)[0]
    p1 = plan_dedup_total_return(root, block)
    p2 = plan_dedup_total_return(root, block)
    assert p1.ok and p2.ok
    assert p1.new == p2.new
    assert p1.new_contents == p2.new_contents
    assert p1.edits_by_file == p2.edits_by_file


def test_emitted_source_always_reparses(tmp_path):
    root = tmp_path
    _write(root, "pkg/mod.py", _GUARD_RETURN)
    block = find_duplicates(root, min_statements=4, min_occurrences=2)[0]
    plan = plan_dedup_total_return(root, block)
    assert plan.ok
    for src in plan.new_contents.values():
        ast.parse(src)  # never emits unparseable source


def test_fewer_than_two_occurrences_blocks(tmp_path):
    block = DuplicateBlock(fingerprint="x", lines=2, occurrences=["mod.py:1"])
    plan = plan_dedup_total_return(tmp_path, block)
    assert not plan.ok
    assert any("two occurrences" in b for b in plan.blockers)


def test_zero_statements_blocks(tmp_path):
    block = DuplicateBlock(fingerprint="x", lines=0,
                           occurrences=["mod.py:1", "mod.py:5"])
    plan = plan_dedup_total_return(tmp_path, block)
    assert not plan.ok
    assert any("no statements" in b for b in plan.blockers)


def test_unreadable_module_blocks(tmp_path):
    block = DuplicateBlock(fingerprint="x", lines=2,
                           occurrences=["missing.py:1", "missing.py:5"])
    plan = plan_dedup_total_return(tmp_path, block)
    assert not plan.ok
    assert any("cannot read" in b for b in plan.blockers)
