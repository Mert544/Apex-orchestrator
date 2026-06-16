from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from ._apply_helpers import node_offset as _node_offset

# Constant value types that are hashable AND safe to place in a set display.
# bool is a subclass of int, so it is covered by ``int`` below, but it is listed
# for clarity. ``complex`` is hashable too, yet rarely a membership constant; it
# is intentionally omitted to keep the rewrite conservative.
_HASHABLE_CONST_TYPES = (str, bytes, int, float, bool, type(None))


def _is_hashable_constant(node: ast.expr) -> bool:
    """True when ``node`` is an ``ast.Constant`` holding a hashable literal.

    Only str/bytes/int/float/bool/None constants qualify. A list/dict/set literal
    is NOT an ``ast.Constant`` (it is a display node) and is unhashable, so it is
    refused. Names, calls and any non-constant expression are refused too because
    their runtime value is unknown and may be unhashable.
    """
    if not isinstance(node, ast.Constant):
        return False
    # ``isinstance(True, int)`` is True, so bool is already covered; the explicit
    # tuple keeps the contract readable. Reject anything outside the allow-list.
    return isinstance(node.value, _HASHABLE_CONST_TYPES)


def _rewritable_comparator(node: ast.expr) -> bool:
    """True when ``node`` is a non-empty list/tuple display of hashable constants.

    Refuses: non-display comparators (Name/Call/comprehension), empty displays
    (``x in []`` must stay — ``{}`` is a dict, and there is no empty-set literal),
    starred elements, and any element that is not a hashable constant.
    """
    if not isinstance(node, (ast.List, ast.Tuple)):
        return False
    if not node.elts:
        return False
    for elt in node.elts:
        if isinstance(elt, ast.Starred):
            return False
        if not _is_hashable_constant(elt):
            return False
    return True


def _find_compare(tree: ast.AST) -> ast.Compare | None:
    """First ``x in <display>`` / ``x not in <display>`` membership test, or None."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        # Exactly one operator and one comparator: a single membership test. A
        # chained compare like ``a in b in c`` has multiple ops and is refused.
        if len(node.ops) != 1 or len(node.comparators) != 1:
            continue
        if not isinstance(node.ops[0], (ast.In, ast.NotIn)):
            continue
        if _rewritable_comparator(node.comparators[0]):
            return node
    return None


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    compare = _find_compare(tree)
    if compare is None:
        return None

    comparator = compare.comparators[0]
    assert isinstance(comparator, (ast.List, ast.Tuple))

    # Preserve element source text exactly by slicing per element.
    element_texts: list[str] = []
    for elt in comparator.elts:
        seg = ast.get_source_segment(source, elt)
        if seg is None:
            return None
        element_texts.append(seg)

    replacement = "{" + ", ".join(element_texts) + "}"

    comp_seg = ast.get_source_segment(source, comparator)
    if comp_seg is None:
        return None

    # Splice only the comparator's exact source span, anchored at its offset, so
    # identical text elsewhere in the file is never disturbed.
    start = _node_offset(source, comparator)
    if start is None:
        return None
    end = start + len(comp_seg)
    if source[start:end] != comp_seg:
        return None
    new_source = source[:start] + replacement + source[end:]

    if new_source == source:
        return None

    # Re-parse to validate; refuse anything that does not round-trip cleanly.
    try:
        ast.parse(new_source)
    except SyntaxError:
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_source,
            "expected_old_content": source,
        }],
        transform_type="membership_set",
        rationale=[f"Rewrote membership against a list/tuple as a set literal in {rel_path}."],
    )
