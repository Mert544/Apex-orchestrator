"""Drop a trivial forwarding lambda: ``lambda a, b: f(a, b)`` -> ``f``.

A lambda that does nothing but pass its parameters straight through, in order,
to another callable is just that callable wearing a costume. ``sorted(xs,
key=lambda x: g(x))`` is exactly ``sorted(xs, key=g)`` — the wrapper only adds a
stack frame.

The rewrite is deliberately paranoid; it fires ONLY when every one of these
holds, and REFUSES otherwise:

  * the lambda has *only* plain positional params — no ``*args``, ``**kwargs``,
    keyword-only params, positional-only params, or defaults;
  * the body is a single ``Call``;
  * the call's positional args are EXACTLY the lambda's params, same count, same
    order (``lambda a, b: g(b, a)`` and ``lambda a, b: g(a)`` both refuse);
  * the call has no keyword args, no ``*``/``**`` unpacking (``lambda x: g(x,
    k=1)`` refuses), and no extra positional args (``lambda x: g(x, 1)`` refuses);
  * the callable ``f`` is a side-effect-free *reference* — a bare Name or an
    attribute chain over Names (``a.b.c``), never itself a call or subscript
    (``lambda x: factory()(x)`` refuses, ``lambda x: tbl[0](x)`` refuses).

``key=lambda x: x.lower`` is NOT touched: its body is an attribute access, not a
call, so it is not a forwarding lambda at all.

Each rewrite is verified by re-parsing the spliced file; any change that would
not parse is dropped, so the file is never corrupted. Single-line lambdas only,
so the splice into the source span stays exact.
"""

from __future__ import annotations

import ast

from ..result import SemanticPatchResult


def _is_pure_reference(node: ast.expr) -> bool:
    """True for a bare Name or an attribute chain over Names (``a.b.c``)."""
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_pure_reference(node.value)
    return False


def _has_only_plain_params(args: ast.arguments) -> bool:
    """True when the lambda has only plain positional params, no defaults."""
    # No *args / **kwargs / keyword-only / positional-only / defaults.
    if args.vararg or args.kwarg or args.kwonlyargs or args.posonlyargs:
        return False
    if args.defaults or args.kw_defaults:
        return False
    return bool(args.args)


def _call_forwards_params(body: ast.expr, params: list[str]) -> bool:
    """True when ``body`` is a plain call passing exactly ``params`` in order."""
    if not isinstance(body, ast.Call):
        return False
    # Callable must be a side-effect-free reference, never itself a call.
    if not _is_pure_reference(body.func):
        return False
    # No keyword args, no */** unpacking in the call.
    if body.keywords or any(isinstance(a, ast.Starred) for a in body.args):
        return False
    # Positional args must be EXACTLY the params, same count and order.
    if len(body.args) != len(params):
        return False
    return all(
        isinstance(arg, ast.Name) and arg.id == param
        for arg, param in zip(body.args, params)
    )


def _is_forwarding_lambda(node: ast.Lambda) -> bool:
    if not _has_only_plain_params(node.args):
        return False
    params = [a.arg for a in node.args.args]
    return _call_forwards_params(node.body, params)


def _targets(tree: ast.Module) -> list[ast.Lambda]:
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Lambda) and _is_forwarding_lambda(n)]


def _parse(source: str) -> ast.Module | None:
    """Parse ``source``; return the module, or ``None`` if it does not parse."""
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _spliced_line(lines: list[str], node: ast.Lambda) -> str | None:
    """The rewritten line for ``node``, or ``None`` when the splice must skip.

    Skips (keeping the splice exact) when the lambda spans lines, its line is
    out of range, or its column span is empty or runs past the line.
    """
    if node.lineno != node.end_lineno:
        return None  # multi-line — skip to keep the splice exact
    li = node.lineno - 1
    if li >= len(lines):
        return None
    line = lines[li]
    start, end = node.col_offset, node.end_col_offset or 0
    if end <= start or end > len(line):
        return None
    assert isinstance(node.body, ast.Call)
    replacement = ast.unparse(node.body.func)
    return line[:start] + replacement + line[end:]


def _rewrite_lines(lines: list[str], nodes: list[ast.Lambda]) -> int:
    """Splice each forwarding lambda in ``lines`` in place; return change count.

    Rightmost-first so splicing one node never shifts an earlier node's columns.
    """
    changed = 0
    for node in sorted(nodes, key=lambda n: (n.lineno, n.col_offset), reverse=True):
        new_line = _spliced_line(lines, node)
        if new_line is None:
            continue
        lines[node.lineno - 1] = new_line
        changed += 1
    return changed


def _build_result(rel_path: str, source: str, new_content: str,
                  changed: int) -> SemanticPatchResult:
    """Assemble the patch result for ``changed`` rewritten lambdas."""
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="drop_redundant_lambda",
        rationale=[
            f"Removed {changed} redundant forwarding lambda(s) "
            f"(`lambda a, b: f(a, b)` -> `f`) in {rel_path} (behaviour-preserving)."
        ],
    )


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    tree = _parse(source)
    if tree is None:
        return None
    nodes = _targets(tree)
    if not nodes:
        return None

    lines = source.splitlines(keepends=True)
    changed = _rewrite_lines(lines, nodes)
    if changed == 0:
        return None

    new_content = "".join(lines)
    if new_content == source:
        return None
    # Never corrupt the file: a spliced result that won't parse is discarded.
    if _parse(new_content) is None:
        return None

    return _build_result(rel_path, source, new_content, changed)
