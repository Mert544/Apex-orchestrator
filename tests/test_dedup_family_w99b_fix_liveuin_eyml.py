"""Regression suite for wave W99b's PREREQUISITE family-wide fix: a shipped
eager-eval ``UnboundLocalError`` hazard on a CONDITIONALLY pre-bound live-in
name.

An independent soundness skeptic's probe (machine-verified against the
shipped tree, repo untouched) proved the LANDED exact guarded-return lane
(``plan_dedup_guarded_return``) lands this shape with ZERO blockers: the
prelude binds a name only under an ``if`` (``if cond: acc = 1``, CONDITIONAL,
outside the lifted run), the run reads that name only under its OWN inner
``if`` after a guard return, and the name is live-in but NOT live-out. On the
guard-taken path (``cond=False``) the ORIGINAL code never reads the name at
all (or never even reaches the run) — no error — but every dedup-family lane
emits live-in names as EAGER call arguments (``helper(acc, ...)``), so the
lifted call raises ``UnboundLocalError`` where the original raised nothing.

Root cause: ``extract_method._data_flow``'s ``live_in`` is *reads(run) ∩
(params ∪ stores(before))* — it counts a CONDITIONAL prelude store the moment
the run reads the name anywhere, however deeply nested. The pre-existing W100
rail in ``dedup_guarded_return`` only widened ``definite`` (and only ever
REFUSED) for names ALSO in ``live_out`` — a live-in-ONLY name was invisible to
it. Because every lane shares this same ``_data_flow`` computation and the
same eager-call-argument emit shape, THE GAP IS FAMILY-WIDE, not specific to
the guarded-return lane: this file freezes one repro for each of the four
lanes whose home test file has no natural W100-style section to extend
(dedup_extract's plain AND tail-return shapes, dedup_total_return, and both
near-dup parameterized siblings, which resolve occurrences through the exact
same functions). The guarded-return lane's own live-in-ONLY repro is pinned
in ``tests/test_dedup_guarded_return.py`` next to its existing (live-out-only)
W100 boundary test, where the fixtures and helpers already live.

Probe finding: NO lane was structurally immune — all five were reproduced
diverging pre-fix (a plain block, a tail-return block, an always-returning
block, and both parameterized near-dup siblings), matching the diagnosis that
every lane emits live_in as eager call arguments via the shared
``_data_flow``.

FIX (refuse-direction, family-wide, shared in ``_dedup_helpers``):
``_bound_before_run(fn, before)`` = the function's parameters plus
``_definitely_assigned(before)``; ``_unbound_live_in_reason(live_in,
bound_before)`` refuses when ``set(live_in)`` is not a subset of
``bound_before``. Wired into the three underlying occurrence-resolution
functions (``dedup_extract._resolve_occurrence``,
``dedup_total_return._total_return_occurrence``,
``dedup_guarded_return._resolve_guarded_return``) — the near-dup lanes
inherit it for free because they resolve occurrences through these same
functions (directly, or via a one-line delegate).
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.engine.dedup import find_duplicates
from app.engine.near_dup import find_near_duplicates
from app.execution._dedup_helpers import (
    _bound_before_run,
    _definitely_assigned,
    _unbound_live_in_reason,
)
from app.execution.dedup_extract import plan_dedup_extract
from app.execution.dedup_total_return import plan_dedup_total_return
from app.execution.near_dup_extract import plan_near_dup_extract
from app.execution.near_dup_total_return import plan_near_dup_total_return


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _exec_module(source: str) -> dict:
    ns: dict = {}
    exec(compile(source, "<mod>", "exec"), ns)  # noqa: S102 - controlled test src
    return ns


def _assert_blocked_on_acc(plan) -> None:
    assert not plan.ok, f"expected a blocked plan, got new={plan.new_contents}"
    assert any("acc" in b and "unbound" in b for b in plan.blockers), (
        f"expected an 'acc ... unbound' blocker, got {plan.blockers}")
    assert not plan.new_contents


def _parse_stmts(src: str) -> list[ast.stmt]:
    fn = ast.parse(src).body[0]
    return fn.body


# ──────────────────────────────────────────────────────────────────────────
# Unit tests: the two new shared primitives in isolation.
# ──────────────────────────────────────────────────────────────────────────

def test_bound_before_run_is_params_plus_definitely_assigned_prelude():
    fn = ast.parse("def f(x, y):\n    pass\n").body[0]
    before = _parse_stmts("def g():\n    a = 1\n    if True:\n        b = 2\n")
    assert _bound_before_run(fn, before) == {"x", "y", "a"}


def test_bound_before_run_empty_prelude_is_just_params():
    fn = ast.parse("def f(x):\n    pass\n").body[0]
    assert _bound_before_run(fn, []) == {"x"}


def test_unbound_live_in_reason_none_when_all_bound():
    assert _unbound_live_in_reason(["x", "y"], {"x", "y", "z"}) is None


def test_unbound_live_in_reason_names_the_gap():
    # Only `acc` is unbound (`flag` is in bound_before) — the message must
    # name exactly the unbound one, not the whole live_in list.
    reason = _unbound_live_in_reason(["acc", "flag"], {"flag"})
    assert reason is not None
    assert reason.startswith("acc may be unbound")
    assert "flag" not in reason


def test_unbound_live_in_reason_sorted_deterministic():
    r1 = _unbound_live_in_reason(["z", "a", "m"], set())
    r2 = _unbound_live_in_reason(["m", "z", "a"], set())
    assert r1 == r2
    assert r1.startswith("a, m, z")


# ──────────────────────────────────────────────────────────────────────────
# Lane 1: dedup_extract — PLAIN block (no return at all in the run).
# ──────────────────────────────────────────────────────────────────────────

_PLAIN_COND_PRELUDE = '''\
def da(cond, flag, log):
    if cond:
        acc = 1
    if flag:
        log.append(acc)
    log.append("tail")


def db(cond, flag, log):
    if cond:
        acc = len(log)
    if flag:
        log.append(acc)
    log.append("tail")
'''


def test_dedup_extract_plain_block_conditionally_pre_bound_live_in_blocked(tmp_path):
    # W99b-fix repro (Lane 1): `acc` is bound only under `if cond:` in the
    # prelude (OUTSIDE the 2-statement run) and read only under the run's own
    # `if flag:`. da(False, False, []) originally appends "tail" and returns
    # None — `acc` is never touched. Pre-fix this landed with ZERO blockers
    # and the emitted `_shared_1(acc, flag, log)` call read `acc` eagerly.
    _write(tmp_path, "mod.py", _PLAIN_COND_PRELUDE)
    blocks = find_duplicates(tmp_path, min_statements=2, min_occurrences=2)
    block = next(b for b in blocks if b.lines == 2)
    plan = plan_dedup_extract(tmp_path, block)
    _assert_blocked_on_acc(plan)

    before = _exec_module(_PLAIN_COND_PRELUDE)
    log: list = []
    assert before["da"](False, False, log) is None
    assert log == ["tail"]  # `acc` never touched on this path


# ──────────────────────────────────────────────────────────────────────────
# Lane 1b: dedup_extract — TAIL-RETURN block (run's ONLY return is the tail).
# ──────────────────────────────────────────────────────────────────────────

_TAIL_RETURN_COND_PRELUDE = '''\
def ta(cond, flag, log):
    if cond:
        acc = 1
    if flag:
        log.append(acc)
    return 1


def tb(cond, flag, log):
    if cond:
        acc = len(log)
    if flag:
        log.append(acc)
    return 1
'''


def test_dedup_extract_tail_return_conditionally_pre_bound_live_in_blocked(tmp_path):
    # W99b-fix repro (Lane 1b): same shape, but the run's own tail IS a
    # return (the OTHER admissible dedup_extract shape). ta(False, False, [])
    # originally returns 1 without ever touching `acc`.
    _write(tmp_path, "mod.py", _TAIL_RETURN_COND_PRELUDE)
    blocks = find_duplicates(tmp_path, min_statements=2, min_occurrences=2)
    block = next(b for b in blocks if b.lines == 2)
    plan = plan_dedup_extract(tmp_path, block)
    _assert_blocked_on_acc(plan)

    before = _exec_module(_TAIL_RETURN_COND_PRELUDE)
    log: list = []
    assert before["ta"](False, False, log) == 1
    assert log == []


# ──────────────────────────────────────────────────────────────────────────
# Positive companion (Lane 1 family): a PARAMETER-bound live-in name
# conditionally REBOUND in the run still lands — the rail must not
# over-refuse the exact shape W100 was built to admit.
# ──────────────────────────────────────────────────────────────────────────

_PLAIN_PARAM_COND_REBIND = '''\
def pa(acc, flag, log):
    if flag:
        acc = acc + 1
    log.append(acc)


def pb(acc, flag, log):
    if flag:
        acc = acc + 1
    log.append(acc)
'''


def test_dedup_extract_param_bound_live_in_conditionally_rebound_still_lands(tmp_path):
    # Negative control: `acc` is a PARAMETER (always bound_before, regardless
    # of the prelude) that the run only conditionally rebinds — sound, must
    # still land (the rail must not over-refuse this shape).
    _write(tmp_path, "mod.py", _PLAIN_PARAM_COND_REBIND)
    blocks = find_duplicates(tmp_path, min_statements=2, min_occurrences=2)
    block = next(b for b in blocks if b.lines == 2)
    plan = plan_dedup_extract(tmp_path, block)
    assert plan.ok, f"blockers={plan.blockers}"

    before = _exec_module(_PLAIN_PARAM_COND_REBIND)
    after = _exec_module(plan.new_contents["mod.py"])
    for acc, flag in ((3, True), (3, False)):
        b_log: list = []
        a_log: list = []
        before["pa"](acc, flag, b_log)
        after["pa"](acc, flag, a_log)
        assert b_log == a_log


# ──────────────────────────────────────────────────────────────────────────
# Lane 2: dedup_total_return — always-returns run.
# ──────────────────────────────────────────────────────────────────────────

_TOTAL_RETURN_COND_PRELUDE = '''\
def ra(cond, flag, log):
    if cond:
        acc = 1
    if flag:
        return process(acc, log)
    return None


def rb(cond, flag, log):
    if cond:
        acc = len(log)
    if flag:
        return process(acc, log)
    return None


def process(acc, log):
    return acc
'''


def test_dedup_total_return_conditionally_pre_bound_live_in_blocked(tmp_path):
    # W99b-fix repro (Lane 2): the block ALWAYS returns (guard `if flag:
    # return ...` then a tail `return None`) — dedup_total_return's own
    # admissible shape. ra(False, False, []) originally returns None without
    # ever touching `acc`.
    _write(tmp_path, "mod.py", _TOTAL_RETURN_COND_PRELUDE)
    blocks = find_duplicates(tmp_path, min_statements=2, min_occurrences=2)
    block = next(b for b in blocks if b.lines == 2)
    plan = plan_dedup_total_return(tmp_path, block)
    _assert_blocked_on_acc(plan)

    before = _exec_module(_TOTAL_RETURN_COND_PRELUDE)
    assert before["ra"](False, False, []) is None


_TOTAL_RETURN_PRELUDE_DIRECT_BOUND = '''\
def sa(cond, flag, log):
    acc = len(log)
    if flag:
        return process(acc, log)
    return None


def sb(cond, flag, log):
    acc = len(log)
    if flag:
        return process(acc, log)
    return None


def process(acc, log):
    return acc
'''


def test_dedup_total_return_prelude_direct_bound_live_in_still_lands(tmp_path):
    # Negative control: `acc` is bound by a DIRECT top-level prelude
    # assignment (unconditional) — sound, must still land. `find_duplicates`
    # reports TWO size-2 windows here (`[acc=..., if flag:...]` starting at
    # line 2, and the always-returning `[if flag:..., return None]` starting
    # at line 3) — only the latter is dedup_total_return's admissible shape.
    _write(tmp_path, "mod.py", _TOTAL_RETURN_PRELUDE_DIRECT_BOUND)
    blocks = find_duplicates(tmp_path, min_statements=2, min_occurrences=2)
    block = next(b for b in blocks
                 if b.lines == 2 and "mod.py:3" in b.occurrences)
    plan = plan_dedup_total_return(tmp_path, block)
    assert plan.ok, f"blockers={plan.blockers}"

    before = _exec_module(_TOTAL_RETURN_PRELUDE_DIRECT_BOUND)
    after = _exec_module(plan.new_contents["mod.py"])
    for flag in (True, False):
        assert before["sa"](True, flag, []) == after["sa"](True, flag, [])


# ──────────────────────────────────────────────────────────────────────────
# Lane 4: near_dup_extract's shared ``_plan_parameterized`` (default
# resolver — the parameterized plain/tail-return domain). Constant diff in
# the run's own tail makes it a near-DUPLICATE (not an exact one).
# ──────────────────────────────────────────────────────────────────────────

_NEAR_DUP_COND_PRELUDE = '''\
def na(cond, flag, log):
    if cond:
        acc = 1
    if flag:
        log.append(acc)
    x = 7


def nb(cond, flag, log):
    if cond:
        acc = len(log)
    if flag:
        log.append(acc)
    x = 8
'''


def test_near_dup_extract_conditionally_pre_bound_live_in_blocked(tmp_path):
    # W99b-fix repro (Lane 4): the near-dup lane resolves occurrences via
    # dedup_extract's OWN ``_resolve_occurrence`` (shared, not copied), so it
    # inherits the fix for free. na(False, False, []) originally leaves `x`
    # unbound and unread, returning None without ever touching `acc`.
    _write(tmp_path, "mod.py", _NEAR_DUP_COND_PRELUDE)
    groups = find_near_duplicates(tmp_path, min_statements=2)
    group = next(g for g in groups if g.lines == 2 and g.diff_count == 1)
    plan = plan_near_dup_extract(tmp_path, group)
    _assert_blocked_on_acc(plan)

    before = _exec_module(_NEAR_DUP_COND_PRELUDE)
    assert before["na"](False, False, []) is None


# ──────────────────────────────────────────────────────────────────────────
# Lane 5: near_dup_total_return (parameterized always-returns).
# ──────────────────────────────────────────────────────────────────────────

_NEAR_DUP_TOTAL_RETURN_COND_PRELUDE = '''\
def ta(cond, flag, log):
    if cond:
        acc = 1
    if flag:
        return process(acc, log, 7)
    return None


def tb(cond, flag, log):
    if cond:
        acc = len(log)
    if flag:
        return process(acc, log, 8)
    return None


def process(acc, log, c):
    return acc + c
'''


def test_near_dup_total_return_conditionally_pre_bound_live_in_blocked(tmp_path):
    # W99b-fix repro (Lane 5): resolves via dedup_total_return's shared
    # ``_total_return_occurrence`` (inherits the fix for free) after its own
    # routing/admissibility checks. ta(False, False, []) originally returns
    # None without ever touching `acc`.
    _write(tmp_path, "mod.py", _NEAR_DUP_TOTAL_RETURN_COND_PRELUDE)
    groups = find_near_duplicates(tmp_path, min_statements=2)
    group = next(g for g in groups if g.lines == 2 and g.diff_count == 1)
    plan = plan_near_dup_total_return(tmp_path, group)
    _assert_blocked_on_acc(plan)

    before = _exec_module(_NEAR_DUP_TOTAL_RETURN_COND_PRELUDE)
    assert before["ta"](False, False, []) is None


# ──────────────────────────────────────────────────────────────────────────
# ``_definitely_assigned`` still resolves from BOTH its new home
# (``_dedup_helpers``) and its original one (``dedup_guarded_return``, whose
# own 34-test suite imports it directly) — the re-export must be the SAME
# function object, not a copy that could drift.
# ──────────────────────────────────────────────────────────────────────────

def test_definitely_assigned_reexported_identical_object():
    from app.execution.dedup_guarded_return import (
        _definitely_assigned as reexported,
    )
    assert reexported is _definitely_assigned
