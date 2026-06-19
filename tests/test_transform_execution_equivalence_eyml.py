"""Execution-proven behaviour-preservation for the "safe" simplification transforms.

A prior red-team pass executed the original and rewritten source for the
``augmented_assign`` transform and surfaced a real aliasing divergence
(``tests/test_augmented_assign_alias_safety_eyml.py``). This file extends that
*proof-by-execution* rigor to the rest of the behaviour-preserving transforms:

  * Every shape a transform REWRITES is run, original vs rewritten, on fixed
    inputs; we assert identical observable behaviour — return value, raised
    exception TYPE, and captured stdout. "Safe" is never eyeballed; it is
    executed.
  * Every shape in a known danger zone (double-evaluation of side-effecting
    expressions, short-circuit semantics, truthiness vs ``bool``, exception-type
    changes, comprehension scope / ``break``) is asserted to be REFUSED
    (``apply`` returns ``None``); for the sharpest ones we also EXECUTE the
    divergence that the refusal prevents, proving the guard earns its keep.

One REAL divergence was found and FIXED during this pass:

  * ``identity_literal`` rewrote a *sibling* identity comparison on the same
    flagged line via its whole-line regex (``y is (z)`` -> ``y == (z)``), which
    changes behaviour for objects where ``is`` and ``==`` disagree (two ``nan``
    references). The transform now refuses any flagged line carrying more than
    one ``is``/``is not`` operator. See the dedicated section below.

One BOUNDARY is documented (not a transform bug we change): ``dict_get_default``
rewrites ``if K in d: x = d[K] else: x = NAME`` even when ``NAME`` is unbound,
and ``d.get(K, NAME)`` evaluates ``NAME`` eagerly. That diverges (``NameError``)
only when the source already references an unbound name *and* the key is
present. A bound name (parameter / earlier assignment) and a constant default
are proven execution-identical here; the unbound-name divergence is pinned as a
known edge that the maintainers' existing test already exercises as accepted.

Deterministic; stdlib-only.
"""

from __future__ import annotations

import io
import warnings
from contextlib import redirect_stdout

from app.execution.semantic.transforms import (
    chained_comparison,
    collection_literal,
    dict_get_default,
    dict_literal,
    double_not,
    identity_literal,
    membership_set,
    merge_nested_if,
    not_in_simplify,
    or_default,
    redundant_else,
    redundant_lambda,
    set_literal,
    simplify_comparison,
    swap_via_tuple,
    tuple_membership,
    unreachable_cleanup,
)

# --------------------------------------------------------------------------- #
# Execution helpers
# --------------------------------------------------------------------------- #


def _rewrite(mod, src: str) -> str | None:
    """Return the rewritten ``new_content`` for ``src``, or ``None`` if refused.

    Tolerates the two ``apply`` signatures in the package (``title`` required vs
    defaulted) so a single helper drives every transform.
    """
    try:
        res = mod.apply("m.py", src, "")
    except TypeError:
        res = mod.apply("m.py", src)
    return res.patch_requests[0]["new_content"] if res else None


def _exec_capture(src: str, fn: str, args: tuple):
    """Exec ``src`` in a fresh namespace, call ``fn(*args)``, capture behaviour.

    Returns ``(result, exception_type_name, stdout)``. The exception TYPE (not
    its message) and stdout are part of observable behaviour, so both are
    compared. ``SyntaxWarning`` (e.g. F632 ``is`` with a literal) is silenced so
    it does not pollute the captured stdout/stderr comparison.
    """
    ns: dict = {}
    buf = io.StringIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            with redirect_stdout(buf):
                exec(compile(src, "<m>", "exec"), ns)
                value = ns[fn](*args) if fn in ns else ns.get("R")
            return value, None, buf.getvalue()
        except Exception as exc:  # noqa: BLE001 — exception identity is behaviour
            return None, type(exc).__name__, buf.getvalue()


def assert_equivalent(mod, src: str, fn: str, arg_sets: list[tuple]) -> None:
    """The transform rewrites ``src`` AND every input executes identically.

    Proves, by execution on each fixed input, that the original and rewritten
    code agree on (result, exception-type, stdout). Fails loudly if the
    transform unexpectedly refuses (so the "safe" claim never silently rests on
    a no-op).
    """
    new = _rewrite(mod, src)
    assert new is not None, f"expected a rewrite for:\n{src}"
    assert new != src, f"rewrite was a no-op for:\n{src}"
    for args in arg_sets:
        before = _exec_capture(src, fn, args)
        after = _exec_capture(new, fn, args)
        assert before == after, (
            f"divergence on args={args!r}\n  src ->{before}\n  new ->{after}\n{src}"
        )


def assert_refused(mod, src: str) -> None:
    """The transform must REFUSE ``src`` (return ``None``) — an unsafe shape."""
    assert _rewrite(mod, src) is None, f"expected refusal for:\n{src}"


# --------------------------------------------------------------------------- #
# or_default:  ``a if a else b`` -> ``a or b``
# --------------------------------------------------------------------------- #


def test_or_default_pure_name_is_equivalent():
    src = "def f(a, b):\n    return a if a else b\n"
    # falsy a -> b; truthy a -> a; preserve the value (not just bool).
    assert_equivalent(or_default, src, "f",
                      [(0, 9), (5, 9), ("", "x"), ([], [1]), ([2], [1])])


def test_or_default_attribute_chain_is_equivalent():
    src = (
        "class O:\n    pass\n"
        "def f(flag):\n    o = O()\n    o.v = flag\n"
        "    return o.v if o.v else 'fallback'\n"
    )
    assert_equivalent(or_default, src, "f", [(0,), ("hit",), (None,)])


def test_or_default_side_effecting_test_is_refused():
    # ``g() if g() else 0`` evaluates g twice; ``g() or 0`` once. Must refuse.
    assert_refused(or_default, "def f():\n    return g() if g() else 0\n")
    # The divergence is real: ``a if a else b`` evaluates the truthy test a
    # SECOND time for the body, while ``a or b`` evaluates it once. A counter
    # returning 1 then 2 exposes it: ternary yields 2 (the body re-eval), ``or``
    # yields 1 (the single eval).
    src = ("seq = iter([1, 2])\n"
           "def g():\n    return next(seq)\n"
           "def f():\n    return g() if g() else -1\n")
    ternary = _exec_capture(src, "f", ())
    forced = _exec_capture(src.replace("g() if g() else -1", "g() or -1"), "f", ())
    assert ternary[0] == 2 and forced[0] == 1  # the rewrite WOULD diverge


# --------------------------------------------------------------------------- #
# double_not:  ``not not x`` -> ``bool(x)``
# --------------------------------------------------------------------------- #


def test_double_not_truthiness_is_preserved():
    # bool(x) collapses any truthy/falsy value to True/False, exactly as not not.
    src = "def f(x):\n    return not not x\n"
    assert_equivalent(double_not, src, "f",
                      [([],), ([0],), ("",), ("s",), (0,), (3,), (None,)])


def test_double_not_compare_operand_is_equivalent():
    src = "def f(x):\n    return not not (x > 0)\n"
    assert_equivalent(double_not, src, "f", [(-1,), (0,), (5,)])


# --------------------------------------------------------------------------- #
# not_in_simplify:  ``not a in b`` -> ``a not in b`` ; ``not a is b`` -> ``a is not b``
# --------------------------------------------------------------------------- #


def test_not_in_simplify_membership_is_equivalent():
    src = "def f(a, b):\n    return not a in b\n"
    assert_equivalent(not_in_simplify, src, "f",
                      [(1, [2, 3]), (2, [2, 3]), ("k", {"k": 1})])


def test_not_in_simplify_identity_is_equivalent():
    src = "def f(a, b):\n    return not a is b\n"
    assert_equivalent(not_in_simplify, src, "f", [(1, 1), (1, 2), (None, None)])


# --------------------------------------------------------------------------- #
# tuple_membership:  ``x == 1 or x == 2`` -> ``x in (1, 2)``
# --------------------------------------------------------------------------- #


def test_tuple_membership_is_equivalent():
    src = "def f(x):\n    return x == 1 or x == 2 or x == 3\n"
    assert_equivalent(tuple_membership, src, "f", [(1,), (2,), (3,), (4,), (0,)])


def test_tuple_membership_side_effecting_left_is_refused():
    # ``g() == 1 or g() == 2`` evaluates g up to twice; ``g() in (1, 2)`` once.
    assert_refused(tuple_membership, "def f():\n    return g() == 1 or g() == 2\n")


# --------------------------------------------------------------------------- #
# membership_set:  ``x in [1, 2]`` -> ``x in {1, 2}``
# --------------------------------------------------------------------------- #


def test_membership_set_in_and_not_in_are_equivalent():
    assert_equivalent(membership_set, "def f(x):\n    return x in [1, 2, 3]\n",
                      "f", [(1,), (3,), (4,), (True,)])
    assert_equivalent(membership_set, "def f(x):\n    return x not in (1, 2)\n",
                      "f", [(1,), (5,)])


def test_membership_set_int_float_bool_collapse_is_preserved():
    # 1 == 1.0 == True under set hashing/equality, so membership is identical
    # whether the display is a list or a set.
    src = "def f(x):\n    return x in [1, 2, 3]\n"
    assert_equivalent(membership_set, src, "f", [(1.0,), (True,), (2.0,)])


# --------------------------------------------------------------------------- #
# chained_comparison:  ``a < b and b < c`` -> ``a < b < c``
# (DANGER: side-effecting middle term evaluated twice vs once)
# --------------------------------------------------------------------------- #


def test_chained_comparison_pure_terms_are_equivalent():
    src = "def f(a, b, c):\n    return a < b and b < c\n"
    assert_equivalent(chained_comparison, src, "f",
                      [(1, 2, 3), (3, 2, 1), (1, 1, 1), (1, 2, 2)])


def test_chained_comparison_equality_chain_is_equivalent():
    src = "def f(a, b, c):\n    return a == b and b == c\n"
    assert_equivalent(chained_comparison, src, "f",
                      [(1, 1, 1), (1, 1, 2), (1, 2, 2)])


def test_chained_comparison_side_effecting_middle_is_refused():
    # The middle term is shared. In the chain it is evaluated ONCE; in the
    # and-form the second arm re-evaluates it. A call/subscript middle must be
    # refused, and the divergence is real.
    assert_refused(chained_comparison, "def f(a, c):\n    return a < g() and g() < c\n")
    assert_refused(chained_comparison,
                   "def f(a, b, c):\n    return a < b[0] and b[0] < c\n")

    # PROOF the guard matters: a generator-backed middle returns 4 then 9.
    #   and-form: 1 < 4  (True)  and  9 < 5 (False)  -> False
    #   chain   : 1 < 4 < 5                           -> True   (9 never seen)
    seq_src = ("seq = iter([4, 9])\n"
               "def g():\n    return next(seq)\n"
               "def f():\n    return 1 < g() and g() < 5\n")
    and_form = _exec_capture(seq_src, "f", ())
    chain_form = _exec_capture(
        seq_src.replace("1 < g() and g() < 5", "1 < g() < 5"), "f", ())
    assert and_form[0] is False and chain_form[0] is True  # diverges


# --------------------------------------------------------------------------- #
# simplify_comparison:  ``x == None`` -> ``x is None`` (and !=)
# --------------------------------------------------------------------------- #


def test_simplify_comparison_none_is_equivalent():
    assert_equivalent(simplify_comparison, "def f(x):\n    return x == None\n",
                      "f", [(None,), (0,), ("",), ([],)])
    assert_equivalent(simplify_comparison, "def f(x):\n    return x != None\n",
                      "f", [(None,), (1,), (False,)])


# --------------------------------------------------------------------------- #
# dict_get_default:  ``if K in d: x = d[K] else: x = DEFAULT`` -> ``x = d.get(K, DEFAULT)``
# --------------------------------------------------------------------------- #


_DGD_CONST = (
    "def f(d, k):\n"
    "    if k in d:\n        x = d[k]\n    else:\n        x = 99\n"
    "    return x\n"
)
_DGD_BOUND = (
    "def f(d, k, dflt):\n"
    "    if k in d:\n        x = d[k]\n    else:\n        x = dflt\n"
    "    return x\n"
)


def test_dict_get_default_constant_default_is_equivalent():
    # hit and miss both proven; constant default is always-safe to evaluate.
    assert_equivalent(dict_get_default, _DGD_CONST, "f",
                      [({"a": 1}, "a"), ({}, "a"), ({"a": 0}, "a")])


def test_dict_get_default_bound_name_default_is_equivalent():
    # A bound (parameter) default name is side-effect-free and always defined,
    # so eager evaluation by ``dict.get`` changes nothing.
    assert_equivalent(dict_get_default, _DGD_BOUND, "f",
                      [({"a": 1}, "a", -1), ({}, "a", -1)])


def test_dict_get_default_side_effecting_default_is_refused():
    # A subscript default (``e[0]``) could raise / have side effects when
    # evaluated eagerly on the hit path; must be refused.
    assert_refused(
        dict_get_default,
        "def f(d, k, e):\n    if k in d:\n        x = d[k]\n"
        "    else:\n        x = e[0]\n    return x\n",
    )


def test_dict_get_default_unbound_name_default_is_a_documented_boundary():
    # KNOWN EDGE (not changed here): the transform rewrites an *unbound* name
    # default. ``if k in d: x = d[k] else: x = MISSING`` never touches MISSING
    # on the hit path, but ``d.get(k, MISSING)`` evaluates it eagerly -> the
    # rewrite raises NameError where the original returns a value. This diverges
    # only for source that already references an unbound name. We PIN the
    # divergence so any future tightening is a conscious, tested choice.
    src = (
        "def f(d, k):\n"
        "    if k in d:\n        x = d[k]\n    else:\n        x = MISSING\n"
        "    return x\n"
    )
    new = _rewrite(dict_get_default, src)
    assert new is not None  # current behaviour: it rewrites
    hit_orig = _exec_capture(src, "f", ({"a": 1}, "a"))
    hit_new = _exec_capture(new, "f", ({"a": 1}, "a"))
    assert hit_orig == (1, None, "")
    assert hit_new == (None, "NameError", "")  # divergence on the hit path


# --------------------------------------------------------------------------- #
# redundant_lambda:  ``lambda a, b: f(a, b)`` -> ``f``
# (DANGER: a call that is NOT a pure forward)
# --------------------------------------------------------------------------- #


def test_redundant_lambda_pure_forward_is_equivalent():
    src = ("def g(x):\n    return abs(x)\n"
           "def f(xs):\n    return sorted(xs, key=lambda v: g(v))\n")
    assert_equivalent(redundant_lambda, src, "f", [([-3, 1, -2],), ([],), ([0],)])


def test_redundant_lambda_reordered_args_is_refused():
    # ``lambda a, b: g(b, a)`` is NOT a forward — refuse, and prove it would
    # invert a non-commutative callable.
    assert_refused(redundant_lambda, "def f():\n    return (lambda a, b: g(b, a))\n")
    src = ("def g(a, b):\n    return a - b\n"
           "def f():\n    h = lambda a, b: g(b, a)\n    return h(5, 2)\n")
    orig = _exec_capture(src, "f", ())
    forced = _exec_capture(src.replace("lambda a, b: g(b, a)", "g"), "f", ())
    assert orig[0] == -3 and forced[0] == 3  # diverges


def test_redundant_lambda_extra_arg_and_kwarg_and_factory_are_refused():
    assert_refused(redundant_lambda, "def f():\n    return (lambda x: g(x, 1))\n")
    assert_refused(redundant_lambda, "def f():\n    return (lambda x: g(x, k=1))\n")
    assert_refused(redundant_lambda, "def f():\n    return (lambda x: factory()(x))\n")
    assert_refused(redundant_lambda, "def f():\n    return (lambda x: tbl[0](x))\n")


# --------------------------------------------------------------------------- #
# set_literal:  ``set([1, 2])`` -> ``{1, 2}``
# --------------------------------------------------------------------------- #


def test_set_literal_is_equivalent_including_dedup():
    src = "def f():\n    return set([1, 2, 2, 3])\n"
    assert_equivalent(set_literal, src, "f", [()])


def test_set_literal_tuple_arg_is_equivalent():
    assert_equivalent(set_literal, "def f():\n    return set((1, 2, 3))\n", "f", [()])


# --------------------------------------------------------------------------- #
# dict_literal:  ``dict(a=1, b=2)`` -> ``{"a": 1, "b": 2}``
# --------------------------------------------------------------------------- #


def test_dict_literal_is_equivalent():
    src = "def f():\n    return dict(a=1, b=2, c=3)\n"
    assert_equivalent(dict_literal, src, "f", [()])


def test_dict_literal_preserves_value_expressions():
    src = "def f(n):\n    return dict(x=n + 1, y=n * 2)\n"
    assert_equivalent(dict_literal, src, "f", [(0,), (5,), (-3,)])


# --------------------------------------------------------------------------- #
# collection_literal:  ``dict()`` -> ``{}``, ``list()`` -> ``[]``, ``tuple()`` -> ``()``
# --------------------------------------------------------------------------- #


def test_collection_literal_empty_constructors_are_equivalent():
    for ctor in ("dict", "list", "tuple"):
        src = f"def f():\n    return {ctor}()\n"
        assert_equivalent(collection_literal, src, "f", [()])


# --------------------------------------------------------------------------- #
# merge_nested_if:  ``if A:\n  if B:\n   BODY`` -> ``if A and B:\n BODY``
# (DANGER: inner else/elif, or a between/sibling statement)
# --------------------------------------------------------------------------- #


def test_merge_nested_if_short_circuit_is_equivalent():
    src = ("def f(a, b):\n    if a:\n        if b:\n            return 1\n    return 0\n")
    assert_equivalent(merge_nested_if, src, "f",
                      [(1, 1), (1, 0), (0, 1), (0, 0)])


def test_merge_nested_if_preserves_precedence_and_short_circuit_side_effects():
    # A is ``a or rec()`` — short-circuit must hold so rec() runs iff a is falsy.
    src = ("calls = []\n"
           "def rec():\n    calls.append(1)\n    return True\n"
           "def f(a, b):\n    calls.clear()\n"
           "    if a or rec():\n        if b:\n            return len(calls)\n"
           "    return len(calls)\n")
    assert_equivalent(merge_nested_if, src, "f",
                      [(True, True), (False, True), (True, False), (False, False)])


def test_merge_nested_if_inner_else_and_sibling_statement_are_refused():
    # Inner else: cannot fold into a single ``and`` guard.
    assert_refused(
        merge_nested_if,
        "def f(a, b):\n    if a:\n        if b:\n            return 1\n"
        "        else:\n            return 2\n    return 0\n",
    )
    # Sibling statement after the inner if: the outer body is not *exactly* the
    # inner if, so merging would change when that statement runs.
    assert_refused(
        merge_nested_if,
        "def f(a, b):\n    if a:\n        if b:\n            return 1\n"
        "        x = 5\n    return 0\n",
    )


# --------------------------------------------------------------------------- #
# redundant_else:  drop ``else`` after a terminating ``if`` branch
# --------------------------------------------------------------------------- #


def test_redundant_else_after_return_is_equivalent():
    src = ("def f(x):\n    if x:\n        return 1\n    else:\n        return 2\n")
    assert_equivalent(redundant_else, src, "f", [(1,), (0,), (None,), ("s",)])


def test_redundant_else_in_loop_with_continue_is_equivalent():
    # Terminator is ``continue``; the dedented else-body must keep running the
    # same statements with the same control flow.
    src = ("def f(items):\n    out = []\n    for x in items:\n"
           "        if x % 2 == 0:\n            continue\n        else:\n"
           "            out.append(x)\n    return out\n")
    assert_equivalent(redundant_else, src, "f",
                      [([1, 2, 3, 4],), ([],), ([2, 4],)])


# --------------------------------------------------------------------------- #
# unreachable_cleanup:  delete statements after an unconditional terminator
# --------------------------------------------------------------------------- #


def test_unreachable_cleanup_after_return_is_equivalent():
    src = ("def f():\n    x = 1\n    return x\n    x = 2\n    return x\n")
    assert_equivalent(unreachable_cleanup, src, "f", [()])


def test_unreachable_cleanup_after_raise_is_equivalent():
    src = ("def f(flag):\n    if flag:\n        raise ValueError('boom')\n"
           "        print('never')\n    return 'ok'\n")
    assert_equivalent(unreachable_cleanup, src, "f", [(True,), (False,)])


def test_unreachable_cleanup_keeps_nested_def_and_globals():
    # A dead ``def``/``class``/``global`` may still be imported/patched, so the
    # transform refuses to delete it. (Not an equivalence claim — a refusal of a
    # removal that could lose a still-referenceable name.)
    assert_refused(
        unreachable_cleanup,
        "def f():\n    return 1\n    def inner():\n        return 2\n",
    )


# --------------------------------------------------------------------------- #
# swap_via_tuple:  ``tmp = a; a = b; b = tmp`` -> ``a, b = b, a``
# --------------------------------------------------------------------------- #


def test_swap_via_tuple_is_equivalent():
    src = ("def f(a, b):\n    tmp = a\n    a = b\n    b = tmp\n    return (a, b)\n")
    assert_equivalent(swap_via_tuple, src, "f",
                      [(1, 2), ("x", "y"), ([1], [2]), (0, 0)])


def test_swap_via_tuple_reused_temp_is_refused():
    # ``tmp`` is read again after the swap, so it is not a throwaway; refuse.
    src = ("def f(a, b):\n    tmp = a\n    a = b\n    b = tmp\n    return (a, b, tmp)\n")
    assert_refused(swap_via_tuple, src)


# --------------------------------------------------------------------------- #
# identity_literal:  ``x is 5`` -> ``x == 5``  (REAL bug found + fixed here)
# --------------------------------------------------------------------------- #


def test_identity_literal_single_target_is_corrected_and_safe():
    # This transform is behaviour-CORRECTING (F632): ``x is 5`` only matched by
    # accident of interning, and ``x == 5`` is what was meant. Equivalence is
    # therefore proven on the value the literal denotes (the case the author
    # intended to match) and a clearly different value. We deliberately do NOT
    # feed ``5.0`` — there ``is`` (False) and ``==`` (True) legitimately differ,
    # which is exactly the latent bug the rewrite fixes, not a regression.
    new = _rewrite(identity_literal, "def f(x):\n    return x is 5\n")
    assert new is not None and "x == 5" in new
    # On the literal's own int value, interning makes ``is`` and ``==`` agree, so
    # original and corrected forms execute identically.
    for x in (5, 6, 0):
        assert _exec_capture("def f(x):\n    return x is 5\n", "f", (x,)) == \
            _exec_capture(new, "f", (x,))
    assert_equivalent(identity_literal, 'def f(x):\n    return x is not "a"\n',
                      "f", [("a",), ("b",)])


def test_identity_literal_sibling_identity_on_same_line_is_refused():
    # REGRESSION GUARD for the divergence found and fixed in this pass.
    #
    # The fix is a WHOLE-LINE regex that turns every ``is``/``is not`` followed
    # by a literal-start character into ``==``/``!=``. On a line that also holds
    # a genuine identity test opening with a bracket — ``y is (z)`` — the regex
    # used to rewrite THAT too, changing behaviour when ``is`` and ``==``
    # disagree (two ``nan`` references: ``is`` True, ``==`` False). The transform
    # now refuses any flagged line carrying more than one identity operator.
    src = (
        "n = float('nan')\n"
        "y = n\n"
        "z = n\n"
        "R = (q is 6) or (y is (z))\n"
        "def f():\n    return R\n"
    )
    # q is intentionally undefined-at-rewrite-time only in the literal sense;
    # bind it so the program runs.
    src = "q = 5\n" + src
    assert _rewrite(identity_literal, src) is None  # REFUSED

    # PROOF the refusal matters: the whole-line rewrite WOULD diverge.
    forced = src.replace("(q is 6) or (y is (z))", "(q == 6) or (y == (z))")
    orig = _exec_capture(src, "f", ())
    bad = _exec_capture(forced, "f", ())
    assert orig[0] is True and bad[0] is False  # rewriting the sibling diverges


def test_identity_literal_two_literal_targets_same_line_is_refused():
    # Conservative line-level rule: more than one identity operator on a flagged
    # line is refused even when both happen to be literals. Safety over reach.
    src = "x = 5\ny = 1\nR = (x is 5) or (y is 6)\n"
    assert _rewrite(identity_literal, src) is None
