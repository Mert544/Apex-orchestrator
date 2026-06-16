"""Idiomatic negated-membership/identity rewrites.

Rewrite ``not a in b`` -> ``a not in b`` and ``not a is b`` -> ``a is not b``.

These are *exactly* semantics-preserving: ``not (a in b)`` and ``a not in b``
evaluate to the same value (``in``/``not in`` and ``is``/``is not`` are single
operators, not ``not`` applied to a result), so the only change is to the
idiomatic spelling Python recommends (E713/E714).

Safety conditions — a node is rewritten ONLY when ALL hold:

* It is a ``UnaryOp(Not, Compare)`` — ``not`` directly wrapping a comparison.
* The inner ``Compare`` is *not chained*: exactly one operator and one
  comparator (``a in b``, never ``a in b in c``).
* That single operator is ``In`` or ``Is``.

Everything else is refused and left untouched:

* ``not a == b`` — the idiomatic form is ``a != b``, a different (and not
  purely cosmetic) transform; we never touch ``==``/``!=``.
* ``not a < b`` — ``<`` has no negation-fused spelling here.
* ``not a < b < c`` — chained comparison; ``not`` negates the whole chain and
  cannot be pushed onto one operator.
* ``not (a and b)`` — not a comparison at all.
* ``not a not in b`` / ``not a is not b`` — already-negated inner operators are
  ignored (only ``In``/``Is`` qualify), so we never double-negate.

The module re-parses its own output and asserts the only change is the intended
operator swap before emitting; on any no-op or ``SyntaxError`` it returns
``None`` and never corrupts the file.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult

# In/Is -> their fused negated counterpart. Only these two operators qualify.
_NEGATED: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.In: ast.NotIn,
    ast.Is: ast.IsNot,
}


def _is_target(node: ast.AST) -> bool:
    """True for ``not a in b`` / ``not a is b`` (single, non-chained In/Is)."""
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.Not)
        and isinstance(node.operand, ast.Compare)
        and len(node.operand.ops) == 1
        and len(node.operand.comparators) == 1
        and type(node.operand.ops[0]) in _NEGATED
    )


class _Rewriter(ast.NodeTransformer):
    def __init__(self) -> None:
        self.count = 0

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        # Recurse first so nested targets are handled too.
        self.generic_visit(node)
        if _is_target(node):
            cmp = node.operand
            assert isinstance(cmp, ast.Compare)  # narrowed by _is_target
            self.count += 1
            cmp.ops = [_NEGATED[type(cmp.ops[0])]()]
            return cmp
        return node


def _has_target(tree: ast.AST) -> bool:
    return any(_is_target(n) for n in ast.walk(tree))


def _semantically_equivalent(n_before: int, after: ast.AST) -> bool:
    """Confirm the only change is the intended operator swap: no negated-
    membership targets remain in ``after``, and it gained at least as many
    single-op ``not in``/``is not`` comparisons as the original had targets."""
    if _has_target(after):
        return False
    n_after = sum(
        1
        for n in ast.walk(after)
        if isinstance(n, ast.Compare)
        and len(n.ops) == 1
        and isinstance(n.ops[0], (ast.NotIn, ast.IsNot))
    )
    return n_before >= 1 and n_after >= n_before


def _rewrite_source(tree: ast.AST) -> tuple[str, int] | None:
    """Rewrite targets in ``tree`` and unparse; ``None`` on no-op or failure."""
    rewriter = _Rewriter()
    new_tree = rewriter.visit(tree)
    if rewriter.count == 0:
        return None
    ast.fix_missing_locations(new_tree)
    try:
        return ast.unparse(new_tree), rewriter.count
    except Exception:
        return None


def _validated_output(source: str, new_source: str, n_targets: int) -> str | None:
    """Confirm the swap is valid/equivalent; restore trailing newline."""
    if new_source == source:
        return None
    try:
        reparsed = ast.parse(new_source)
    except SyntaxError:
        return None
    if not _semantically_equivalent(n_targets, reparsed):
        return None
    # ast.unparse drops a trailing newline; restore one for a clean file.
    if source.endswith("\n") and not new_source.endswith("\n"):
        new_source += "\n"
    return new_source


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    # Count targets up front: the NodeTransformer mutates ``tree`` in place,
    # so this must be read before the rewrite consumes them.
    n_targets = sum(1 for n in ast.walk(tree) if _is_target(n))
    if n_targets == 0:
        return None

    rewritten = _rewrite_source(tree)
    if rewritten is None:
        return None
    new_source, count = rewritten

    new_source = _validated_output(source, new_source, n_targets)
    if new_source is None:
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_source,
            "expected_old_content": source,
        }],
        transform_type="simplify_not_in",
        rationale=[
            f"Rewrote {count} negated comparison(s) to idiomatic "
            f"`not in`/`is not` in {rel_path} (semantics-preserving; E713/E714)."
        ],
    )
