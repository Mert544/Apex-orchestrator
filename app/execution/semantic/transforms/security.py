from __future__ import annotations

import ast

from ..result import SemanticPatchResult
from .base import _get_indent, import_insert_index


def _select_patcher(issue: str):
    """Return the patch function whose keyword matches ``issue``, else None.

    Order matters and mirrors the original if-chain exactly: the first keyword
    group that matches wins.
    """
    for keywords, patcher in _DISPATCH:
        if any(keyword in issue for keyword in keywords):
            return patcher
    return None


def apply(rel_path: str, source: str, title: str) -> SemanticPatchResult | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    patcher = _select_patcher(title.lower())
    if patcher is None:
        return None
    return patcher(rel_path, source, tree)


def _is_weak_hash_call(node: ast.AST) -> bool:
    """``hashlib.md5()``/``sha1()`` without an explicit ``usedforsecurity=False``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr in ("md5", "sha1")):
        return False
    if not (isinstance(func.value, ast.Name) and func.value.id == "hashlib"):
        return False
    return not _has_kw_false(node, "usedforsecurity")


def _has_kw_false(node: ast.Call, name: str) -> bool:
    """True when ``node`` passes ``name=False`` as a constant keyword argument."""
    return any(kw.arg == name and isinstance(kw.value, ast.Constant)
               and kw.value.value is False for kw in node.keywords)


def _patch_weak_hash(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    """Flag a weak ``hashlib.md5()``/``sha1()`` used for security with a comment.

    There is no safe automatic rewrite: switching to sha256 changes the digest
    (breaking any stored/compared hash), and adding ``usedforsecurity=False`` is
    only correct when the caller really isn't using it for security — a judgment
    the tool can't make. So we annotate the call site, like the pickle/SQL flags.
    """
    warning_text = (
        "Apex: weak hash for security — use hashlib.sha256(), "
        "or pass usedforsecurity=False if this isn't security-related"
    )
    for node in ast.walk(tree):
        if not _is_weak_hash_call(node):
            continue
        result = _flag_call_site(
            rel_path, source, node.lineno, "Apex: weak hash", warning_text,
            "flag_weak_hash",
            f"Flagged weak hashlib.md5()/sha1() with a security warning in {rel_path}.",
        )
        if result is not None:
            return result
    return None


def _flag_call_site(rel_path: str, source: str, lineno: int, marker: str,
                    warning_text: str, transform_type: str,
                    rationale: str) -> SemanticPatchResult | None:
    """Insert a ``# SECURITY (<warning_text>)`` comment above line ``lineno``.

    Returns None when the line is out of range or already carries ``marker`` (on
    that line or the one before), so the caller can try the next occurrence.
    """
    lines = source.splitlines(keepends=True)
    if lineno > len(lines):
        return None
    line_content = lines[lineno - 1]
    prev_line = lines[lineno - 2] if lineno >= 2 else ""
    if marker in line_content or marker in prev_line:
        return None
    indent = line_content[: len(line_content) - len(line_content.lstrip())]
    warning = f"{indent}# SECURITY ({warning_text})\n"
    new_lines = list(lines)
    new_lines.insert(lineno - 1, warning)
    return SemanticPatchResult(
        patch_requests=[{
            "path": rel_path,
            "new_content": "".join(new_lines),
            "expected_old_content": source,
        }],
        transform_type=transform_type,
        rationale=[rationale],
    )


def _patch_mktemp(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    """Flag ``tempfile.mktemp()`` with a security warning comment.

    mktemp only returns a *name*; whatever opens it afterwards is a TOCTOU race.
    The safe replacements (mkstemp returns an open fd; NamedTemporaryFile returns
    a file object) have different return contracts, so there is no safe drop-in
    rewrite — we annotate the call site rather than silently change behavior,
    exactly like the pickle/SQL flags.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "mktemp"):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "tempfile"):
            continue

        lineno = node.lineno
        lines = source.splitlines(keepends=True)
        if lineno > len(lines):
            continue
        line_content = lines[lineno - 1]
        prev_line = lines[lineno - 2] if lineno >= 2 else ""
        if "Apex: insecure temp file" in line_content or "Apex: insecure temp file" in prev_line:
            continue  # already flagged (comment sits on the preceding line)
        indent = line_content[: len(line_content) - len(line_content.lstrip())]
        warning = (
            f"{indent}# SECURITY (Apex: insecure temp file — tempfile.mktemp() is a TOCTOU "
            f"race; use tempfile.mkstemp() or NamedTemporaryFile)\n"
        )
        new_lines = list(lines)
        new_lines.insert(lineno - 1, warning)
        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": "".join(new_lines),
                "expected_old_content": source,
            }],
            transform_type="flag_insecure_tempfile",
            rationale=[f"Flagged insecure tempfile.mktemp() with a security warning in {rel_path}."],
        )
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
        prev_line = lines[lineno - 2] if lineno >= 2 else ""
        if "Apex: SQL injection" in line_content or "Apex: SQL injection" in prev_line:
            continue  # already flagged (comment sits on the preceding line)
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
        prev_line = lines[lineno - 2] if lineno >= 2 else ""
        if "Apex: untrusted pickle" in line_content or "Apex: untrusted pickle" in prev_line:
            continue  # already flagged (comment sits on the preceding line)
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


def _eval_arg(node: ast.AST) -> ast.expr | None:
    """The first positional arg of a bare ``eval(...)`` call, else None."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return None
    if node.func.id != "eval" or not node.args:
        return None
    return node.args[0]


def _eval_arg_rewritable(arg_node: ast.expr) -> bool:
    """Whether ``eval(arg)`` may be narrowed to ``ast.literal_eval(arg)``.

    Declines f-strings (never a literal, would always crash) and string literals
    whose content is a runtime expression rather than a Python literal (e.g.
    ``eval("a * b")``) — rewriting those would ship code that crashes.
    """
    if isinstance(arg_node, ast.JoinedStr):
        return False
    if isinstance(arg_node, ast.Constant) and isinstance(arg_node.value, str):
        try:
            ast.literal_eval(arg_node.value)
        except (ValueError, SyntaxError, TypeError):
            return False
    return True


def _eval_line_content(lines: list[str], lineno: int) -> str:
    """The 1-based source line for ``lineno``, or "" when out of range."""
    return lines[lineno - 1] if lineno <= len(lines) else ""


def _patch_eval(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    for node in ast.walk(tree):
        arg_node = _eval_arg(node)
        if arg_node is None or not _eval_arg_rewritable(arg_node):
            continue
        arg_source = _get_arg_source(arg_node, source)
        if not arg_source:
            continue

        lineno = node.lineno
        lines = source.splitlines(keepends=True)
        line_content = _eval_line_content(lines, lineno)
        _get_indent(line_content)

        if arg_source.startswith(("ast.literal_eval(", "json.loads(")):
            return None

        new_line = line_content.replace(f"eval({arg_source})", f"ast.literal_eval({arg_source})")
        if new_line == line_content:
            # The argument source didn't match the line verbatim (e.g. a string
            # literal that isn't a Python literal). Don't emit a no-op patch that
            # would add a spurious, unused `import ast`; try the next eval.
            continue

        new_lines = list(lines)
        new_lines[lineno - 1] = new_line

        import_needed = "import ast" not in source
        if import_needed:
            new_lines.insert(import_insert_index(tree), "import ast\n")

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

        # os.system runs its argument through a shell, which TOKENISES it. The
        # equivalent shell-free call must split the command the same way, so we
        # use shlex.split — wrapping the whole string in a one-element list
        # (subprocess.run([cmd], shell=False)) would seek a single executable
        # literally named e.g. "ls -la" and fail at runtime.
        new_line = line_content.replace(
            f"os.system({arg_source})",
            f"subprocess.run(shlex.split({arg_source}), check=True)"
        )

        new_lines = list(lines)
        new_lines[lineno - 1] = new_line

        needs_subprocess = "import subprocess" not in source
        needs_shlex = "import shlex" not in source
        at = import_insert_index(tree)
        if needs_shlex:
            new_lines.insert(at, "import shlex\n")
        if needs_subprocess:
            new_lines.insert(at, "import subprocess\n")

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


def _patch_base_exception(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    """Narrow ``except BaseException:`` to ``except Exception:``.

    Only handlers that don't re-raise are rewritten (a bare ``raise`` means the
    broad catch is the intentional cleanup pattern) — mirroring the detector.
    """
    from app.engine.detectors import _exc_names, _reraises

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        if "BaseException" not in _exc_names(node.type) or _reraises(node.body):
            continue

        lineno = node.lineno
        lines = source.splitlines(keepends=True)
        line_content = lines[lineno - 1] if lineno <= len(lines) else ""

        new_line = line_content.replace("BaseException", "Exception", 1)
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
            transform_type="base_exception_to_exception",
            rationale=[
                f"Narrowed except BaseException to except Exception in {rel_path} "
                "(was swallowing KeyboardInterrupt/SystemExit)."
            ],
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
    if isinstance(arg_node, ast.JoinedStr):
        # f-string: extract the exact source so the line replacement matches
        # verbatim (reconstructing it could change quote/space style).
        return ast.get_source_segment(source, arg_node) or ""
    if isinstance(arg_node, (ast.Str, ast.Constant)):
        if isinstance(arg_node, ast.Str):
            return repr(arg_node.s)
        if isinstance(arg_node, ast.Constant) and isinstance(arg_node.value, str):
            return repr(arg_node.value)
    return ""


# Issue-keyword -> patcher dispatch, in the SAME precedence order as the
# original if-chain in ``apply``. The first group whose keyword appears in the
# lowercased title wins.
_DISPATCH = (
    (("eval",), _patch_eval),
    (("os.system",), _patch_os_system),
    (("bare except", "bareexcept"), _patch_bare_except),
    (("base-exception", "baseexception"), _patch_base_exception),
    (("pickle",), _patch_pickle),
    (("sql", "injection"), _patch_sql_injection),
    (("yaml",), _patch_yaml_load),
    (("tempfile", "mktemp"), _patch_mktemp),
    (("weak-hash", "hashlib"), _patch_weak_hash),
)
