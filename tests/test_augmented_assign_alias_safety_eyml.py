"""Execution-proven behaviour-preservation for the ``augmented_assign`` transform,
focused on the ALIASING hazard a red-team pass surfaced.

``x = x <op> y`` rebinds ``x`` to a fresh object; ``x += y`` invokes the in-place
dunder (``__iadd__`` …) which, for a *mutable* ``x``, mutates the EXISTING object.
The two diverge exactly when another live reference can read that object AFTER the
mutation. A transform that rewrote such a case would silently change behaviour —
the deepest way a "behaviour-preserving" transform can betray the moat.

These tests EXECUTE the original and the rewritten source on fixed inputs and
assert identical observable results for every case the transform rewrites
(proof, not eyeballing), and assert the transform REFUSES every aliasing shape
where ``+=`` would diverge. They also pin the precision of the guard: the common
loop accumulator read strictly AFTER the loop stays rewritable.

Deterministic; stdlib-only.
"""

from __future__ import annotations

from app.execution.semantic.transforms import augmented_assign as aa


def _run(src: str, *args):
    """Exec ``src`` and call ``f(*args)``; return (result, exception-type)."""
    ns: dict = {}
    try:
        exec(compile(src, "<m>", "exec"), ns)
        return ns["f"](*args), None
    except Exception as exc:  # noqa: BLE001 — exception identity is part of behaviour
        return None, type(exc).__name__


def _rewritten(src: str) -> str | None:
    res = aa.apply("m.py", src)
    return res.patch_requests[0]["new_content"] if res else None


# --- cases the transform rewrites must be EXECUTION-identical ---------------

_SAFE = {
    "returned int accumulator": (
        "def f(items):\n    acc = 0\n    for x in items:\n"
        "        acc = acc + x\n    return acc\n", ([1, 2, 3],)),
    "used-after-loop accumulator": (
        "def f(items):\n    t = 0\n    for x in items:\n"
        "        t = t + x\n    return t * 2\n", ([5, 6],)),
    "simple local then return": (
        "def f():\n    x = 0\n    x = x + 1\n    return x\n", ()),
}


def test_safe_cases_rewrite_and_execute_identically():
    for name, (src, args) in _SAFE.items():
        new = _rewritten(src)
        assert new is not None, f"{name}: expected a rewrite"
        assert "+=" in new, name
        assert _run(src, *args) == _run(new, *args), name


# --- aliasing hazards must be REFUSED (and the divergence is real) ----------

def test_sibling_alias_to_mutable_is_refused():
    src = "def f(z):\n    x = z\n    b = x\n    x = x + [1]\n    return b\n"
    assert _rewritten(src) is None
    rebind, _ = _run(src, [0])
    inplace, _ = _run(src.replace("x = x + [1]", "x += [1]"), [0])
    assert rebind == [0] and inplace == [0, 1]  # the rewrite WOULD have diverged


def test_parameter_target_is_refused():
    # A mutable arg the caller still holds diverges; refuse regardless of the
    # statically-unknown runtime type.
    assert _rewritten("def f(x, y):\n    x = x + y\n    return x\n") is None
    # The divergence is real: a caller-held list is left untouched by rebinding
    # but mutated by ``+=``.
    reb: dict = {}
    exec(compile("def f(x, y):\n    x = x + y\n    return x\n", "<m>", "exec"), reb)
    inp: dict = {}
    exec(compile("def f(x, y):\n    x += y\n    return x\n", "<m>", "exec"), inp)
    base = [0]
    reb["f"](base, [1])
    assert base == [0]
    base2 = [0]
    inp["f"](base2, [1])
    assert base2 == [0, 1]


def test_global_and_nonlocal_targets_are_refused():
    assert _rewritten(
        "g = []\ndef f(y):\n    global g\n    g = g + y\n    return g\n") is None
    assert _rewritten(
        "def outer():\n    a = []\n    def f(y):\n        nonlocal a\n"
        "        a = a + y\n        return a\n    return f\n") is None


def test_in_loop_snapshot_is_refused():
    src = ("def f(items):\n    acc = []\n    out = []\n    for x in items:\n"
           "        acc = acc + [x]\n        out.append(acc)\n    return out\n")
    assert _rewritten(src) is None
    rebind, _ = _run(src, [1, 2])
    inplace, _ = _run(src.replace("acc = acc + [x]", "acc += [x]"), [1, 2])
    assert rebind == [[1], [1, 2]] and inplace == [[1, 2], [1, 2]]  # diverges


def test_escape_before_mutation_is_refused():
    src = ("def f(z):\n    x = z\n    bag = []\n    bag.append(x)\n"
           "    x = x + [1]\n    return bag[0]\n")
    assert _rewritten(src) is None
    rebind, _ = _run(src, [0])
    inplace, _ = _run(src.replace("x = x + [1]", "x += [1]"), [0])
    assert rebind == [0] and inplace == [0, 1]  # diverges


def test_read_strictly_after_last_mutation_is_allowed():
    # Precision guard: a plain read AFTER the only mutation, outside any loop,
    # cannot observe a transition — both forms hold the same final object.
    new = _rewritten("def f():\n    x = 0\n    x = x + 5\n    y = x + 1\n    return y\n")
    assert new is not None and "x += 5" in new
