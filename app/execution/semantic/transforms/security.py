from __future__ import annotations

import ast

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
    if "pickle" in issue:
        return _patch_pickle(rel_path, source, tree)
    if "sql" in issue or "injection" in issue:
        return _patch_sql_injection(rel_path, source, tree)
    if "yaml" in issue:
        return _patch_yaml_load(rel_path, source, tree)
    return None


def _patch_yaml_load(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    """Rewrite an unsafe ``yaml.load(x)`` call to ``yaml.safe_load(x)``.

    Unlike pickle/SQL, this has a safe, semantically-equivalent drop-in for the
    common case (loading untrusted YAML without custom tags), so we rewrite it.
    A call that already passes an explicit ``Loader=`` is left untouched.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "load"):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "yaml"):
            continue
        # Respect an explicit Loader=... (caller already chose a loader).
        if any(kw.arg == "Loader" for kw in node.keywords):
            continue

        lineno = node.lineno
        lines = source.splitlines(keepends=True)
        if lineno > len(lines):
            continue
        line_content = lines[lineno - 1]
        new_line = line_content.replace("yaml.load(", "yaml.safe_load(")
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
            transform_type="yaml_load_to_safe_load",
            rationale=[f"Replaced unsafe yaml.load() with yaml.safe_load() in {rel_path}."],
        )
    return None


def _patch_sql_injection(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    """Flag an f-string passed to .execute()/.cursor() as a SQL-injection risk.

    A correct rewrite needs to extract the interpolated values into bound
    parameters, which can't be done safely without understanding the query, so
    we annotate the call site rather than rewrite it.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in ("execute", "cursor", "executemany"):
            continue
        if not any(isinstance(a, ast.JoinedStr) for a in node.args):
            continue

        lineno = node.lineno
        lines = source.splitlines(keepends=True)
        if lineno > len(lines):
            continue
        line_content = lines[lineno - 1]
        if "Apex: SQL injection" in line_content:
            continue
        indent = line_content[: len(line_content) - len(line_content.lstrip())]
        warning = (
            f"{indent}# SECURITY (Apex: SQL injection — pass values as query "
            f"parameters, e.g. execute(sql, (a, b)), not an f-string)\n"
        )
        new_lines = list(lines)
        new_lines.insert(lineno - 1, warning)
        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": "".join(new_lines),
                "expected_old_content": source,
            }],
            transform_type="flag_sql_injection",
            rationale=[f"Flagged f-string SQL query with a security warning in {rel_path}."],
        )
    return None


def _patch_pickle(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    """Flag pickle.loads() with a security warning comment.

    Unlike eval/os.system, there is no safe drop-in replacement (pickle can
    execute arbitrary code on load, and json/msgpack are not semantically
    equivalent), so we annotate the call site rather than silently rewriting it.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "loads"):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "pickle"):
            continue

        lineno = node.lineno
        lines = source.splitlines(keepends=True)
        if lineno > len(lines):
            continue
        line_content = lines[lineno - 1]
        if "Apex: untrusted pickle" in line_content:
            continue  # already flagged
        indent = line_content[: len(line_content) - len(line_content.lstrip())]
        warning = (
            f"{indent}# SECURITY (Apex: untrusted pickle.loads can execute "
            f"arbitrary code; validate the source or use json/msgpack)\n"
        )
        new_lines = list(lines)
        new_lines.insert(lineno - 1, warning)
        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": "".join(new_lines),
                "expected_old_content": source,
            }],
            transform_type="flag_pickle_loads",
            rationale=[f"Flagged unsafe pickle.loads() with a security warning in {rel_path}."],
        )
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
        _get_indent(line_content)

        if arg_source.startswith("ast.literal_eval(") or arg_source.startswith("json.loads("):
            return None

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
        _get_indent(line_content)

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
        source.splitlines()[arg_node.lineno - 1] if arg_node.lineno <= len(source.splitlines()) else ""
        start = arg_node.col_offset
        start + len(ast.unparse(arg_node))
        return ast.unparse(arg_node)
    if isinstance(arg_node, (ast.Str, ast.Constant)):
        if isinstance(arg_node, ast.Str):
            return repr(arg_node.s)
        if isinstance(arg_node, ast.Constant) and isinstance(arg_node.value, str):
            return repr(arg_node.value)
    return ""
