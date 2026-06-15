"""Collapse a defensive ``if K in d`` lookup into ``d.get(K, DEFAULT)``.

The pattern::

    if K in d:
        x = d[K]
    else:
        x = DEFAULT

is exactly ``x = d.get(K, DEFAULT)`` *only* when ``d`` and ``K`` are
side-effect-free (plain names / constants) and the same expression appears in
the membership test and the subscript. ``dict.get`` evaluates ``d`` and ``K``
once and returns the default on a miss, so the rewrite is behaviour-preserving
under those conditions.

This transform is deliberately narrow: it rewrites only that exact two-branch
shape with a single same-target assignment in each branch. Anything richer — a
mutated container, extra statements, mismatched targets, a side-effectful
subscript, a non-``Name`` container — is refused (``None``). The rewritten
source is re-parsed; if it does not parse, the transform refuses.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from .base import _get_indent


def _is_simple_key(node: ast.expr) -> bool:
    """A key with no side effects and no evaluation-order risk."""
    return isinstance(node, (ast.Name, ast.Constant))


def _is_simple_container(node: ast.expr) -> bool:
    """A container expression cheap and safe to evaluate (a bare ``Name``).

    Restricting to ``Name`` guarantees ``d`` in the test and the subscript are
    the same access with no call/index/attribute side effects.
    """
    return isinstance(node, ast.Name)


def _same_expr(a: ast.expr, b: ast.expr) -> bool:
    """Structural equality of two simple expressions (names / constants)."""
    if isinstance(a, ast.Name) and isinstance(b, ast.Name):
        return a.id == b.id
    if isinstance(a, ast.Constant) and isinstance(b, ast.Constant):
        return type(a.value) is type(b.value) and a.value == b.value
    return False


def _assign_single_name(stmt: ast.stmt) -> tuple[ast.Name, ast.expr] | None:
    """Return ``(target, value)`` for ``name = value``; ``None`` otherwise."""
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Name) or not isinstance(target.ctx, ast.Store):
        return None
    return target, stmt.value


def _matches(node: ast.If) -> str | None:
    """If ``node`` is the canonical shape, return the replacement RHS source.

    The replacement is the full ``target = d.get(K, DEFAULT)`` statement text
    (no indentation); the caller prefixes the block's indentation.
    """
    # Exactly one statement in each branch; no elif / extra orelse.
    if len(node.body) != 1 or len(node.orelse) != 1:
        return None

    if_assign = _assign_single_name(node.body[0])
    else_assign = _assign_single_name(node.orelse[0])
    if if_assign is None or else_assign is None:
        return None
    if_target, if_value = if_assign
    else_target, else_value = else_assign

    # Both branches must assign the SAME simple target name.
    if if_target.id != else_target.id:
        return None

    # The test must be exactly ``K in d`` with a single membership operator.
    test = node.test
    if (not isinstance(test, ast.Compare)
            or len(test.ops) != 1
            or not isinstance(test.ops[0], ast.In)
            or len(test.comparators) != 1):
        return None
    test_key = test.left
    test_container = test.comparators[0]
    if not _is_simple_key(test_key) or not _is_simple_container(test_container):
        return None

    # The if-branch value must be exactly ``d[K]`` (a simple subscript) using the
    # SAME container and key as the membership test.
    if (not isinstance(if_value, ast.Subscript)
            or not isinstance(if_value.ctx, ast.Load)):
        return None
    sub_container = if_value.value
    sub_key = if_value.slice
    if not _is_simple_container(sub_container) or not _is_simple_key(sub_key):
        return None
    if not _same_expr(test_container, sub_container):
        return None
    if not _same_expr(test_key, sub_key):
        return None

    # The default (else value) must itself be side-effect-free so evaluating it
    # as ``get``'s second argument keeps behaviour — same guarantee as the key.
    if not _is_simple_key(else_value):
        return None

    container_src = ast.unparse(sub_container)
    key_src = ast.unparse(sub_key)
    default_src = ast.unparse(else_value)
    return f"{if_target.id} = {container_src}.get({key_src}, {default_src})"


def _is_expected_get(stmt: ast.stmt | None) -> bool:
    """The rewritten statement is exactly ``target = <name>.get(K, DEFAULT)``."""
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return False
    if not isinstance(stmt.targets[0], ast.Name):
        return False
    val = stmt.value
    return (isinstance(val, ast.Call)
            and isinstance(val.func, ast.Attribute)
            and val.func.attr == "get"
            and len(val.args) == 2
            and not val.keywords)


def _statement_at(tree: ast.Module, lineno: int) -> ast.stmt | None:
    """The first statement in ``tree`` that begins at ``lineno`` (1-based)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and node.lineno == lineno:
            return node
    return None


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    lines = source.splitlines(keepends=True)

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        replacement = _matches(node)
        if replacement is None:
            continue

        start = node.lineno - 1
        end = node.end_lineno or node.lineno  # 1-based inclusive last line
        if start >= len(lines) or end > len(lines):
            continue
        indent = _get_indent(lines[start])
        # Preserve the line ending used on the block's last physical line so the
        # spliced statement matches the file's newline convention.
        last = lines[end - 1]
        if last.endswith("\r\n"):
            newline = "\r\n"
        elif last.endswith("\n"):
            newline = "\n"
        elif last.endswith("\r"):
            newline = "\r"
        else:
            newline = ""  # block ended at EOF with no trailing newline
        new_block = f"{indent}{replacement}{newline}"

        new_lines = lines[:start] + [new_block] + lines[end:]
        new_content = "".join(new_lines)

        # Re-parse; refuse if the rewrite does not parse or is not the expected
        # ``target = d.get(K, DEFAULT)`` assignment at the same start line.
        try:
            new_tree = ast.parse(new_content)
        except SyntaxError:
            continue
        if not _is_expected_get(_statement_at(new_tree, node.lineno)):
            continue

        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": new_content,
                "expected_old_content": source,
            }],
            transform_type="dict_get_default",
            rationale=[
                f"Collapsed an `if K in d` / `else` lookup into `d.get(K, DEFAULT)` "
                f"in {rel_path} (behaviour-preserving)."
            ],
        )
    return None
