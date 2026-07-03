"""Tests for the dedup guarded-return transform (sentinel projection).

This covers the LAST control-flow rung of the dedup family: an EXACT-duplicate
block with a guard ``return`` on some path AND a reachable fall-through — the
shape dedup_extract (plain/tail) and dedup_total_return (always-returns) both
refuse. The run lifts verbatim into a helper whose appended last line returns a
fresh module-level sentinel; each copy becomes a call + sentinel guard, plus a
live-out rebind when locals project out. Everything else BLOCKS. The suite is
exhaustive by intent — this is high-risk, so correctness over coverage.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.dedup import DuplicateBlock, find_duplicates
from app.execution.dedup_guarded_return import (
    _definitely_assigned,
    _guarded_return_reason,
    plan_dedup_guarded_return,
)


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
# _definitely_assigned — the projection-safety rule, unit-tested in isolation.
# ──────────────────────────────────────────────────────────────────────────

def test_definitely_assigned_direct_assign_counts():
    stmts = _parse_stmts("def f():\n    a = 1\n    b, c = 2, 3\n")
    assert _definitely_assigned(stmts) == {"a", "b", "c"}


def test_definitely_assigned_augassign_and_annassign_count():
    stmts = _parse_stmts("def f(a):\n    a += 1\n    b: int = 2\n")
    assert _definitely_assigned(stmts) == {"a", "b"}


def test_definitely_assigned_conditional_binding_does_not_count():
    stmts = _parse_stmts(
        "def f(cond):\n"
        "    if cond:\n"
        "        a = 1\n"
        "    b = 2\n")
    assert _definitely_assigned(stmts) == {"b"}


def test_definitely_assigned_loop_target_does_not_count():
    # Zero iterations skip the binding entirely.
    stmts = _parse_stmts(
        "def f(items):\n"
        "    for it in items:\n"
        "        pass\n"
        "    done = True\n")
    assert _definitely_assigned(stmts) == {"done"}


def test_definitely_assigned_bare_annassign_does_not_count():
    # `x: int` with no value binds nothing at runtime.
    stmts = _parse_stmts("def f():\n    x: int\n    y = 1\n")
    assert _definitely_assigned(stmts) == {"y"}


# ──────────────────────────────────────────────────────────────────────────
# Positive: live_out == [] — guard return + side-effect fall-through.
# ──────────────────────────────────────────────────────────────────────────

_SIDE_EFFECT = '''\
def alpha(cache, key, log):
    if key in cache:
        return cache[key]
    cache[key] = 1
    cache["total"] = len(cache)
    log.append("alpha-miss")


def beta(cache, key, log):
    if key in cache:
        return cache[key]
    cache[key] = 1
    cache["total"] = len(cache)
    log.append("beta-miss")
'''


def test_guard_with_fallthrough_lifts_with_simple_sentinel(tmp_path):
    root = tmp_path
    _write(root, "pkg/mod.py", _SIDE_EFFECT)
    blocks = find_duplicates(root, min_statements=3, min_occurrences=2)
    assert blocks, "the detector should find the shared guarded block"
    plan = plan_dedup_guarded_return(root, blocks[0])
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    new_src = plan.new_contents["pkg/mod.py"]

    tree = ast.parse(new_src)  # re-parses
    helper = plan.new
    assert helper in [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    # A fresh module-level sentinel, guarded at BOTH call sites (simple form).
    assert new_src.count("= object()") == 1
    assert new_src.count("is not") == 2
    # The duplicated body is no longer literally repeated.
    assert new_src.count('cache["total"] = len(cache)') == 1

    # Exec-equivalence on the HIT path (guard returns) and the MISS path
    # (falls through into the differing tails), including side effects.
    before = _exec_module(_SIDE_EFFECT)
    after = _exec_module(new_src)
    for fn in ("alpha", "beta"):
        hit_cache = {"k": 42}
        assert before[fn](dict(hit_cache), "k", []) == after[fn](dict(hit_cache), "k", [])
        b_cache, b_log = {}, []
        a_cache, a_log = {}, []
        assert before[fn](b_cache, "k", b_log) == after[fn](a_cache, "k", a_log)
        assert b_cache == a_cache  # {"k": 1, "total": ...} mutated identically
        assert b_log == a_log      # the per-function tail still runs


# ──────────────────────────────────────────────────────────────────────────
# Positive: live_out projection — THE witnessed guard-prelude shape.
# ──────────────────────────────────────────────────────────────────────────

_GUARD_PRELUDE = '''\
def build_a(data, key):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 2
    return f"A:{name}:{size}"


def build_b(data, key):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 2
    return f"B:{size}:{name}"
'''


def test_guard_prelude_projects_live_out_locals(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _GUARD_PRELUDE)
    blocks = find_duplicates(root, min_statements=4, min_occurrences=2)
    assert blocks, "the detector should find the shared prelude"
    plan = plan_dedup_guarded_return(root, blocks[0])
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]

    ast.parse(new_src)
    # The projection form: tagged-tuple fall-through + a rebind at each site.
    assert new_src.count("= object()") == 1
    assert new_src.count("name, size =") == 2  # live-out rebinds (sorted names)
    assert new_src.count("item = data.get(key)") == 1  # body collapsed

    before = _exec_module(_GUARD_PRELUDE)
    after = _exec_module(new_src)
    data = {"k": {"name": "n", "size": 3}}
    for fn in ("build_a", "build_b"):
        assert before[fn](data, "k") == after[fn](data, "k")      # fall-through
        assert before[fn](data, "nope") == after[fn](data, "nope")  # guard hit
    assert after["build_a"](data, "k") == "A:n:6"
    assert after["build_b"](data, "k") == "B:6:n"
    assert after["build_a"](data, "nope") == "missing"


_SINGLE_OUT = '''\
def calc_a(raw):
    if not raw:
        return 0
    total = sum(raw)
    if total < 0:
        return -1
    scaled = total * 10
    return scaled + 1


def calc_b(raw):
    if not raw:
        return 0
    total = sum(raw)
    if total < 0:
        return -1
    scaled = total * 10
    return scaled - 1
'''


def test_single_live_out_uses_tuple_unpack(tmp_path):
    # Arity-1 projection must stay a real tuple unpack — `(scaled,) = _res[1]`.
    root = tmp_path
    _write(root, "mod.py", _SINGLE_OUT)
    blocks = find_duplicates(root, min_statements=4, min_occurrences=2)
    assert blocks
    plan = plan_dedup_guarded_return(root, blocks[0])
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    ast.parse(new_src)
    assert new_src.count("(scaled,) =") == 2

    before = _exec_module(_SINGLE_OUT)
    after = _exec_module(new_src)
    for raw in ([], [3, 4], [-9, 1]):
        assert before["calc_a"](raw) == after["calc_a"](raw)
        assert before["calc_b"](raw) == after["calc_b"](raw)
    assert after["calc_a"]([3, 4]) == 71
    assert after["calc_b"]([3, 4]) == 69


# ──────────────────────────────────────────────────────────────────────────
# Positive: a BARE `return` (None) on the guard path stays distinguishable
# from the fall-through — None is not the sentinel.
# ──────────────────────────────────────────────────────────────────────────

_BARE_RETURN = '''\
def go_a(flag, out):
    if flag:
        return
    out.append(1)
    out.append(2)


def go_b(flag, out):
    if flag:
        return
    out.append(1)
    out.append(2)
    out.append("b-tail")
'''


def test_bare_return_none_is_not_confused_with_fallthrough(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _BARE_RETURN)
    blocks = find_duplicates(root, min_statements=3, min_occurrences=2)
    assert blocks
    plan = plan_dedup_guarded_return(root, blocks[0])
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]

    before = _exec_module(_BARE_RETURN)
    after = _exec_module(new_src)
    for fn in ("go_a", "go_b"):
        for flag in (True, False):
            b_out: list = []
            a_out: list = []
            assert before[fn](flag, b_out) == after[fn](flag, a_out)  # both None
            assert b_out == a_out
    # Concretely: the guard path leaves `out` untouched; the fall-through
    # path appends — and go_b's own tail still runs after the shared block.
    probe: list = []
    after["go_b"](False, probe)
    assert probe == [1, 2, "b-tail"]
    probe2: list = []
    after["go_b"](True, probe2)
    assert probe2 == []


# ──────────────────────────────────────────────────────────────────────────
# Positive: cross-file — the import carries BOTH the sentinel and the helper.
# ──────────────────────────────────────────────────────────────────────────

_CROSS_A = '''\
def render_a(data, key):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 2
    return "A" + name + str(size)
'''

_CROSS_B = '''\
def render_b(data, key):
    item = data.get(key)
    if item is None:
        return "missing"
    name = item["name"]
    size = item["size"] * 2
    return "B" + str(size) + name
'''


def test_cross_file_imports_sentinel_and_helper(tmp_path):
    root = tmp_path
    _write(root, "a.py", _CROSS_A)
    _write(root, "b.py", _CROSS_B)
    blocks = find_duplicates(root, min_statements=4, min_occurrences=2)
    assert blocks, "the detector should find the cross-file block"
    plan = plan_dedup_guarded_return(root, blocks[0])
    assert plan.ok, f"blockers={plan.blockers}"
    helper = plan.new
    definer = plan.defined_in
    importer = "b.py" if definer == "a.py" else "a.py"
    def_src = plan.new_contents[definer]
    imp_src = plan.new_contents[importer]
    assert f"def {helper}(" in def_src
    assert def_src.count("= object()") == 1
    # The importing module pulls BOTH names in one import line.
    assert "import" in imp_src and helper in imp_src and "_MISS" in imp_src
    assert "= object()" not in imp_src
    for src in (def_src, imp_src):
        ast.parse(src)


# ──────────────────────────────────────────────────────────────────────────
# Regression (H4 mirror): same-file copy ABOVE the first-in-emit-order
# container — the insert-index rebase must use the GUARD's call-line count.
# ──────────────────────────────────────────────────────────────────────────

_ABOVE_CONTAINER = '''\
def bar(x, log):
    if x < 0:
        return "neg"
    log.append(x)
    log.append(x + 1)


def foo(x, log):
    s0 = x + 100
    if x < 0:
        return "neg"
    log.append(x)
    log.append(x + 1)
    log.append(s0)
'''


def test_same_file_copy_above_container_keeps_helper_at_module_level(tmp_path):
    _write(tmp_path, "mod.py", _ABOVE_CONTAINER)
    # bar's block starts at line 2 (topmost); foo's at line 10. Emit order
    # [foo, bar] makes `first` the BOTTOM function, so bar's replaced span sits
    # above foo's container and the anchor must rebase by 3-call-lines minus
    # the span height — the guarded-return variant of the H4 regression.
    block = DuplicateBlock(fingerprint="x", lines=3,
                           occurrences=["mod.py:10", "mod.py:2"])
    plan = plan_dedup_guarded_return(tmp_path, block)
    assert plan.ok, f"expected a clean plan, blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]

    tree = ast.parse(new_src)
    helper = plan.new
    top_defs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert helper in top_defs, (
        f"helper must be a top-level def, not nested; module defs={top_defs}\n"
        f"--- emitted ---\n{new_src}")
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef):
            assert not any(isinstance(n, ast.FunctionDef)
                           for n in ast.walk(fn) if n is not fn), (
                f"a function ended up nested inside {fn.name}:\n{new_src}")

    before = _exec_module(_ABOVE_CONTAINER)
    after = _exec_module(new_src)
    for x in (-5, 0, 10):
        b_log: list = []
        a_log: list = []
        assert before["foo"](x, b_log) == after["foo"](x, a_log)
        assert b_log == a_log
        b_log, a_log = [], []
        assert before["bar"](x, b_log) == after["bar"](x, a_log)
        assert b_log == a_log
    probe: list = []
    after["foo"](10, probe)
    assert probe == [10, 11, 110]  # foo's own tail (s0) survived the lift


# ──────────────────────────────────────────────────────────────────────────
# BLOCK: the siblings' shapes are refused with a pointer to whose job it is.
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


def test_plain_block_is_dedup_extracts_job(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _PLAIN_TAIL)
    blocks = find_duplicates(root, min_statements=5, min_occurrences=2)
    assert blocks
    plan = plan_dedup_guarded_return(root, blocks[0])
    assert not plan.ok
    assert any("no `return`" in b and "dedup_extract" in b for b in plan.blockers)
    assert not plan.new_contents


_TOTAL_RETURN = '''\
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


def test_total_return_block_is_the_siblings_job(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _TOTAL_RETURN)
    blocks = find_duplicates(root, min_statements=4, min_occurrences=2)
    assert blocks
    plan = plan_dedup_guarded_return(root, blocks[0])
    assert not plan.ok
    assert any("dedup-total-return" in b for b in plan.blockers)
    assert not plan.new_contents


# ──────────────────────────────────────────────────────────────────────────
# BLOCK: hazards — yield, escaping break, super/__class__, del, unbound out.
# ──────────────────────────────────────────────────────────────────────────

def _block_for(src: str, root: Path, *, min_statements: int) -> DuplicateBlock:
    _write(root, "mod.py", src)
    blocks = find_duplicates(root, min_statements=min_statements, min_occurrences=2)
    assert blocks, "the detector should still see the identical block"
    return blocks[0]


_WITH_YIELD = '''\
def alpha(items, flag):
    if flag:
        return
    for it in items:
        yield it
    print("a")


def beta(items, flag):
    if flag:
        return
    for it in items:
        yield it
    print("b")
'''


def test_yield_in_block_is_blocked(tmp_path):
    plan = plan_dedup_guarded_return(
        tmp_path, _block_for(_WITH_YIELD, tmp_path, min_statements=2))
    assert not plan.ok
    assert any("yield" in b for b in plan.blockers)


def test_escaping_break_is_blocked_at_the_reason_rail():
    # The detector only windows over TOP-LEVEL fn.body statements, so a run
    # whose `break` escapes it can never arrive from find_duplicates (a
    # top-level break without its loop is a syntax error) — the rail is
    # defense-in-depth for hand-crafted occurrences. Unit-test it directly on
    # the loop-body run [`if it: break`, `return out`]: the break's `for` is
    # OUTSIDE the run.
    src = ("def f(items, out):\n"
           "    for it in items:\n"
           "        if it:\n"
           "            break\n"
           "        return out\n")
    fn = ast.parse(src).body[0]
    run = fn.body[0].body
    reason = _guarded_return_reason(run)
    assert reason is not None and "break" in reason


_WITH_SUPER = '''\
class A:
    def run(self, ready):
        if not ready:
            return None
        base = super().run(ready)
        self.log.append(base)


class B:
    def run(self, ready):
        if not ready:
            return None
        base = super().run(ready)
        self.log.append(base)
'''


def test_zero_arg_super_is_blocked(tmp_path):
    # `super()` compiles against the method's implicit __class__ cell; a
    # module-level helper has none — it would re-parse fine and break at
    # runtime, exactly what the rail refuses.
    plan = plan_dedup_guarded_return(
        tmp_path, _block_for(_WITH_SUPER, tmp_path, min_statements=3))
    assert not plan.ok
    assert any("super" in b and "class cell" in b for b in plan.blockers)


_WITH_DEL = '''\
def alpha(x, out):
    if x < 0:
        return None
    tmp = x + 1
    del tmp
    out.append(x)


def beta(x, out):
    if x < 0:
        return None
    tmp = x + 1
    del tmp
    out.append(x)
'''


def test_del_in_block_is_blocked(tmp_path):
    plan = plan_dedup_guarded_return(
        tmp_path, _block_for(_WITH_DEL, tmp_path, min_statements=4))
    assert not plan.ok
    assert any("del" in b for b in plan.blockers)


_CONDITIONAL_OUT = '''\
def fa(cond, flag):
    if not cond:
        return None
    if flag:
        val = 1
    out = 7
    return val + out


def fb(cond, flag):
    if not cond:
        return None
    if flag:
        val = 1
    out = 7
    return val - out
'''


def test_conditionally_bound_live_out_is_blocked(tmp_path):
    # `val` is live-out but bound only under `if flag:` — the helper's
    # projection line would raise UnboundLocalError on a path where the
    # ORIGINAL only raised later (or never). Definite assignment refuses it.
    plan = plan_dedup_guarded_return(
        tmp_path, _block_for(_CONDITIONAL_OUT, tmp_path, min_statements=3))
    assert not plan.ok
    assert any("val" in b and "unbound" in b for b in plan.blockers)


_SIG_DIVERGE = '''\
k = 7  # module global referenced by beta (alpha takes `k` as a parameter)


def alpha(cond, k, log):
    a = k + 1
    if cond:
        return a
    b = a + 1
    log.append(b)


def beta(cond, log):
    a = k + 1
    if cond:
        return a
    b = a + 1
    log.append(b)
'''


def test_differing_signatures_block(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _SIG_DIVERGE)
    blocks = find_duplicates(root, min_statements=4, min_occurrences=2)
    assert blocks
    plan = plan_dedup_guarded_return(root, blocks[0])
    assert not plan.ok, "divergent live-in must block"
    assert any("signature" in b or "data-flow" in b for b in plan.blockers)


# ──────────────────────────────────────────────────────────────────────────
# Fresh-name discipline: sentinel and result names dodge live bindings.
# ──────────────────────────────────────────────────────────────────────────

_SENTINEL_TAKEN = '''\
_SHARED_1_MISS = 3


def alpha(cache, key, log):
    if key in cache:
        return cache[key]
    cache[key] = 1
    cache["total"] = len(cache)
    log.append("alpha-miss")


def beta(cache, key, log):
    if key in cache:
        return cache[key]
    cache[key] = 1
    cache["total"] = len(cache)
    log.append("beta-miss")
'''


def test_sentinel_name_collision_falls_to_next_free(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _SENTINEL_TAKEN)
    blocks = find_duplicates(root, min_statements=3, min_occurrences=2)
    plan = plan_dedup_guarded_return(root, blocks[0])
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    assert "_SHARED_1_MISS_2 = object()" in new_src
    assert new_src.count("_SHARED_1_MISS = 3") == 1  # the live binding untouched


_RVAR_TAKEN = '''\
def alpha(cache, key, log):
    if key in cache:
        return cache[key]
    cache[key] = 1
    cache["total"] = len(cache)
    _res = 1
    log.append(_res)


def beta(cache, key, log):
    if key in cache:
        return cache[key]
    cache[key] = 1
    cache["total"] = len(cache)
    _res = 2
    log.append(_res)
'''


def test_result_name_collision_falls_to_next_free(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _RVAR_TAKEN)
    blocks = find_duplicates(root, min_statements=3, min_occurrences=2)
    assert blocks
    block = next(b for b in blocks if b.lines == 3)
    plan = plan_dedup_guarded_return(root, block)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    assert "_res_2 =" in new_src and "if _res_2 is not" in new_src

    before = _exec_module(_RVAR_TAKEN)
    after = _exec_module(new_src)
    b_log: list = []
    a_log: list = []
    assert before["alpha"]({}, "k", b_log) == after["alpha"]({}, "k", a_log)
    assert b_log == a_log


# ──────────────────────────────────────────────────────────────────────────
# W97 rails: the emitted sentinel/guard must resolve to the REAL builtins.
# A shadow of `object`/`type`/`tuple`/`len` — module level or any enclosing
# function's local/param — silently changes the emit's meaning (a forgeable
# sentinel via `object = lambda: None`; `type(_res)` calling a parameter).
# ──────────────────────────────────────────────────────────────────────────

_OBJECT_SHADOW = '''\
object = lambda: None


def fa(x, log):
    if x < 0:
        return
    log.append(x)
    log.append(x + 1)


def fb(x, log):
    if x < 0:
        return
    log.append(x)
    log.append(x + 1)
    log.append("b")
'''


def test_module_level_object_shadow_blocks(tmp_path):
    # The verified repro: with `object = lambda: None` the sentinel is None,
    # indistinguishable from a bare-return guard path (f(-1): None -> 'fell').
    _write(tmp_path, "mod.py", _OBJECT_SHADOW)
    block = DuplicateBlock(fingerprint="x", lines=3,
                           occurrences=["mod.py:5", "mod.py:12"])
    plan = plan_dedup_guarded_return(tmp_path, block)
    assert not plan.ok
    assert any("`object` is shadowed by a module-level or enclosing-function "
               "binding" in b and "not the builtin" in b
               for b in plan.blockers)
    assert not plan.new_contents


_TYPE_PARAM_SHADOW = '''\
def fa(type, x):
    if x < 0:
        return None
    y = x + 1
    print(y)
    return y + type(x)


def fb(type, x):
    if x < 0:
        return None
    y = x + 1
    print(y)
    return y - type(x)
'''


def test_type_parameter_shadow_blocks(tmp_path):
    # The verified repro: a parameter named `type` makes the emitted 4-line
    # guard call the PARAMETER (f(int, 3): 8 -> TypeError).
    _write(tmp_path, "mod.py", _TYPE_PARAM_SHADOW)
    block = DuplicateBlock(fingerprint="x", lines=3,
                           occurrences=["mod.py:2", "mod.py:10"])
    plan = plan_dedup_guarded_return(tmp_path, block)
    assert not plan.ok
    assert any("`type` is shadowed" in b and "sentinel/guard" in b
               for b in plan.blockers)
    assert not plan.new_contents


_LEN_LOCAL_SHADOW = '''\
def fa(vals, x):
    len = 3
    if x < 0:
        return None
    y = x + 1
    vals.append(y)
    return y + len


def fb(vals, x):
    len = 3
    if x < 0:
        return None
    y = x + 1
    vals.append(y)
    return y - len
'''


def test_len_local_shadow_blocks(tmp_path):
    _write(tmp_path, "mod.py", _LEN_LOCAL_SHADOW)
    block = DuplicateBlock(fingerprint="x", lines=3,
                           occurrences=["mod.py:3", "mod.py:12"])
    plan = plan_dedup_guarded_return(tmp_path, block)
    assert not plan.ok
    assert any("`len` is shadowed" in b for b in plan.blockers)
    assert not plan.new_contents


_BUILTIN_READS = '''\
def fa(cache, key, log):
    if key in cache:
        return cache[key]
    cache[key] = len(str(key))
    log.append(type(key).__name__)


def fb(cache, key, log):
    if key in cache:
        return cache[key]
    cache[key] = len(str(key))
    log.append(type(key).__name__)
    log.append("b")
'''


def test_builtin_reads_without_shadow_still_land(tmp_path):
    # Negative control: READING `len`/`type`/`str` (no binding anywhere) is
    # exactly the sound class — the rail must not over-refuse it.
    _write(tmp_path, "mod.py", _BUILTIN_READS)
    block = DuplicateBlock(fingerprint="x", lines=3,
                           occurrences=["mod.py:2", "mod.py:9"])
    plan = plan_dedup_guarded_return(tmp_path, block)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    assert "= object()" in new_src

    before = _exec_module(_BUILTIN_READS)
    after = _exec_module(new_src)
    for fn in ("fa", "fb"):
        b_cache, b_log = {}, []
        a_cache, a_log = {}, []
        assert before[fn](b_cache, "k", b_log) == after[fn](a_cache, "k", a_log)
        assert b_cache == a_cache and b_log == a_log
        hit = {"k": 42}
        assert before[fn](dict(hit), "k", []) == after[fn](dict(hit), "k", [])


# ──────────────────────────────────────────────────────────────────────────
# W97 rail: the sentinel name must be free in the ENCLOSING FUNCTIONS too
# (mirroring _free_result_name's scan) — a same-named local would hijack the
# guard's identity test.
# ──────────────────────────────────────────────────────────────────────────

_SENTINEL_LOCAL = '''\
def alpha(cache, key, log):
    _SHARED_1_MISS = "hot"
    if key in cache:
        return cache[key]
    cache[key] = 1
    log.append("miss")
    return _SHARED_1_MISS


def beta(cache, key, log):
    _SHARED_1_MISS = "hot"
    if key in cache:
        return cache[key]
    cache[key] = 1
    log.append("miss")
    return _SHARED_1_MISS + "!"
'''


def test_sentinel_name_used_as_function_local_falls_to_next_free(tmp_path):
    # The verified repro: with a fn-LOCAL `_SHARED_1_MISS`, the emitted guard
    # compared against the local ("cache"/"hot"), so genuine fall-through
    # returned the raw projection tuple. The sentinel scan now mirrors
    # _free_result_name and dodges every enclosing-function Name/arg.
    _write(tmp_path, "mod.py", _SENTINEL_LOCAL)
    block = DuplicateBlock(fingerprint="x", lines=3,
                           occurrences=["mod.py:3", "mod.py:12"])
    plan = plan_dedup_guarded_return(tmp_path, block)
    assert plan.ok, f"blockers={plan.blockers}"
    new_src = plan.new_contents["mod.py"]
    assert "_SHARED_1_MISS_2 = object()" in new_src
    assert "is not _SHARED_1_MISS_2" in new_src
    assert new_src.count('_SHARED_1_MISS = "hot"') == 2  # locals untouched

    before = _exec_module(_SENTINEL_LOCAL)
    after = _exec_module(new_src)
    for fn in ("alpha", "beta"):
        b_cache, b_log = {}, []
        a_cache, a_log = {}, []
        assert before[fn](b_cache, "k", b_log) == after[fn](a_cache, "k", a_log)
        assert b_cache == a_cache and b_log == a_log
        hit = {"k": 42}
        assert before[fn](dict(hit), "k", []) == after[fn](dict(hit), "k", [])


# ──────────────────────────────────────────────────────────────────────────
# Determinism & robustness.
# ──────────────────────────────────────────────────────────────────────────

def test_plan_is_deterministic(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _GUARD_PRELUDE)
    block = find_duplicates(root, min_statements=4, min_occurrences=2)[0]
    p1 = plan_dedup_guarded_return(root, block)
    p2 = plan_dedup_guarded_return(root, block)
    assert p1.ok and p2.ok
    assert p1.new == p2.new
    assert p1.new_contents == p2.new_contents
    assert p1.edits_by_file == p2.edits_by_file


def test_emitted_source_always_reparses(tmp_path):
    root = tmp_path
    _write(root, "mod.py", _GUARD_PRELUDE)
    block = find_duplicates(root, min_statements=4, min_occurrences=2)[0]
    plan = plan_dedup_guarded_return(root, block)
    assert plan.ok
    for src in plan.new_contents.values():
        ast.parse(src)  # never emits unparseable source


def test_fewer_than_two_occurrences_blocks(tmp_path):
    block = DuplicateBlock(fingerprint="x", lines=2, occurrences=["mod.py:1"])
    plan = plan_dedup_guarded_return(tmp_path, block)
    assert not plan.ok
    assert any("two occurrences" in b for b in plan.blockers)


def test_zero_statements_blocks(tmp_path):
    block = DuplicateBlock(fingerprint="x", lines=0,
                           occurrences=["mod.py:1", "mod.py:5"])
    plan = plan_dedup_guarded_return(tmp_path, block)
    assert not plan.ok
    assert any("no statements" in b for b in plan.blockers)


def test_unreadable_module_blocks(tmp_path):
    block = DuplicateBlock(fingerprint="x", lines=2,
                           occurrences=["missing.py:1", "missing.py:5"])
    plan = plan_dedup_guarded_return(tmp_path, block)
    assert not plan.ok
    assert any("cannot read" in b for b in plan.blockers)
