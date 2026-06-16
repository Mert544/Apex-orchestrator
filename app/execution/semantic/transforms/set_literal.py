from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from ._apply_helpers import node_offset as _node_offset


def _is_builtin_set_call(node: ast.Call) -> bool:
    """True when the call is a bare ``set(...)`` (builtin Name, not an attribute)."""
    func = node.func
    return (
        isinstance(func, ast.Name)
        and func.id == "set"
        and not node.keywords
        and len(node.args) == 1
    )


def _rewritable_literal(arg: ast.expr) -> bool:
    """True when ``arg`` is a non-empty list/tuple display with no starred elements.

    An EMPTY literal MUST be refused: ``set([])`` / ``set(())`` denote the empty
    set, but ``{}`` is an empty dict, not an empty set, so there is no safe literal
    rewrite. Generators, comprehensions and starred unpacking are also refused.
    """
    if not isinstance(arg, (ast.List, ast.Tuple)):
        return False
    if not arg.elts:
        # Empty list/tuple -> would become `{}` which is a dict. Refuse.
        return False
    if any(isinstance(elt, ast.Starred) for elt in arg.elts):
        return False
    return True


def _find_call(tree: ast.AST) -> ast.Call | None:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and _is_builtin_set_call(node)
            and _rewritable_literal(node.args[0])
        ):
            return node
    return None


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    call = _find_call(tree)
    if call is None:
        return None

    arg = call.args[0]
    assert isinstance(arg, (ast.List, ast.Tuple))

    # Preserve element text exactly by slicing the original source per element.
    element_texts: list[str] = []
    for elt in arg.elts:
        seg = ast.get_source_segment(source, elt)
        if seg is None:
            return None
        element_texts.append(seg)

    replacement = "{" + ", ".join(element_texts) + "}"

    call_seg = ast.get_source_segment(source, call)
    if call_seg is None:
        return None

    # Replace only the first occurrence of the exact call text, anchored at the
    # call's source offset, so we never corrupt unrelated identical text.
    start = _node_offset(source, call)
    if start is None:
        return None
    end = start + len(call_seg)
    if source[start:end] != call_seg:
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
        transform_type="set_literal",
        rationale=[f"Rewrote set([...]) to a set literal in {rel_path}."],
    )
