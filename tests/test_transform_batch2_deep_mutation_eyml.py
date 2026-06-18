"""Deep-mutation hardening for three behaviour-preserving FIX transforms.

These characterization tests pin the deep mutation survivors (past the standard
30-mutant cap) found by ``app.engine.mutation_tester`` for:

  * ``augmented_assign`` — already fully killed at 12 sites; a couple of
    public-API characterizations are added as regression anchors.
  * ``double_not`` — survivors live in the ``_replace_span`` defensive guards
    (``or``/boundary flips) which never fire through the public ``apply`` path
    because every node comes from a real parse; we kill them by calling
    ``_replace_span`` directly with crafted node positions. The two
    ``return False -> return None`` survivors in ``_is_double_not`` are
    behaviour-equivalent through ``apply`` (both falsy) but pinned here via a
    direct ``is False`` assertion.
  * ``negated_comparison`` — the rightmost-first splice order (``reverse=True``)
    is the load-bearing correctness invariant for nested same-line rewrites; the
    ``changed`` counter init/increment is observable in the rationale.

Each test names the behaviour it locks down. Deterministic, stdlib + pytest.
"""

from __future__ import annotations

import ast

from app.execution.semantic.transforms import augmented_assign as aa
from app.execution.semantic.transforms import double_not as dn
from app.execution.semantic.transforms import negated_comparison as nc


# ---------------------------------------------------------------------------
# augmented_assign — public-API regression anchors (all 12 sites already killed)
# ---------------------------------------------------------------------------


def _aa_apply(src: str) -> str | None:
    r = aa.apply("m.py", src)
    return r.patch_requests[0]["new_content"] if r else None


def test_aa_floordiv_is_not_confused_with_div():
    # Guards the `_AUG_OPS` membership + left-name-equality checks together.
    assert _aa_apply("x = x // 2\n") == "x //= 2\n"


def test_aa_refuses_name_on_right_exactly():
    # `left.id != target.id` must hold for the repeated-name-on-left rule.
    assert _aa_apply("x = a + x\n") is None
    assert _aa_apply("x = x + a\n") == "x += a\n"


# ---------------------------------------------------------------------------
# double_not — `_is_double_not` return-value pinning (L28 / L31 survivors)
# ---------------------------------------------------------------------------


def _first_value(src: str) -> ast.AST:
    return ast.parse(src).body[0].value


def test_dn_non_unaryop_returns_exactly_false():
    # L28 first guard: node is not `UnaryOp(Not, ...)` at all (a plain Name).
    # Kills the first `return False -> return None`.
    node = _first_value("y = x")
    assert dn._is_double_not(node) is False


def test_dn_non_not_unaryop_returns_exactly_false():
    # L28 first guard via a UnaryOp whose op is NOT `Not` (bitwise invert).
    node = _first_value("y = ~x")
    assert dn._is_double_not(node) is False


def test_dn_single_not_inner_returns_exactly_false():
    # L31 second guard: outer is `UnaryOp(Not, ...)` but the inner operand is a
    # plain Name, not another `Not`. Kills the second `return False -> None`.
    node = _first_value("y = not x")
    assert dn._is_double_not(node) is False


def test_dn_boolop_inner_returns_exactly_false():
    # L31 second guard: inner is a BoolOp, not a plain Not.
    node = _first_value("y = not (not a and b)")
    assert dn._is_double_not(node) is False


def test_dn_genuine_double_not_returns_true():
    node = _first_value("y = not not x")
    assert dn._is_double_not(node) is True


# ---------------------------------------------------------------------------
# double_not._replace_span — defensive-guard survivors (L101 / L105 / L110)
# These guards never fire through `apply` (real nodes always carry valid
# positions); we exercise them directly to kill the `or`/boundary mutants.
# ---------------------------------------------------------------------------


class _Pos:
    """A minimal positioned-node stand-in for ``_replace_span``."""

    def __init__(self, lineno, col_offset, end_lineno, end_col_offset):
        self.lineno = lineno
        self.col_offset = col_offset
        self.end_lineno = end_lineno
        self.end_col_offset = end_col_offset


_SRC = "y = not not x\n"


def test_dn_replace_span_real_node_round_trips():
    # The single happy path: a real double-not node splices cleanly.
    node = ast.parse(_SRC).body[0].value
    assert dn._replace_span(_SRC, node, "bool(x)") == "y = bool(x)\n"


def test_dn_replace_span_none_position_short_circuits():
    # L101: `lineno is None or col is None or end_lineno is None or end_col is
    # None`. With only ONE field None, the original (`or`) returns None; an
    # `and`-mutant would proceed and splice -> asserting None kills `or->and`.
    assert dn._replace_span(_SRC, _Pos(1, None, 1, 5), "Z") is None
    assert dn._replace_span(_SRC, _Pos(None, 0, 1, 5), "Z") is None
    assert dn._replace_span(_SRC, _Pos(1, 0, None, 5), "Z") is None
    assert dn._replace_span(_SRC, _Pos(1, 0, 1, None), "Z") is None


def test_dn_replace_span_lineno_below_one_short_circuits():
    # L105: `node.lineno < 1 or end_lineno > len(lines)` — first disjunct alone.
    assert dn._replace_span(_SRC, _Pos(0, 0, 1, 1), "Z") is None


def test_dn_replace_span_end_lineno_past_eof_short_circuits():
    # L105: second disjunct alone -> kills `or->and` (needs both for `and`).
    assert dn._replace_span(_SRC, _Pos(1, 0, 99, 1), "Z") is None


def test_dn_replace_span_start_after_end_short_circuits():
    # L110: `start_idx > end_idx` first disjunct alone (col after end col).
    assert dn._replace_span(_SRC, _Pos(1, 8, 1, 0), "Z") is None


def test_dn_replace_span_end_past_source_short_circuits():
    # L110: `end_idx > len(source)` second disjunct alone.
    assert dn._replace_span(_SRC, _Pos(1, 0, 1, 999), "Z") is None


def test_dn_replace_span_boundary_start_equals_end_still_splices():
    # L110 boundary: `start_idx > end_idx` must be STRICT. When start==end the
    # original proceeds (inserts at that point); a `>=` mutant would short to
    # None. Asserting a non-None splice kills the `>`->`>=` boundary mutant.
    assert dn._replace_span(_SRC, _Pos(1, 5, 1, 5), "Z") == "y = nZot not x\n"


def test_dn_replace_span_boundary_end_equals_len_still_splices():
    # L110 boundary: `end_idx > len(source)` must be STRICT. end==len(source) is
    # in-range; original splices, `>=` mutant returns None.
    assert dn._replace_span(_SRC, _Pos(1, 0, 1, len(_SRC)), "Z") == "Z"


# ---------------------------------------------------------------------------
# negated_comparison — splice order + changed-counter survivors (L43/L45/L56)
# ---------------------------------------------------------------------------


def _nc_apply(src: str):
    return nc.apply("m.py", src, "fix negated comparison")


def _nc_content(src: str) -> str | None:
    r = _nc_apply(src)
    return r.patch_requests[0]["new_content"] if r else None


def test_nc_nested_same_line_requires_rightmost_first_order():
    # L45 `reverse=True`: nested negated comparisons on one line. The outer span
    # fully contains the inner; only rightmost-first splicing keeps both spans
    # exact. A `reverse=False` mutant corrupts the second (overlapping) splice
    # into unparseable garbage, so this exact, parseable output kills it.
    out = _nc_content("r = not (not a in b) in c\n")
    assert out == "r = (not a in b) not in c\n"
    ast.parse(out)


def test_nc_multiline_only_targets_return_none():
    # L43 `changed = 0` initialiser: a sole multi-line target is skipped, so
    # `changed` stays 0 and `apply` returns None. A `changed = 1` mutant would
    # emit a no-op patch instead. Asserting None pins the initial counter value.
    multiline = "y = not a in (\n    b\n)\n"
    assert _nc_apply(multiline) is None


def test_nc_rationale_reports_exact_change_count_one():
    # L56 `changed += 1` (number 1->2 and `+=`->`-=`): a single rewrite must
    # report "Rewrote 1". Mutants report "Rewrote 2" / "Rewrote -1".
    r = _nc_apply("y = not a in b\n")
    assert r is not None
    assert "Rewrote 1 negated" in r.rationale[0]


def test_nc_rationale_reports_exact_change_count_two():
    # Two rewrites on one line -> "Rewrote 2"; reinforces the counter increment.
    r = _nc_apply("x = (not a in b, not c in d)\n")
    assert r is not None
    assert "Rewrote 2 negated" in r.rationale[0]
    assert r.patch_requests[0]["new_content"] == "x = (a not in b, c not in d)\n"
