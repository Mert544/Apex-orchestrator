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


def _walk_attr_calls(tree: ast.Module, attr: str, owner: str | None):
    """Yield each ``owner.attr(...)`` call node in ``tree``.

    When ``owner`` is None, any ``X.attr(...)`` matches (the receiver is an
    arbitrary expression, e.g. ``tarfile.open(p).extractall()``); otherwise the
    receiver must be the plain name ``owner``.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == attr):
            continue
        if owner is None:
            yield node
        elif isinstance(func.value, ast.Name) and func.value.id == owner:
            yield node


def _patch_os_popen(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    """Flag ``os.popen(...)`` with a security warning comment.

    os.popen runs the command through a shell (injection-prone) and returns a
    file-like object; the safe replacement (subprocess.run/Popen) has a different
    return contract, so there is no behaviour-preserving drop-in. We annotate the
    call site, exactly like the pickle/SQL flags.
    """
    warning_text = (
        "Apex: os.popen runs a shell (injection-prone); use subprocess.run() "
        "with a list of args"
    )
    for node in _walk_attr_calls(tree, "popen", "os"):
        result = _flag_call_site(
            rel_path, source, node.lineno, "Apex: os.popen", warning_text,
            "flag_os_popen",
            f"Flagged os.popen() with a security warning in {rel_path}.")
        if result is not None:
            return result
    return None


def _patch_tls_verify(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    """Flag an HTTP client call that disables TLS verification (``verify=False``).

    Flipping ``verify`` back to True could break a caller that intentionally
    talks to a self-signed endpoint, so we annotate rather than rewrite — the
    correct fix (pin a CA bundle, fix the cert) is contextual.
    """
    warning_text = (
        "Apex: TLS verification disabled (verify=False) enables "
        "man-in-the-middle attacks; remove it or pin a trusted CA bundle"
    )
    for node in ast.walk(tree):
        if not _is_tls_verify_disabled(node):
            continue
        result = _flag_call_site(
            rel_path, source, node.lineno, "Apex: TLS verification", warning_text,
            "flag_tls_verify",
            f"Flagged disabled TLS verification with a security warning in {rel_path}.")
        if result is not None:
            return result
    return None


def _is_tls_verify_disabled(node: ast.AST) -> bool:
    """``requests``/``httpx`` verb call passing a literal ``verify=False``."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    func = node.func
    if not (isinstance(func.value, ast.Name) and func.value.id in ("requests", "httpx")):
        return False
    return _has_kw_false(node, "verify")


def _patch_zip_slip(rel_path: str, source: str, tree: ast.Module) -> SemanticPatchResult | None:
    """Flag an unguarded ``.extractall(...)`` (Zip-Slip / path traversal).

    A safe rewrite would have to validate every member path against the target
    directory (or inject ``filter="data"``, which is 3.12-only and changes
    behaviour on older runtimes), so we annotate the call site instead.
    """
    warning_text = (
        "Apex: Zip-Slip — archive extractall() without a member guard allows "
        "path traversal; validate each member or pass filter=\"data\" (Python 3.12+)"
    )
    for node in _walk_attr_calls(tree, "extractall", None):
        if any(kw.arg in ("members", "filter") or kw.arg is None for kw in node.keywords):
            continue  # already guarded (or **kwargs may guard) — mirror the detector
        result = _flag_call_site(
            rel_path, source, node.lineno, "Apex: Zip-Slip", warning_text,
            "flag_zip_slip",
            f"Flagged unguarded archive extractall() with a security warning in {rel_path}.")
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


def _is_hashlib_new_weak_call(node: ast.AST) -> bool:
    """``hashlib.new("md5"|"sha1")`` not already ``usedforsecurity=False``."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    func = node.func
    if not (func.attr == "new" and isinstance(func.value, ast.Name)
            and func.value.id == "hashlib"):
        return False
    if not (node.args and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.lower() in ("md5", "sha1")):
        return False
    return not _has_kw_false(node, "usedforsecurity")


def _replace_call_segment(source: str, node: ast.Call, new_segment: str) -> str | None:
    """Return ``source`` with ``node``'s exact source segment replaced.

    Single-occurrence, single-line-anchored replacement: the original segment is
    looked up verbatim via ``ast.get_source_segment`` and swapped once. Returns
    None when the segment can't be recovered or doesn't appear verbatim (so the
    caller declines rather than emit a corrupt patch).
    """
    old_segment = ast.get_source_segment(source, node)
    if not old_segment or old_segment not in source:
        return None
    return source.replace(old_segment, new_segment, 1)


def _patch_hashlib_new_weak(rel_path: str, source: str,
                            tree: ast.Module) -> SemanticPatchResult | None:
    """Append ``usedforsecurity=False`` to ``hashlib.new("md5"|"sha1")``.

    This is a provably-safe auto-rewrite: ``usedforsecurity=False`` does not
    change the digest bytes the call produces (it only declares intent and, on
    FIPS builds, keeps the construction permitted), so any stored/compared hash
    stays identical. We only touch the string-form constructor whose first arg is
    a literal weak-digest name; a dynamic name, or a call already carrying the
    flag, is left alone — mirroring the detector exactly.
    """
    for node in ast.walk(tree):
        if not _is_hashlib_new_weak_call(node):
            continue
        old_segment = ast.get_source_segment(source, node)
        if not old_segment or not old_segment.endswith(")"):
            continue
        new_segment = old_segment[:-1] + ", usedforsecurity=False)"
        new_content = _replace_call_segment(source, node, new_segment)
        if new_content is None or new_content == source:
            continue
        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": new_content,
                "expected_old_content": source,
            }],
            transform_type="hashlib_new_usedforsecurity_false",
            rationale=[f"Declared hashlib.new() weak hash non-security with "
                       f"usedforsecurity=False in {rel_path}."],
        )
    return None


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


# Shell metacharacters that make a command un-tokenisable by a plain
# shlex.split. A literal carrying any of these is NOT rewritten (kept as a flag).
_SHELL_METACHARS = frozenset(";&|`$><()*?[]{}~!#\\\"'\n\t")


def _shell_true_runner(node: ast.AST) -> ast.Call | None:
    """``node`` if it is a ``subprocess`` runner call passing ``shell=True``."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return None
    func = node.func
    runners = ("run", "call", "Popen", "check_output", "check_call")
    if not (func.attr in runners and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"):
        return None
    return node if _has_kw_true(node, "shell") else None


def _has_kw_true(node: ast.Call, name: str) -> bool:
    return any(kw.arg == name and isinstance(kw.value, ast.Constant)
               and kw.value.value is True for kw in node.keywords)


def _safe_literal_command(node: ast.Call) -> ast.Constant | None:
    """The first-arg string literal of a ``shell=True`` call, if rewrite-safe.

    Safe means: a plain ``str`` constant with non-empty content and NO shell
    metacharacter — the only case where ``shell=True`` + a string equals
    ``shell=False`` + ``shlex.split("<literal>")``. Otherwise None.
    """
    if not (node.args and isinstance(node.args[0], ast.Constant)):
        return None
    arg = node.args[0]
    if not isinstance(arg.value, str) or not arg.value.strip():
        return None
    if any(ch in _SHELL_METACHARS for ch in arg.value):
        return None
    return arg


def _patch_subprocess_shell_literal(rel_path: str, source: str,
                                    tree: ast.Module) -> SemanticPatchResult | None:
    """Rewrite ``subprocess.run("<literal>", shell=True)`` to a shell-free call.

    Provably behaviour-preserving ONLY for a metachar-free string literal: with a
    bare command the shell does nothing but whitespace-tokenise the string, which
    ``shlex.split`` reproduces exactly, and dropping the shell removes the entire
    injection surface. The first arg becomes ``shlex.split("<literal>")`` and
    ``shell=True`` becomes ``shell=False``. A dynamic arg, a list, an empty
    string, or any shell metacharacter makes the call decline (it stays a flag).
    """
    for node in ast.walk(tree):
        call = _shell_true_runner(node)
        if call is None:
            continue
        literal = _safe_literal_command(call)
        if literal is None:
            continue
        new_content = _rewrite_shell_literal(source, call, literal)
        if new_content is None or new_content == source:
            continue
        new_lines = new_content.splitlines(keepends=True)
        if "import shlex" not in source:
            new_lines.insert(import_insert_index(tree), "import shlex\n")
        return SemanticPatchResult(
            patch_requests=[{
                "path": rel_path,
                "new_content": "".join(new_lines),
                "expected_old_content": source,
            }],
            transform_type="subprocess_shell_literal_to_shlex",
            rationale=[f"Ran subprocess shell-free with shlex.split() (removed "
                       f"shell=True) in {rel_path}."],
        )
    return None


def _rewrite_shell_literal(source: str, call: ast.Call,
                           literal: ast.Constant) -> str | None:
    """Replace the call's segment: literal -> shlex.split(literal), shell=True -> False.

    Both replacements are anchored to the call's exact source segment so a
    matching token elsewhere in the file is never touched. Returns None if the
    segment can't be recovered verbatim.
    """
    seg = ast.get_source_segment(source, call)
    lit_seg = ast.get_source_segment(source, literal)
    if not seg or not lit_seg or seg not in source:
        return None
    new_seg = seg.replace(lit_seg, f"shlex.split({lit_seg})", 1)
    new_seg = new_seg.replace("shell=True", "shell=False", 1)
    if new_seg == seg:
        return None
    return source.replace(seg, new_seg, 1)


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
    (("os.popen", "popen"), _patch_os_popen),
    (("subprocess-shell-literal",), _patch_subprocess_shell_literal),
    (("tls-verify",), _patch_tls_verify),
    (("zip-slip",), _patch_zip_slip),
    (("bare except", "bareexcept"), _patch_bare_except),
    (("base-exception", "baseexception"), _patch_base_exception),
    (("pickle",), _patch_pickle),
    (("sql", "injection"), _patch_sql_injection),
    (("yaml",), _patch_yaml_load),
    (("tempfile", "mktemp"), _patch_mktemp),
    # hashlib-new-weak MUST precede weak-hash: "hashlib" is a substring of the
    # former's label, so the generic weak-hash group would otherwise capture it.
    (("hashlib-new-weak",), _patch_hashlib_new_weak),
    (("weak-hash", "hashlib"), _patch_weak_hash),
)
