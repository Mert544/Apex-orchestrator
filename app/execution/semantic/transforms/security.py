from __future__ import annotations

import ast
import re

from ..result import SemanticPatchResult
from .base import _get_indent


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    issue = title.lower()
    if "eval" in issue:
        return _patch_eval(rel_path, source, tree)
    if "os.system" in issue:
        return _patch_os_system(rel_path, source, tree)
    if "bare except" in issue or "bareexcept" in issue:
        return _patch_bare_except(rel_path, source, tree)
    return None


def _patch_eval(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "eval":
            continue
        if not node.args:
            continue
        arg_node = node.args[0]
        arg_source = _get_arg_source(arg_node, source)
        if not arg_source:
            continue

        lineno = node.lineno
        lines = source.splitlines(keepends=True)
        line_content = lines[lineno - 1] if lineno <= len(lines) else ""
        indent = _get_indent(line_content)

        if arg_source.startswith("ast.literal_eval(") or arg_source.startswith("json.loads("):
            return None

        new_call = f"ast.literal_eval({arg_source})"
        new_line = line_content.replace(f"eval({arg_source})", f"ast.literal_eval({arg_source})")

        new_lines = list(lines)
        new_lines[lineno - 1] = new_line

        import_needed = "import ast" not in source
        if import_needed:
            new_lines.insert(0, "import ast\n")

        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": "".join(new_lines),
                "expected_old_content": source,
            }],
            transform_type="eval_to_literal_eval",
            rationale=[f"Replaced eval() with ast.literal_eval() for safety in {rel_path}."],
        )

    return None


def _patch_os_system(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name):
            continue
        if node.func.value.id != "os":
            continue
        if node.func.attr != "system":
            continue

        if not node.args:
            continue
        arg_source = _get_arg_source(node.args[0], source)
        if not arg_source:
            continue

        lineno = node.lineno
        lines = source.splitlines(keepends=True)
        line_content = lines[lineno - 1] if lineno <= len(lines) else ""
        indent = _get_indent(line_content)

        new_line = line_content.replace(
            f"os.system({arg_source})",
            f"subprocess.run([{arg_source}], shell=False, check=True)"
        )

        new_lines = list(lines)
        new_lines[lineno - 1] = new_line

        needs_subprocess = "import subprocess" not in source
        needs_ast = "import ast" not in source
        if needs_subprocess:
            new_lines.insert(0, "import subprocess\n")
        if needs_ast:
            new_lines.insert(0, "import ast\n")

        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": "".join(new_lines),
                "expected_old_content": source,
            }],
            transform_type="os_system_to_subprocess",
            rationale=[f"Replaced os.system() with subprocess.run() for safety in {rel_path}."],
        )

    return None


def _patch_bare_except(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is not None:
            continue

        lineno = node.lineno
        lines = source.splitlines(keepends=True)
        line_content = lines[lineno - 1] if lineno <= len(lines) else ""

        new_line = line_content.replace("except:", "except Exception:")
        if new_line == line_content:
            continue

        new_lines = list(lines)
        new_lines[lineno - 1] = new_line

        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": "".join(new_lines),
                "expected_old_content": source,
            }],
            transform_type="bare_except_to_exception",
            rationale=[f"Replaced bare except with except Exception in {rel_path}."],
        )

    return None


def _get_arg_source(arg_node: ast.expr, source: str) -> str:
    if isinstance(arg_node, ast.Name):
        return arg_node.id
    if isinstance(arg_node, ast.Attribute):
        return _get_arg_source(arg_node.value, source)
    if isinstance(arg_node, ast.Call):
        full_source = source.splitlines()[arg_node.lineno - 1] if arg_node.lineno <= len(source.splitlines()) else ""
        start = arg_node.col_offset
        end = start + len(ast.unparse(arg_node))
        return ast.unparse(arg_node)
    if isinstance(arg_node, (ast.Str, ast.Constant)):
        if isinstance(arg_node, ast.Str):
            return repr(arg_node.s)
        if isinstance(arg_node, ast.Constant) and isinstance(arg_node.value, str):
            return repr(arg_node.value)
    return ""
