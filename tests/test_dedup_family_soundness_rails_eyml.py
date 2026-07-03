"""Regression suite for the dedup family's W97 soundness rails.

An adversarial red-team (independently skeptic-verified) produced repros where
the exact-duplicate landers — dedup_extract, dedup_total_return,
dedup_guarded_return — ACCEPTED unsound blocks and shipped silently-wrong (or
import-breaking) code. Each finding is frozen here as: the adversarial fixture
now produces a plan with a BLOCKER and empty ``new_contents`` (blocker text
quoted), plus a negative control proving the neighbouring sound shape still
lands. Strictly refuse-direction: no rail ever widens what lands.

Rails covered here (family-wide, shared via ``_dedup_helpers``):
  1. occurrence identity — stale detector lines must not rewrite DIFFERENT
     code with the first copy's logic;
  2. cross-module free-global rebind — a run reading a name that is neither
     live-in, run-bound, nor a builtin must not collapse across modules;
  3. multi-line strings — ``_reindent`` rewrites their CONTENTS (refuse-first);
  4. pre-run closures — a nested def/lambda outside the run reading a
     run-store keeps reading the now-helper-internal name;
  5. invisible non-``Name`` bindings — ``import … as`` / ``except … as`` /
     match captures outside the run are invisible to live-in;
  9. ``async for``/``async with`` — no ``Await`` child, and the broken sync
     emit still PARSES (compile/import is what breaks);
  +  reflection — ``globals``/``locals``/``vars``/``eval``/``exec``/
     ``sys._getframe`` observe the executing scope, which the lift changes.

The guarded-return-only rails (shadowed ``object``/``type``/``tuple``/``len``
in the emit; sentinel-name freeness inside enclosing functions) live in
``tests/test_dedup_guarded_return.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.dedup import DuplicateBlock
from app.execution._dedup_helpers import (
    _bound_names,
    _invisible_bound_names,
    _multiline_string_reason,
    occurrence_rail_reason,
)
from app.execution.dedup_extract import plan_dedup_extract
from app.execution.dedup_guarded_return import plan_dedup_guarded_return
from app.execution.dedup_total_return import plan_dedup_total_return


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _block(occurrences: list[str], lines: int) -> DuplicateBlock:
    return DuplicateBlock(fingerprint="x", lines=lines, occurrences=occurrences)


def _assert_blocked(plan, *needles: str) -> None:
    """The refuse-direction contract: a blocker carrying every ``needle``,
    and NO rewrite output at all."""
    assert not plan.ok, f"expected a blocked plan, got new={plan.new_contents}"
    assert any(all(n in b for n in needles) for b in plan.blockers), (
        f"expected a blocker containing {needles!r}, got {plan.blockers}")
    assert not plan.new_contents


# ══════════════════════════════════════════════════════════════════════════
# Rail 1 — occurrence identity (stale/shifted detector lines).
# ══════════════════════════════════════════════════════════════════════════

_IDENTITY_GUARDED = '''\
def f(x):
    if x < 0:
        return -1
    y = x + 1
    print("f", y)
    return y


def g(x):
    if x > 100:
        return 999
    y = x * 2
    print("g", y)
    return y
'''


def test_identity_guarded_different_runs_block(tmp_path):
    # The verified repro: two STRUCTURALLY DIFFERENT guarded runs with
    # coincident data-flow signatures. The old planner rewrote g's body with
    # f's logic (g(5): 10 -> 6). Now: identity blocker, no output.
    _write(tmp_path, "m.py", _IDENTITY_GUARDED)
    plan = plan_dedup_guarded_return(
        tmp_path, _block(["m.py:2", "m.py:10"], 3))
    _assert_blocked(plan, "occurrence is not structurally identical",
                    "stale detector lines would rewrite different code")


_IDENTITY_TOTAL = '''\
def f(x):
    a = x + 1
    return a


def g(x):
    a = x * 2
    return a
'''


def test_identity_total_return_different_runs_block(tmp_path):
    _write(tmp_path, "m.py", _IDENTITY_TOTAL)
    plan = plan_dedup_total_return(tmp_path, _block(["m.py:2", "m.py:7"], 2))
    _assert_blocked(plan, "occurrence is not structurally identical")


_IDENTITY_EXTRACT = '''\
def f(x):
    a = x + 1
    b = a * 2
    print(b)


def g(x):
    a = x - 1
    b = a * 3
    print(b)
'''


def test_identity_extract_different_runs_block(tmp_path):
    _write(tmp_path, "m.py", _IDENTITY_EXTRACT)
    plan = plan_dedup_extract(tmp_path, _block(["m.py:2", "m.py:8"], 3))
    _assert_blocked(plan, "occurrence is not structurally identical")


_IDENTITY_CLEAN = '''\
def f(x):
    if x < 0:
        return -1
    y = x + 1
    print("run", y)
    return y


def g(x):
    if x < 0:
        return -1
    y = x + 1
    print("run", y)
    return y + 100
'''


def test_identity_negative_identical_runs_still_land(tmp_path):
    # Negative control: genuinely identical runs pass the identity rail and
    # land exactly as before.
    _write(tmp_path, "m.py", _IDENTITY_CLEAN)
    plan = plan_dedup_guarded_return(
        tmp_path, _block(["m.py:2", "m.py:10"], 3))
    assert plan.ok, f"blockers={plan.blockers}"
    ast.parse(plan.new_contents["m.py"])


# ══════════════════════════════════════════════════════════════════════════
# Rail 2 — cross-module free-global rebind.
# ══════════════════════════════════════════════════════════════════════════

_REBIND_G = '''\
LIMIT = {limit}


def {fn}(x):
    if x > LIMIT:
        return "big"
    x = x + 1
    print(x)
    return x
'''


def test_rebind_guarded_cross_module_global_blocks(tmp_path):
    # The verified repro: a.py LIMIT=10, b.py LIMIT=1000 — the lifted helper
    # would read the DEFINING module's LIMIT for both (b.fb(50): 51 -> 'big').
    _write(tmp_path, "a.py", _REBIND_G.format(limit=10, fn="fa"))
    _write(tmp_path, "b.py", _REBIND_G.format(limit=1000, fn="fb"))
    plan = plan_dedup_guarded_return(tmp_path, _block(["a.py:5", "b.py:5"], 3))
    _assert_blocked(
        plan, "`LIMIT`",
        "free module-global would rebind to the defining module's value")


_REBIND_T = '''\
SCALE = {scale}


def {fn}(x):
    y = x * SCALE
    if y > 10:
        return y
    return -y
'''


def test_rebind_total_return_cross_module_global_blocks(tmp_path):
    _write(tmp_path, "a.py", _REBIND_T.format(scale=2, fn="ta"))
    _write(tmp_path, "b.py", _REBIND_T.format(scale=50, fn="tb"))
    plan = plan_dedup_total_return(tmp_path, _block(["a.py:5", "b.py:5"], 3))
    _assert_blocked(
        plan, "`SCALE`",
        "free module-global would rebind to the defining module's value")


_REBIND_E = '''\
LIMIT = {limit}


def {fn}(x):
    a = x + LIMIT
    b = a * 2
    c = b + 3
    print(c)
'''


def test_rebind_extract_cross_module_global_blocks(tmp_path):
    _write(tmp_path, "a.py", _REBIND_E.format(limit=10, fn="pa"))
    _write(tmp_path, "b.py", _REBIND_E.format(limit=1000, fn="pb"))
    plan = plan_dedup_extract(tmp_path, _block(["a.py:5", "b.py:5"], 4))
    _assert_blocked(
        plan, "`LIMIT`",
        "free module-global would rebind to the defining module's value")


_CLEAN_CROSS_G = '''\
def {fn}(x, log):
    if x < 0:
        return "neg"
    y = x + 1
    log.append(str(y))
'''


def test_rebind_negative_cross_module_params_and_builtins_land(tmp_path):
    # Negative control: a cross-module run reading only params, run-bound
    # names, and builtins (`str`) still lands with helper + import.
    _write(tmp_path, "a.py", _CLEAN_CROSS_G.format(fn="fa"))
    _write(tmp_path, "b.py", _CLEAN_CROSS_G.format(fn="fb"))
    plan = plan_dedup_guarded_return(tmp_path, _block(["a.py:2", "b.py:2"], 3))
    assert plan.ok, f"blockers={plan.blockers}"
    assert set(plan.new_contents) == {"a.py", "b.py"}
    for src in plan.new_contents.values():
        ast.parse(src)


_CLEAN_CROSS_T = '''\
def {fn}(x):
    y = x + 1
    if y > 10:
        return y
    return -y
'''


def test_rebind_negative_cross_module_total_return_lands(tmp_path):
    _write(tmp_path, "a.py", _CLEAN_CROSS_T.format(fn="ca"))
    _write(tmp_path, "b.py", _CLEAN_CROSS_T.format(fn="cb"))
    plan = plan_dedup_total_return(tmp_path, _block(["a.py:2", "b.py:2"], 3))
    assert plan.ok, f"blockers={plan.blockers}"
    assert set(plan.new_contents) == {"a.py", "b.py"}


_CLEAN_CROSS_E = '''\
def {fn}(x):
    a = x + 1
    b = a * 2
    c = b + 3
    print(c)
'''


def test_rebind_negative_cross_module_extract_lands(tmp_path):
    _write(tmp_path, "a.py", _CLEAN_CROSS_E.format(fn="pa"))
    _write(tmp_path, "b.py", _CLEAN_CROSS_E.format(fn="pb"))
    plan = plan_dedup_extract(tmp_path, _block(["a.py:2", "b.py:2"], 4))
    assert plan.ok, f"blockers={plan.blockers}"
    assert set(plan.new_contents) == {"a.py", "b.py"}


def test_rebind_negative_single_module_global_read_untouched(tmp_path):
    # Negative control: the SAME free-global shape in ONE module stays
    # byte-identically landable — the helper never leaves the module that
    # binds the name.
    src = (_REBIND_G.format(limit=10, fn="fa") + "\n\n"
           + _REBIND_G.format(limit=10, fn="fb").split("\n\n\n")[1])
    _write(tmp_path, "m.py", src)
    plan = plan_dedup_guarded_return(
        tmp_path, _block(["m.py:5", "m.py:13"], 3))
    assert plan.ok, f"blockers={plan.blockers}"
    assert "LIMIT" in plan.new_contents["m.py"]


# ══════════════════════════════════════════════════════════════════════════
# Rail 3 — multi-line string constants (refuse-first).
# ══════════════════════════════════════════════════════════════════════════

_MLSTR_G = '''\
def fa(x):
    if x < 0:
        return None
    q = """A
  B
"""
    return len(q)


def fb(x):
    if x < 0:
        return None
    q = """A
  B
"""
    return len(q)
'''


def test_multiline_string_guarded_blocks(tmp_path):
    # The verified repro: _reindent rewrote the STRING's under-indented
    # continuation lines (len 6 -> 12). Refuse-first: any multi-line string
    # constant in the run blocks.
    _write(tmp_path, "m.py", _MLSTR_G)
    plan = plan_dedup_guarded_return(
        tmp_path, _block(["m.py:2", "m.py:11"], 2))
    _assert_blocked(plan, "multi-line string constant",
                    "would rewrite the string's contents")


_MLSTR_T = '''\
def ta(flag):
    msg = """A
  B
"""
    if flag:
        return msg
    return msg.strip()


def tb(flag):
    msg = """A
  B
"""
    if flag:
        return msg
    return msg.strip()
'''


def test_multiline_string_total_return_blocks(tmp_path):
    _write(tmp_path, "m.py", _MLSTR_T)
    plan = plan_dedup_total_return(tmp_path, _block(["m.py:2", "m.py:11"], 3))
    _assert_blocked(plan, "multi-line string constant")


_MLSTR_E = '''\
def pa(x):
    q = """A
  B
"""
    r = len(q) + x
    print(r)


def pb(x):
    q = """A
  B
"""
    r = len(q) + x
    print(r)
'''


def test_multiline_string_extract_blocks(tmp_path):
    _write(tmp_path, "m.py", _MLSTR_E)
    plan = plan_dedup_extract(tmp_path, _block(["m.py:2", "m.py:10"], 3))
    _assert_blocked(plan, "multi-line string constant")


_MLSTR_FSTRING = '''\
def ga(x):
    if x < 0:
        return None
    q = f"""A
{x}
"""
    return len(q)


def gb(x):
    if x < 0:
        return None
    q = f"""A
{x}
"""
    return len(q)
'''


def test_multiline_fstring_guarded_blocks(tmp_path):
    # JoinedStr (f-string) spanning physical lines is the same corruption.
    _write(tmp_path, "m.py", _MLSTR_FSTRING)
    plan = plan_dedup_guarded_return(
        tmp_path, _block(["m.py:2", "m.py:11"], 2))
    _assert_blocked(plan, "multi-line string constant")


_SINGLE_LINE_STR = '''\
def ha(x, log):
    if x < 0:
        return "neg"
    y = "prefix: " + str(x)
    log.append(y)


def hb(x, log):
    if x < 0:
        return "neg"
    y = "prefix: " + str(x)
    log.append(y)
'''


def test_multiline_string_negative_single_line_string_lands(tmp_path):
    _write(tmp_path, "m.py", _SINGLE_LINE_STR)
    plan = plan_dedup_guarded_return(tmp_path, _block(["m.py:2", "m.py:9"], 3))
    assert plan.ok, f"blockers={plan.blockers}"
    assert '"prefix: "' in plan.new_contents["m.py"]


# ══════════════════════════════════════════════════════════════════════════
# Rail 4 — pre-run closure over a run-store.
# ══════════════════════════════════════════════════════════════════════════

_CLOSURE_G = '''\
def f(x):
    get = lambda: y
    if x < 0:
        return None
    y = x + 1
    print(y)
    return get()


def g(x):
    get = lambda: y
    if x < 0:
        return None
    y = x + 1
    print(y)
    return get()
'''


def test_closure_guarded_pre_run_lambda_blocks(tmp_path):
    # The verified repro: live_out misses the closure-only read of `y`, the
    # emitted caller never assigns it, and `lambda: y` raises NameError.
    _write(tmp_path, "m.py", _CLOSURE_G)
    plan = plan_dedup_guarded_return(
        tmp_path, _block(["m.py:3", "m.py:12"], 3))
    _assert_blocked(plan, "`y`", "nested def/lambda outside the range",
                    "now-helper-internal name")


_CLOSURE_E = '''\
def f(x):
    get = lambda: y
    y = x + 1
    z = y * 2
    print(z)
    return get


def g(x):
    get = lambda: y
    y = x + 1
    z = y * 2
    print(z)
    return get
'''


def test_closure_extract_pre_run_lambda_blocks(tmp_path):
    _write(tmp_path, "m.py", _CLOSURE_E)
    plan = plan_dedup_extract(tmp_path, _block(["m.py:3", "m.py:11"], 3))
    _assert_blocked(plan, "`y`", "now-helper-internal name")


_CLOSURE_CLEAN = '''\
def f(x, log):
    get = lambda: x
    if x < 0:
        return "neg"
    y = x + 1
    log.append(y)
    return get()


def g(x, log):
    get = lambda: x
    if x < 0:
        return "neg"
    y = x + 1
    log.append(y)
    return get()
'''


def test_closure_negative_lambda_reading_param_lands(tmp_path):
    # Negative control: the pre-run lambda reads only the PARAMETER `x` —
    # nothing the run stores — so the lift stays sound and lands.
    _write(tmp_path, "m.py", _CLOSURE_CLEAN)
    plan = plan_dedup_guarded_return(
        tmp_path, _block(["m.py:3", "m.py:12"], 3))
    assert plan.ok, f"blockers={plan.blockers}"
    ast.parse(plan.new_contents["m.py"])


# ══════════════════════════════════════════════════════════════════════════
# Rail 5 — invisible non-Name bindings (import-as / except-as / match).
# ══════════════════════════════════════════════════════════════════════════

_IMPORT_AS_G = '''\
def f(x):
    import os as _os
    if x < 0:
        return None
    y = _os.sep + str(x)
    return y


def g(x):
    import os as _os
    if x < 0:
        return None
    y = _os.sep + str(x)
    return y
'''


def test_invisible_binding_guarded_import_as_blocks(tmp_path):
    # The verified repro: `_os` is bound via ast.alias (no Name node), so
    # live-in misses it and the helper references it as a dangling global.
    _write(tmp_path, "m.py", _IMPORT_AS_G)
    plan = plan_dedup_guarded_return(
        tmp_path, _block(["m.py:3", "m.py:11"], 2))
    _assert_blocked(plan, "`_os`", "import`/`except`/`match",
                    "would lose that binding")


_IMPORT_AS_T = '''\
def f(x):
    import os as _os
    y = _os.sep + str(x)
    return y


def g(x):
    import os as _os
    y = _os.sep + str(x)
    return y
'''


def test_invisible_binding_total_return_import_as_blocks(tmp_path):
    _write(tmp_path, "m.py", _IMPORT_AS_T)
    plan = plan_dedup_total_return(tmp_path, _block(["m.py:3", "m.py:9"], 2))
    _assert_blocked(plan, "`_os`", "would lose that binding")


_MATCH_CAPTURE_E = '''\
def f(cmd, x):
    match cmd:
        case [label]:
            pass
    out = label + x
    print(out)


def g(cmd, x):
    match cmd:
        case [label]:
            pass
    out = label + x
    print(out)
'''


def test_invisible_binding_extract_match_capture_blocks(tmp_path):
    _write(tmp_path, "m.py", _MATCH_CAPTURE_E)
    plan = plan_dedup_extract(tmp_path, _block(["m.py:5", "m.py:13"], 2))
    _assert_blocked(plan, "`label`", "would lose that binding")


_IMPORT_IN_RUN = '''\
def f(x):
    if x < 0:
        return None
    import os as _os
    y = _os.sep + str(x)
    return y


def g(x):
    if x < 0:
        return None
    import os as _os
    y = _os.sep + str(x)
    return y
'''


def test_invisible_binding_negative_import_inside_run_lands(tmp_path):
    # Negative control: the alias binding travels WITH the run (it is bound
    # within the range), so the lift stays sound.
    _write(tmp_path, "m.py", _IMPORT_IN_RUN)
    plan = plan_dedup_guarded_return(
        tmp_path, _block(["m.py:2", "m.py:10"], 3))
    assert plan.ok, f"blockers={plan.blockers}"
    ast.parse(plan.new_contents["m.py"])


_MODULE_IMPORT_CLEAN = '''\
import os


def f(x):
    y = os.sep + str(x)
    z = y * 2
    print(z)


def g(x):
    y = os.sep + str(x)
    z = y * 2
    print(z)
'''


def test_invisible_binding_negative_module_level_import_lands(tmp_path):
    # Negative control: a MODULE-level import is not a function-local
    # invisible binding — the single-module lift keeps resolving it.
    _write(tmp_path, "m.py", _MODULE_IMPORT_CLEAN)
    plan = plan_dedup_extract(tmp_path, _block(["m.py:5", "m.py:11"], 3))
    assert plan.ok, f"blockers={plan.blockers}"
    assert "os.sep" in plan.new_contents["m.py"]


# ══════════════════════════════════════════════════════════════════════════
# Rail 9 — async for / async with (parse-clean, compile-broken emits).
# ══════════════════════════════════════════════════════════════════════════

_ASYNC_T = '''\
async def suma(it):
    total = 0
    async for v in it:
        total += v
    return total


async def sumb(it):
    total = 0
    async for v in it:
        total += v
    return total
'''


def test_async_for_total_return_blocks(tmp_path):
    # The verified repro: `async for` has no Await child, the sync helper
    # emit PARSES but cannot compile ('async for' outside async function).
    _write(tmp_path, "m.py", _ASYNC_T)
    plan = plan_dedup_total_return(tmp_path, _block(["m.py:2", "m.py:9"], 3))
    _assert_blocked(plan, "`asyncfor`", "would change control flow")


_ASYNC_G = '''\
async def fa(it, flag):
    if flag:
        return 0
    total = 0
    async for v in it:
        total += v
    print(total)


async def fb(it, flag):
    if flag:
        return 0
    total = 0
    async for v in it:
        total += v
    print(total)
'''


def test_async_for_guarded_blocks(tmp_path):
    _write(tmp_path, "m.py", _ASYNC_G)
    plan = plan_dedup_guarded_return(
        tmp_path, _block(["m.py:2", "m.py:11"], 4))
    _assert_blocked(plan, "`asyncfor`", "would change control flow")


_ASYNC_WITH_E = '''\
async def wa(res, log):
    async with res as r:
        log.append(r)
    log.append("done")


async def wb(res, log):
    async with res as r:
        log.append(r)
    log.append("done")
'''


def test_async_with_extract_blocks(tmp_path):
    _write(tmp_path, "m.py", _ASYNC_WITH_E)
    plan = plan_dedup_extract(tmp_path, _block(["m.py:2", "m.py:8"], 2))
    _assert_blocked(plan, "`asyncwith`", "would change control flow")


_SYNC_IN_ASYNC = '''\
async def fa(x):
    y = x + 1
    if y > 10:
        return y
    return -y


async def fb(x):
    y = x + 1
    if y > 10:
        return y
    return -y
'''


def test_async_negative_sync_run_inside_async_def_lands(tmp_path):
    # Negative control: a PURELY SYNC run inside an `async def` lifts into a
    # sync helper soundly — the emit compiles, not just parses.
    _write(tmp_path, "m.py", _SYNC_IN_ASYNC)
    plan = plan_dedup_total_return(tmp_path, _block(["m.py:2", "m.py:9"], 3))
    assert plan.ok, f"blockers={plan.blockers}"
    compile(plan.new_contents["m.py"], "<m>", "exec")


# ══════════════════════════════════════════════════════════════════════════
# Bonus rail — frame/namespace reflection.
# ══════════════════════════════════════════════════════════════════════════

_REFLECT_G = '''\
K = 5


def fa(x):
    if x < 0:
        return None
    y = globals()["K"] + x
    return y


def fb(x):
    if x < 0:
        return None
    y = globals()["K"] + x
    return y
'''


def test_reflection_guarded_globals_blocks(tmp_path):
    _write(tmp_path, "m.py", _REFLECT_G)
    plan = plan_dedup_guarded_return(
        tmp_path, _block(["m.py:5", "m.py:12"], 2))
    _assert_blocked(plan, "`globals`", "frame/namespace reflection")


_REFLECT_E = '''\
import sys


def pa(x):
    frame = sys._getframe(0)
    name = frame.f_code.co_name
    print(name, x)


def pb(x):
    frame = sys._getframe(0)
    name = frame.f_code.co_name
    print(name, x)
'''


def test_reflection_extract_getframe_blocks(tmp_path):
    _write(tmp_path, "m.py", _REFLECT_E)
    plan = plan_dedup_extract(tmp_path, _block(["m.py:5", "m.py:11"], 3))
    _assert_blocked(plan, "`_getframe`", "frame/namespace reflection")


_REFLECT_CLEAN = '''\
def qa(x, evaluate):
    a = evaluate(x)
    b = a * 2
    print(b)


def qb(x, evaluate):
    a = evaluate(x)
    b = a * 2
    print(b)
'''


def test_reflection_negative_similar_names_land(tmp_path):
    # Negative control: `evaluate` is not `eval` — only the exact reflection
    # tokens block.
    _write(tmp_path, "m.py", _REFLECT_CLEAN)
    plan = plan_dedup_extract(tmp_path, _block(["m.py:2", "m.py:8"], 3))
    assert plan.ok, f"blockers={plan.blockers}"


# ══════════════════════════════════════════════════════════════════════════
# Bonus rail (W99a) — a `class` statement anywhere in the run: its `.name`
# binding is invisible to `_stores`/`_bound_names` (an identifier FIELD, not
# an ast.Name Store node), so a class defined in the run and READ AFTER it is
# silently lost (NameError) once the run collapses into a helper — and, on
# the near-dup lane, a differing class DOCSTRING splices to a bare expression,
# silently nulling __doc__. Probe-confirmed on all three exact-dup lanes.
# ══════════════════════════════════════════════════════════════════════════

_CLASSDEF_EXTRACT = '''\
def fa(x):
    a = x + 1
    class C:
        tag = 1
    b = a * 2
    return C.tag + b


def fb(x):
    a = x + 1
    class C:
        tag = 1
    b = a * 2
    return C.tag + b
'''


def test_classdef_extract_read_after_run_blocks(tmp_path):
    # The verified repro: a class bound in the (plain, non-returning) run and
    # read AFTER it landed with blockers == [] and raised NameError at
    # runtime (`C` never left the helper). Now: refusal.
    _write(tmp_path, "m.py", _CLASSDEF_EXTRACT)
    plan = plan_dedup_extract(tmp_path, _block(["m.py:2", "m.py:10"], 3))
    _assert_blocked(plan, "the range defines a `class`",
                    "invisible to this data-flow analysis")


_CLASSDEF_TOTAL_RETURN = '''\
def fa(x, flag):
    if flag:
        return -1
    class C:
        tag = 1
    b = x + 1
    return C.tag + b


def fb(x, flag):
    if flag:
        return -1
    class C:
        tag = 1
    b = x + 1
    return C.tag + b
'''


def test_classdef_total_return_blocks(tmp_path):
    # Immune to the NameError mechanism specifically (live_out is hardcoded
    # [] — everything after a total-return run is unreachable), but the
    # blanket rail refuses it anyway (cheap over-refusal, family-wide).
    _write(tmp_path, "m.py", _CLASSDEF_TOTAL_RETURN)
    plan = plan_dedup_total_return(tmp_path, _block(["m.py:2", "m.py:11"], 4))
    _assert_blocked(plan, "the range defines a `class`",
                    "invisible to this data-flow analysis")


_CLASSDEF_GUARDED = '''\
def fa(x, flag, log):
    if flag:
        return -1
    class C:
        tag = 1
    b = x + 1
    log.append(b)
    return C.tag + b


def fb(x, flag, log):
    if flag:
        return -1
    class C:
        tag = 1
    b = x + 1
    log.append(b)
    return C.tag + b
'''


def test_classdef_guarded_return_blocks(tmp_path):
    # The verified repro: the guarded-return lane's sentinel projection ALSO
    # landed with blockers == [] and raised NameError ('C' is not defined) at
    # runtime. Now: refusal.
    _write(tmp_path, "m.py", _CLASSDEF_GUARDED)
    plan = plan_dedup_guarded_return(tmp_path, _block(["m.py:2", "m.py:12"], 4))
    _assert_blocked(plan, "the range defines a `class`",
                    "invisible to this data-flow analysis")


_CLASSDEF_NEGATIVE = '''\
def ra(x, flag):
    if flag:
        return -1
    a = x + 1
    b = a * 2
    return b


def rb(x, flag):
    if flag:
        return -1
    a = x + 1
    b = a * 2
    return b
'''


def test_classdef_negative_no_class_in_run_lands(tmp_path):
    # Negative control: a run with NO class statement anywhere is untouched
    # by the rail — the sound total-return shape still lands.
    _write(tmp_path, "m.py", _CLASSDEF_NEGATIVE)
    plan = plan_dedup_total_return(tmp_path, _block(["m.py:2", "m.py:10"], 4))
    assert plan.ok, f"blockers={plan.blockers}"
    ns: dict = {}
    exec(compile(plan.new_contents["m.py"], "<m>", "exec"), ns)  # noqa: S102
    assert ns["ra"](3, False) == 8


def test_classdef_reason_unit_edges():
    # Edge/unit paths: empty run, nested class inside another statement, and
    # a class OUTSIDE the run (the enclosing container) never trips it.
    from app.execution._dedup_helpers import _classdef_reason

    assert _classdef_reason([]) is None
    nested = ast.parse("if True:\n    class C:\n        pass\n").body
    assert _classdef_reason(nested) is not None
    method_run = ast.parse(
        "class Outer:\n    def m(self):\n        x = 1\n        return x\n"
    ).body[0].body[0].body
    assert _classdef_reason(method_run) is None


# ══════════════════════════════════════════════════════════════════════════
# Unit edges for the shared collectors / reason helpers.
# ══════════════════════════════════════════════════════════════════════════

def test_invisible_bound_names_collects_alias_except_and_match_captures():
    src = (
        "import os.path\n"
        "from json import dumps as _d\n"
        "try:\n"
        "    pass\n"
        "except ValueError as err:\n"
        "    pass\n"
        "match x:\n"
        "    case [head, *rest]:\n"
        "        pass\n"
    )
    names = _invisible_bound_names(ast.parse(src).body)
    assert names == {"os", "_d", "err", "head", "rest"}


def test_invisible_bound_names_empty_input_is_empty():
    assert _invisible_bound_names([]) == set()


def test_bound_names_adds_name_stores_for_walrus_for_and_with():
    src = (
        "for i in rng:\n"
        "    total = (n := i) + 1\n"
        "with open(p) as fh:\n"
        "    pass\n"
    )
    assert {"i", "total", "n", "fh"} <= _bound_names(ast.parse(src).body)


def test_multiline_string_reason_flags_triple_quoted_and_fstring():
    fn = ast.parse('def f():\n    q = """A\n  B\n"""\n').body[0]
    assert _multiline_string_reason(fn.body) is not None
    fn2 = ast.parse('def f(x):\n    q = f"""A\n{x}\n"""\n').body[0]
    assert _multiline_string_reason(fn2.body) is not None
    fn3 = ast.parse('def f():\n    q = "one line"\n').body[0]
    assert _multiline_string_reason(fn3.body) is None
    assert _multiline_string_reason([]) is None


def test_occurrence_rail_reason_clean_whole_body_run_is_none():
    # Edge: the run IS the whole body — empty before/after, no rails fire.
    fn = ast.parse("def f(x):\n    y = x\n    print(y)\n").body[0]
    assert occurrence_rail_reason(fn, fn.body) is None
