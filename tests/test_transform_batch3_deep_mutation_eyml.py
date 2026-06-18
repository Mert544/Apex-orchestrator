"""Deep-mutation hardening for three behaviour-preserving FIX transforms:
``or_default``, ``startswith_tuple`` and ``isinstance_merge``.

Past the default 30-mutant cap the mutation tester (``app.engine.mutation_tester``)
seeds extra single-token faults; this file kills the REAL survivors those deeper
mutants exposed in the three transforms' *safety guards*. The highest-value kills
are the guards that, when weakened, would let a transform fire on an UNSAFE case
(a false rewrite). Concretely:

* ``or_default`` / ``startswith_tuple`` share two structural helpers — a purity
  check (only a Name or attribute-chain may be duplicated) and a structural
  equality check (the two receivers / ternary halves must be the *same* pure
  expression). A mutant that flips the recursion ``and`` in the attribute branch
  to ``or`` makes ``x.a`` and ``z.a`` (same leaf, different parent) compare
  equal, so the transform would falsely merge unrelated receivers. Those mutants
  must die.
* The ``NodeTransformer`` ``visit_*`` methods ``return node`` (the original,
  unchanged) on every refusal path. A mutant that flips this to ``return None``
  *deletes* the visited expression from the tree. The single-statement tests
  can't see this (a deleted no-match leaves ``changed`` False, so ``apply``
  returns ``None`` either way), so we pair a real match with a non-matching
  sibling expression and assert the sibling survives verbatim.
* ``isinstance_merge`` reports the number of merges it performed in its
  ``rationale``; a mutant on that counter (``changed += 1`` -> ``-= 1`` /
  ``+= 2``) is observable in the reported text, so we pin the exact count.

Several deeper survivors are genuine EQUIVALENT mutants (documented inline in
the relevant tests): boolean-connective flips guarded by a preceding
type-equality check, and defensive bounds (``li >= len(lines)``,
``end <= start``, ``... or 0``) on invariants that always hold for a parsed,
single-line node. They change source without changing behaviour and so are
intentionally not targeted.

Deterministic: fixed in-memory sources, no clock / randomness / filesystem.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms import isinstance_merge
from app.execution.semantic.transforms import or_default
from app.execution.semantic.transforms import startswith_tuple


def _expr(src: str) -> ast.expr:
    return ast.parse(src, mode="eval").body


def _new(result) -> str | None:
    return None if result is None else result.patch_requests[0]["new_content"]


# ===========================================================================
# or_default — ``a if a else b`` -> ``a or b``
# ===========================================================================

# --- purity helper ``_pure_expr`` (guards against duplicating side effects) -

def test_or_default_pure_expr_accepts_name_and_attr_chain() -> None:
    assert or_default._pure_expr(_expr("a")) is True
    assert or_default._pure_expr(_expr("a.b.c")) is True


def test_or_default_pure_expr_rejects_call_and_subscript() -> None:
    # Kills the ``_pure_expr`` fallthrough mutated from ``return False`` to
    # ``return True`` / ``return None``: an impure receiver MUST be refused, or
    # the rewrite could evaluate a side-effecting expression a different number
    # of times.
    assert or_default._pure_expr(_expr("g()")) is False
    assert or_default._pure_expr(_expr("d[k]")) is False
    assert or_default._pure_expr(_expr("a + b")) is False


# --- structural-equality helper ``_same_expr`` ------------------------------

def test_or_default_same_expr_true_only_for_identical_pure_exprs() -> None:
    assert or_default._same_expr(_expr("a"), _expr("a")) is True
    assert or_default._same_expr(_expr("x.y"), _expr("x.y")) is True


def test_or_default_same_expr_rejects_different_names() -> None:
    # Kills the Name-branch ``==`` -> ``!=`` flip.
    assert or_default._same_expr(_expr("a"), _expr("b")) is False


def test_or_default_same_expr_rejects_different_node_types() -> None:
    # Kills the type-guard fallthrough mutated from ``return False`` to
    # ``return None`` (a Name and an Attribute are never the same expression).
    assert or_default._same_expr(_expr("a"), _expr("a.b")) is False


def test_or_default_same_expr_rejects_attr_chain_with_different_parent() -> None:
    # The high-value guard kill: flipping the attribute-branch recursion ``and``
    # to ``or`` (``a.attr == b.attr and _same_expr(a.value, b.value)``) would
    # make same-leaf/different-parent receivers compare equal. ``x.y`` and
    # ``z.y`` must NOT be equal.
    assert or_default._same_expr(_expr("x.y"), _expr("z.y")) is False


def test_or_default_same_expr_rejects_attr_chain_with_different_leaf() -> None:
    assert or_default._same_expr(_expr("x.y"), _expr("x.z")) is False


def test_or_default_same_expr_rejects_non_pure_same_type() -> None:
    # Kills the final fallthrough ``return False`` -> ``return True`` / ``None``:
    # two subscripts share a node type but are not a comparable pure expression.
    assert or_default._same_expr(_expr("a[0]"), _expr("a[0]")) is False


# --- apply-level guard: no FALSE rewrite on an unsafe attribute pair ---------

def test_or_default_declines_attr_test_differs_from_body() -> None:
    # End-to-end proof of the ``_same_expr`` attribute guard: the test half and
    # body half are different attribute chains, so this is NOT ``a or b`` and
    # must be refused. A weakened guard (``and`` -> ``or``) would falsely rewrite
    # ``x.a if x.b else c`` into ``x.a or c``.
    assert or_default.apply("m.py", "def f(x, c):\n    return x.a if x.b else c\n", "t") is None


# --- visit_IfExp refusal paths must RETURN the node, never delete it --------

def test_or_default_keeps_non_matching_impure_ternary_sibling() -> None:
    # A real match plus a sibling whose test is impure (``g()``). The impure
    # ternary must be left untouched; a ``return node`` -> ``return None`` flip
    # in the purity-refusal path would delete it.
    src = "x = a if a else b\ny = g() if g() else e\n"
    out = _new(or_default.apply("m.py", src, "t"))
    assert out == "x = a or b\ny = g() if g() else e\n"


def test_or_default_keeps_non_matching_test_differs_sibling() -> None:
    # A real match plus a sibling where test != body (``c if d else e``). The
    # non-self-defaulting ternary must survive verbatim; a ``return node`` ->
    # ``return None`` flip in the same-expr-refusal path would delete it.
    src = "x = a if a else b\ny = c if d else e\n"
    out = _new(or_default.apply("m.py", src, "t"))
    assert out == "x = a or b\ny = c if d else e\n"


# --- the ``changed`` flag must start False (no spurious reformat patches) ----

def test_or_default_declines_non_matching_ternary_even_when_unparse_reformats() -> None:
    # ``self.changed`` is initialised to ``False``; a ``False`` -> ``True`` flip
    # would force every parse-able module to emit a patch (here a mere spacing
    # reformat of ``a,c,b`` -> ``a, c, b``) even though nothing was rewritten.
    src = "def f(a,c,b):\n    return a if c else b\n"
    assert or_default.apply("m.py", src, "t") is None


# ===========================================================================
# startswith_tuple — ``x.startswith("a") or x.startswith("b")`` -> tuple form
# ===========================================================================

# --- receiver-purity helper ``_is_side_effect_free_receiver`` ---------------

def test_startswith_receiver_purity_accepts_name_and_attr_chain() -> None:
    assert startswith_tuple._is_side_effect_free_receiver(_expr("a")) is True
    assert startswith_tuple._is_side_effect_free_receiver(_expr("a.b.c")) is True


def test_startswith_receiver_purity_rejects_call_and_subscript() -> None:
    # Kills the fallthrough ``return False`` -> ``return True`` / ``None``.
    assert startswith_tuple._is_side_effect_free_receiver(_expr("f()")) is False
    assert startswith_tuple._is_side_effect_free_receiver(_expr("d[0]")) is False


# --- structural-equality helper ``_structurally_equal`` ---------------------

def test_startswith_structural_equal_true_for_identical_receivers() -> None:
    assert startswith_tuple._structurally_equal(_expr("a"), _expr("a")) is True
    assert startswith_tuple._structurally_equal(_expr("x.y"), _expr("x.y")) is True


def test_startswith_structural_equal_rejects_different_names() -> None:
    assert startswith_tuple._structurally_equal(_expr("a"), _expr("b")) is False


def test_startswith_structural_equal_rejects_different_node_types() -> None:
    assert startswith_tuple._structurally_equal(_expr("a"), _expr("a.b")) is False


def test_startswith_structural_equal_rejects_attr_chain_with_different_parent() -> None:
    # High-value guard: ``and`` -> ``or`` in the attribute recursion would merge
    # ``p.m`` with ``q.m`` (same method leaf, different receiver root).
    assert startswith_tuple._structurally_equal(_expr("p.m"), _expr("q.m")) is False


def test_startswith_structural_equal_rejects_non_pure_same_type() -> None:
    assert startswith_tuple._structurally_equal(_expr("a[0]"), _expr("a[0]")) is False


# --- apply-level guard: no FALSE merge of unrelated receivers ----------------

def test_startswith_declines_same_method_different_receiver_root() -> None:
    # ``p.m.startswith`` and ``q.m.startswith`` share the method-leaf attribute
    # but have different roots; merging them would change behaviour. A weakened
    # ``_structurally_equal`` (attr ``and`` -> ``or``) would falsely merge them.
    src = 'p.m.startswith("a") or q.m.startswith("b")\n'
    assert startswith_tuple.apply("m.py", src, "t") is None


def test_startswith_declines_different_attr_method_same_root() -> None:
    src = 'x.p.startswith("a") or x.q.startswith("b")\n'
    assert startswith_tuple.apply("m.py", src, "t") is None


# --- visit_BoolOp refusal paths must RETURN the node, never delete it -------

def test_startswith_keeps_plain_or_sibling() -> None:
    # A real merge plus a plain ``c or d`` BoolOp sibling. The non-call ``or``
    # must survive; the "some operand not a qualifying call" refusal
    # (``return node`` -> ``return None``) would delete it.
    src = 'a = x.startswith("a") or x.startswith("b")\nb = c or d\n'
    out = _new(startswith_tuple.apply("m.py", src, "t"))
    assert out == "a = x.startswith(('a', 'b'))\nb = c or d\n"


def test_startswith_keeps_non_or_boolop_sibling() -> None:
    # A real merge plus an ``and`` BoolOp sibling. The non-``Or`` refusal path
    # must return the node unchanged, not delete it.
    src = 'a = x.startswith("a") or x.startswith("b")\nb = m and n\n'
    out = _new(startswith_tuple.apply("m.py", src, "t"))
    assert out == "a = x.startswith(('a', 'b'))\nb = m and n\n"


def test_startswith_keeps_mixed_method_sibling() -> None:
    # The method-mismatch refusal path (``startswith`` ored with ``endswith``)
    # must return the node, not delete it.
    src = 'a = x.startswith("a") or x.startswith("b")\nb = z.startswith("a") or z.endswith("b")\n'
    out = _new(startswith_tuple.apply("m.py", src, "t"))
    assert out == (
        "a = x.startswith(('a', 'b'))\n"
        "b = z.startswith('a') or z.endswith('b')\n"
    )


def test_startswith_keeps_different_receiver_sibling() -> None:
    # The receiver-mismatch refusal path must return the node, not delete it.
    src = 'a = x.startswith("a") or x.startswith("b")\nb = p.startswith("a") or q.startswith("b")\n'
    out = _new(startswith_tuple.apply("m.py", src, "t"))
    assert out == (
        "a = x.startswith(('a', 'b'))\n"
        "b = p.startswith('a') or q.startswith('b')\n"
    )


def test_startswith_keeps_unrelated_or_term_sibling() -> None:
    # An ``or`` mixing a qualifying call with a bare name must be refused and
    # returned unchanged, not deleted.
    src = 'a = x.startswith("a") or x.startswith("b")\nb = z.startswith("a") or flag\n'
    out = _new(startswith_tuple.apply("m.py", src, "t"))
    assert out == "a = x.startswith(('a', 'b'))\nb = z.startswith('a') or flag\n"


# ===========================================================================
# isinstance_merge — the merge counter is reported and must be exact
# ===========================================================================

def test_isinstance_merge_rationale_reports_exact_single_merge_count() -> None:
    # ``changed`` is surfaced in the rationale text. ``changed += 1`` mutated to
    # ``-= 1`` would report "Merged -1"; ``1`` -> ``2`` would report "Merged 2".
    # Pin the exact count for one merge.
    src = "def f(x):\n    return isinstance(x, int) or isinstance(x, float)\n"
    result = isinstance_merge.apply("m.py", src, "t")
    assert result is not None
    assert result.rationale == [
        "Merged 1 ored isinstance check(s) into a single tuple form in m.py "
        "(behaviour-preserving)."
    ]


def test_isinstance_merge_rationale_reports_exact_two_merge_count() -> None:
    # Two independent merges on one line: the counter must read exactly 2, which
    # also distinguishes the ``+= 1`` -> ``-= 1`` flip (would read -2).
    src = (
        "def f(x, y):\n"
        "    return (isinstance(x, int) or isinstance(x, float)) "
        "and (isinstance(y, int) or isinstance(y, str))\n"
    )
    result = isinstance_merge.apply("m.py", src, "t")
    assert result is not None
    assert result.rationale == [
        "Merged 2 ored isinstance check(s) into a single tuple form in m.py "
        "(behaviour-preserving)."
    ]
