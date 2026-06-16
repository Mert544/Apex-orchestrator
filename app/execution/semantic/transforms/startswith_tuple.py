from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from ._apply_helpers import parse_or_none as _parse_or_none
from ._apply_helpers import run_rewrite_transformer as _run_rewrite_transformer

_TARGET_METHODS = ("startswith", "endswith")


def _is_side_effect_free_receiver(node: ast.expr) -> bool:
    """A receiver is safe to duplicate only if it is a Name or a chain of
    attribute accesses bottoming out in a Name (no calls, no subscripts)."""
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_side_effect_free_receiver(node.value)
    return False


def _structurally_equal(a: ast.expr, b: ast.expr) -> bool:
    """Compare two side-effect-free receiver expressions for structural equality."""
    if type(a) is not type(b):
        return False
    if isinstance(a, ast.Name) and isinstance(b, ast.Name):
        return a.id == b.id
    if isinstance(a, ast.Attribute) and isinstance(b, ast.Attribute):
        return a.attr == b.attr and _structurally_equal(a.value, b.value)
    return False


def _as_single_arg_target_call(node: ast.expr) -> tuple[ast.expr, str, ast.expr] | None:
    """If node is `recv.startswith(arg)` / `recv.endswith(arg)` with exactly one
    positional arg (no *args/**kwargs/keywords) and the arg is not already a tuple,
    return (receiver, method_name, arg); otherwise None."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr not in _TARGET_METHODS:
        return None
    if len(node.args) != 1 or node.keywords:
        return None
    arg = node.args[0]
    if isinstance(arg, ast.Starred):
        return None
    if isinstance(arg, ast.Tuple):
        return None
    if not _is_side_effect_free_receiver(func.value):
        return None
    return func.value, func.attr, arg


def _flatten_or(node: ast.BoolOp) -> list[ast.expr]:
    """Flatten a chain of `or` operands into a flat list."""
    operands: list[ast.expr] = []
    for value in node.values:
        if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
            operands.extend(_flatten_or(value))
        else:
            operands.append(value)
    return operands


class _StartswithTupleTransformer(ast.NodeTransformer):
    def __init__(self) -> None:
        self.changed = False

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        # Recurse first so nested rewrites still happen.
        self.generic_visit(node)
        if not isinstance(node.op, ast.Or):
            return node

        operands = _flatten_or(node)
        if len(operands) < 2:
            return node

        parsed = [_as_single_arg_target_call(op) for op in operands]
        if any(p is None for p in parsed):
            # Some operand is not a qualifying call (e.g. unrelated `or` term).
            return node

        first_recv, first_method, _ = parsed[0]  # type: ignore[misc]
        args: list[ast.expr] = []
        for entry in parsed:
            recv, method, arg = entry  # type: ignore[misc]
            if method != first_method:
                return node
            if not _structurally_equal(recv, first_recv):
                return node
            args.append(arg)

        new_call = ast.Call(
            func=ast.Attribute(value=first_recv, attr=first_method, ctx=ast.Load()),
            args=[ast.Tuple(elts=args, ctx=ast.Load())],
            keywords=[],
        )
        self.changed = True
        return ast.copy_location(new_call, node)


def apply(rel_path: str, source: str, title: str = "") -> SemanticPatchResult | None:
    tree = _parse_or_none(source)
    if tree is None:
        return None

    transformer = _StartswithTupleTransformer()
    new_source = _run_rewrite_transformer(tree, transformer, source)
    if new_source is None:
        return None

    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_source,
            "expected_old_content": source,
        }],
        transform_type="startswith_tuple",
        rationale=[f"Merged ored startswith/endswith calls into a tuple argument in {rel_path}."],
    )
