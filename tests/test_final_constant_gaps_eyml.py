"""Coverage gaps for :mod:`app.execution.final_constant` — the missing branches the
objective suite (``test_finalize_constant_objective_eyml``) does not already hit:

  - an annotated ``NAME: T = <literal>`` whose NAME is NOT a constant (lower-case) or
    whose value is NOT a literal — the ``AnnAssign`` refusal path (``_const_assign``);
  - a whole-project ``project_sources`` list containing an UNPARSEABLE source — the
    per-source parse guard in :func:`rebound_names` skips it and still lands;
  - a finalizable constant whose VALUE begins on a LATER physical line (a parenthesised
    ``(\n 1\n)``) so the single-line header splice refuses — ``add_final_constant``
    tries the candidate, cannot splice, and returns ``None``;
  - the two DEFENSIVE splice/annotation guards (``_annotation_is_final(None)`` and a
    header line with no spliceable ``=`` before the value column) that are unreachable
    through the public API but documented, exercised here directly as characterization.

Everything deterministic (pure AST + line splice, no clock/random/network).
"""

from __future__ import annotations

import ast

from app.execution.final_constant import (
    _annotation_is_final,
    _splice_annotation,
    add_final_constant,
    finalizable_constants,
)


def test_refuses_annotated_lowercase_name():
    # ``x: int = 5`` is an AnnAssign with a NON-constant (lower-case) name — the
    # AnnAssign branch of ``_const_assign`` refuses it (const-name gate), so it is not
    # finalizable even though the value is a literal.
    assert finalizable_constants("x: int = 5\n") == []
    assert add_final_constant("x: int = 5\n") is None


def test_refuses_annotated_non_literal_value():
    # ``FOO: int = bar`` is an AnnAssign whose value is a Name, not a literal — the
    # AnnAssign branch refuses on the literal-value gate.
    assert add_final_constant("FOO: int = bar\n") is None
    assert finalizable_constants("FOO: int = bar\n") == []


def test_project_sources_with_unparseable_source_is_skipped():
    # The whole-project rebind scan tolerates an UNPARSEABLE sibling source (the
    # per-source parse guard in ``rebound_names`` ``continue``s past it) and still
    # lands ``Final`` on the good module's constant.
    good = "MAX = 3\n"
    out = add_final_constant(good, ["MAX = 3\n", "def (  # not valid python\n"])
    assert out is not None
    assert "MAX: Final = 3" in out
    ast.parse(out)


def test_refuses_when_value_starts_on_a_later_line():
    # A parenthesised value that begins on the NEXT physical line: the constant is
    # finalizable in isolation, but the single-line header splice cannot place the
    # annotation, so ``add_final_constant`` skips the candidate and returns ``None``.
    src = "FOO = (\n    1\n)\n"
    assert finalizable_constants(src) == ["FOO"]  # provably a literal constant
    assert add_final_constant(src) is None  # header not cleanly spliceable


def test_annotation_is_final_false_for_none():
    # Defensive guard: a missing annotation is never ``Final``-shaped (unreachable via
    # the public API — an AnnAssign always carries an annotation — but documented).
    assert _annotation_is_final(None) is False


def test_splice_refuses_header_without_equals_before_value():
    # Defensive guard: when the header line carries no ``=`` before the value's column
    # (an artificial lines/node mismatch), ``_splice_annotation`` refuses (returns
    # ``None``) rather than mis-splice — the ``eq_index == -1`` boundary.
    node = ast.parse("FOO = 1").body[0]
    assert _splice_annotation(node, ["FOO   1"], "Final") is None
