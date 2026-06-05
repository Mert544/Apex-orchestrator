"""Single source of truth for code-issue detection.

Detection used to live in three places (the diff reviewer, the action bridge's
``_detect_*`` helpers, and scattered scans) with subtly different logic. This
module centralizes it: one AST pass produces a list of :class:`Issue`, and small
helpers derive the specific answers each caller needs. Add a detector here once
and every consumer — review, maintain, the idea seeder — benefits.

Deterministic, stdlib-only (ast).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

# Security labels in descending severity (the bridge's contract relies on this).
_SECURITY_ORDER = ("eval", "os.system", "pickle", "yaml", "sql", "tempfile", "weak-hash", "bare except")


def _has_usedforsecurity_false(node: ast.Call) -> bool:
    """True if the call passes ``usedforsecurity=False`` (declared non-security)."""
    return any(
        kw.arg == "usedforsecurity" and isinstance(kw.value, ast.Constant) and kw.value.value is False
        for kw in node.keywords
    )


@dataclass(frozen=True)
class Issue:
    line: int
    category: str          # security | bug | style | docs
    severity: str          # high | medium | low
    message: str
    fix_kind: str          # routing key for a transform, or "" if not auto-fixable

    @property
    def auto_fixable(self) -> bool:
        return bool(self.fix_kind)


def detect(source: str) -> list[Issue]:
    """All detectable issues in a source string (line-level)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Issue(exc.lineno or 1, "bug", "high", f"SyntaxError: {exc.msg}", "")]

    out: list[Issue] = []

    def add(line: int, cat: str, sev: str, msg: str, fix: str) -> None:
        out.append(Issue(line, cat, sev, msg, fix))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _is_network_call_without_timeout(node):
                add(node.lineno, "bug", "medium",
                    "network call without timeout= can hang forever — pass timeout=...", "net-timeout")
            f = node.func
            if isinstance(f, ast.Name) and f.id == "eval":
                add(node.lineno, "security", "high", "eval() — code injection risk", "eval")
            elif isinstance(f, ast.Name) and f.id == "exec":
                add(node.lineno, "security", "high", "exec() — code injection risk", "")
            elif isinstance(f, ast.Name) and f.id == "open" and _is_text_open_without_encoding(node):
                add(node.lineno, "bug", "low",
                    "open() without encoding= is locale-dependent — pass encoding=\"utf-8\"",
                    "open-encoding")
            elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                owner, attr = f.value.id, f.attr
                if owner == "os" and attr == "system":
                    add(node.lineno, "security", "high", "os.system() — prefer subprocess.run()", "os.system")
                elif owner == "pickle" and attr == "loads":
                    add(node.lineno, "security", "high", "pickle.loads() — unsafe deserialization", "pickle")
                elif owner == "yaml" and attr == "load":
                    add(node.lineno, "security", "medium", "yaml.load() — prefer yaml.safe_load()", "yaml")
                elif owner == "tempfile" and attr == "mktemp":
                    add(node.lineno, "security", "medium",
                        "tempfile.mktemp() — TOCTOU race; use mkstemp()/NamedTemporaryFile", "tempfile")
                elif owner == "hashlib" and attr in ("md5", "sha1") and not _has_usedforsecurity_false(node):
                    add(node.lineno, "security", "medium",
                        f"hashlib.{attr}() is weak for security — use sha256, or pass "
                        "usedforsecurity=False if non-security", "weak-hash")
                elif attr in ("execute", "executemany", "cursor") and any(
                    isinstance(a, ast.JoinedStr) for a in node.args
                ):
                    add(node.lineno, "security", "high", "SQL built from an f-string — injection risk", "sql")
                elif attr in ("run", "call", "Popen", "check_output", "check_call") and any(
                    kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                    for kw in node.keywords
                ):
                    add(node.lineno, "security", "high", "subprocess with shell=True — command injection risk", "")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            if _is_hardcoded_secret(node):
                add(node.lineno, "security", "high", "possible hardcoded secret — load it from the environment", "")
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                add(node.lineno, "security", "medium", "bare except — use except Exception:", "bare except")
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                add(node.lineno, "bug", "medium",
                    "exception silently swallowed (except: pass) — log or handle it", "")
        elif isinstance(node, ast.Assert) and isinstance(node.test, ast.Tuple) and node.test.elts:
            add(node.lineno, "bug", "high",
                "assert on a tuple is always true — remove the parentheses", "")
        elif isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            has_eq = any(isinstance(o, (ast.Eq, ast.NotEq)) for o in node.ops)
            if has_eq and any(isinstance(x, ast.Constant) and x.value is None for x in operands):
                add(node.lineno, "style", "low", "compare to None with `is` / `is not`", "none-comparison")
            if has_eq and any(isinstance(x, ast.Constant) and isinstance(x.value, bool) for x in operands):
                add(node.lineno, "style", "low",
                    "compare to True/False directly (drop `== True` / `== False`)", "")
            if any(isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "type"
                   for x in operands):
                add(node.lineno, "style", "medium", "use isinstance() instead of comparing type()", "")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _has_mutable_default(node):
                add(node.lineno, "bug", "high", "mutable default argument — shared-state bug", "mutable-default")
            if ast.get_docstring(node) is None and not node.name.startswith("_"):
                add(node.lineno, "docs", "low", f"public function `{node.name}` lacks a docstring", "docstring")
    return out


_SECRET_NAMES = ("password", "passwd", "secret", "api_key", "apikey", "token",
                 "access_key", "private_key", "client_secret")
_SECRET_PLACEHOLDERS = {"", "changeme", "example", "test", "your_key_here", "xxx", "none", "todo"}


def _is_hardcoded_secret(node: ast.AST) -> bool:
    """True if this assigns a non-trivial string literal to a secret-looking name."""
    if isinstance(node, ast.AnnAssign):
        targets = [node.target]
        value = node.value
    else:
        targets = node.targets
        value = node.value
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        return False
    if value.value.strip().lower() in _SECRET_PLACEHOLDERS or len(value.value) < 6:
        return False
    for t in targets:
        name = t.id.lower() if isinstance(t, ast.Name) else (
            t.attr.lower() if isinstance(t, ast.Attribute) else "")
        if any(s in name for s in _SECRET_NAMES):
            return True
    return False


# Network verbs shared by ``requests`` and ``httpx`` (and the bare urllib call).
_NET_VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "request"})


def _is_network_call_without_timeout(node: ast.Call) -> bool:
    """True if ``node`` is a blocking network call lacking a ``timeout=`` kwarg.

    Conservative, high-precision detection of Bandit B113 — only the clear cases,
    so an ambiguous ``session.get(...)`` is never flagged:
      - ``requests.<verb>(...)`` / ``httpx.<verb>(...)`` (get/post/.../request),
      - ``urllib.request.urlopen(...)`` and a bare ``urlopen(...)``.
    A call already passing ``timeout=`` (any value) — or smuggling one via
    ``**kwargs`` — is left alone. There is no universally-safe default timeout to
    inject, so this is flag-only (a comment), like the pickle/SQL transforms.
    """
    func = node.func
    if any(kw.arg is None for kw in node.keywords):       # **kwargs could carry timeout
        return False
    if any(kw.arg == "timeout" for kw in node.keywords):
        return False
    if isinstance(func, ast.Name):
        return func.id == "urlopen"
    if not isinstance(func, ast.Attribute):
        return False
    attr, value = func.attr, func.value
    if attr == "urlopen":
        return (isinstance(value, ast.Attribute) and value.attr == "request"
                and isinstance(value.value, ast.Name) and value.value.id == "urllib")
    if attr in _NET_VERBS and isinstance(value, ast.Name):
        return value.id in ("requests", "httpx")
    return False


def _is_text_open_without_encoding(node: ast.Call) -> bool:
    """True if ``node`` is a builtin text-mode ``open()`` lacking ``encoding=``.

    Mirrors the open_encoding transform's guard so detection and the fix agree:
    a dynamic/binary mode or an existing ``encoding=`` (or ``**kwargs``) is left
    alone.
    """
    if not (isinstance(node.func, ast.Name) and node.func.id == "open") or not node.args:
        return False
    if any(kw.arg is None for kw in node.keywords):
        return False
    if any(kw.arg == "encoding" for kw in node.keywords):
        return False
    mode_node: ast.expr | None = node.args[1] if len(node.args) >= 2 else None
    for kw in node.keywords:
        if kw.arg == "mode":
            mode_node = kw.value
    if mode_node is not None:
        if not (isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str)):
            return False
        if "b" in mode_node.value:
            return False
    return True


def _has_mutable_default(func: ast.AST) -> bool:
    defaults = list(func.args.defaults) + [k for k in func.args.kw_defaults if k]
    for d in defaults:
        if isinstance(d, (ast.List, ast.Dict, ast.Set)):
            return True
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                and d.func.id in ("list", "dict", "set") and not d.args and not d.keywords):
            return True
    return False


# --- derived helpers (single-answer queries used by the bridge) --------------

def security_label(source: str) -> str | None:
    """The most severe security issue label present, or None.

    Mirrors the historical contract: AST-based, with a conservative substring
    fallback when the file can't be parsed.
    """
    try:
        ast.parse(source)
    except SyntaxError:
        for needle, label in (
            ("eval(", "eval"), ("os.system(", "os.system"), ("pickle.loads(", "pickle"),
            ("yaml.load(", "yaml"), ("except:", "bare except"),
        ):
            if needle in source:
                return label
        return None
    labels = {i.fix_kind for i in detect(source) if i.category == "security"}
    for label in _SECURITY_ORDER:
        if label in labels:
            return label
    return None


def security_labels(source: str) -> list[str]:
    """All present security labels, most-severe first.

    Unlike :func:`security_label` (which returns only the top one), this lets a
    caller advance past a finding it has already handled — important for
    flag-only fixes (pickle/sql/tempfile/weak-hash) that annotate but do not
    remove the pattern, so the same label would otherwise be returned forever.
    """
    try:
        ast.parse(source)
    except SyntaxError:
        top = security_label(source)
        return [top] if top else []
    labels = {i.fix_kind for i in detect(source) if i.category == "security" and i.fix_kind}
    return [label for label in _SECURITY_ORDER if label in labels]


def has_mutable_default(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _has_mutable_default(n)
        for n in ast.walk(tree)
    )


def has_none_comparison(source: str) -> bool:
    return any(i.fix_kind == "none-comparison" for i in detect(source))


def has_open_without_encoding(source: str) -> bool:
    return any(i.fix_kind == "open-encoding" for i in detect(source))


def has_network_call_without_timeout(source: str) -> bool:
    return any(i.fix_kind == "net-timeout" for i in detect(source))
