from __future__ import annotations

import ast

from ..result import SemanticPatchResult


def _collect_used_names(tree: ast.AST) -> set[str]:
    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used_names.add(node.id)
        if (isinstance(node, ast.Attribute)) and (isinstance(node.value, ast.Name)):
            used_names.add(node.value.id)
    return used_names


def _has_noqa(src_lines: list[str], node: ast.AST) -> bool:
    # A noqa marker is a human saying "this import is intentional"
    # (re-export surfaces, side-effect imports) — honour it.
    return any("noqa" in src_lines[i - 1]
               for i in range(node.lineno,
                              getattr(node, "end_lineno", node.lineno) + 1))


def _import_is_unused(node: ast.Import, used_names: set[str]) -> bool:
    for alias in node.names:
        name = alias.asname or alias.name.split(".")[0]
        if name in used_names:
            return False
    return True


def _import_from_is_unused(node: ast.ImportFrom, used_names: set[str]) -> bool:
    module = node.module or ""
    for alias in node.names:
        name = alias.asname or alias.name
        if name in used_names:
            return False
    if module.split(".")[0] in used_names:
        return False
    return True


def _node_lines(node: ast.AST) -> range:
    return range(node.lineno, getattr(node, "end_lineno", node.lineno) + 1)


def _collect_unused_lines(tree: ast.AST, src_lines: list[str],
                          used_names: set[str]) -> set[int]:
    unused_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        # __future__ imports are compiler directives, not bindings — they
        # are never "unused" (found by dogfooding: this transform stripped
        # `from __future__ import annotations` from three live modules).
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        if _has_noqa(src_lines, node):
            continue
        if isinstance(node, ast.Import):
            all_unused = _import_is_unused(node, used_names)
        else:
            all_unused = _import_from_is_unused(node, used_names)
        if all_unused:
            unused_lines.update(_node_lines(node))
    return unused_lines


def _build_result(rel_path: str, source: str,
                  unused_lines: set[int]) -> SemanticPatchResult:
    lines = source.splitlines(keepends=True)
    new_lines = [line for i, line in enumerate(lines, start=1) if i not in unused_lines]
    new_content = "".join(new_lines)
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": new_content,
            "expected_old_content": source,
        }],
        transform_type="organize_imports",
        rationale=[f"Removed {len(unused_lines)} unused import lines in {rel_path}."],
    )


def apply(rel_path: str, source: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return None

    used_names = _collect_used_names(tree)
    src_lines = source.splitlines()
    unused_lines = _collect_unused_lines(tree, src_lines, used_names)

    if not unused_lines:
        return None

    return _build_result(rel_path, source, unused_lines)
