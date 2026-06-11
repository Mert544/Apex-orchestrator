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
import re
from dataclasses import dataclass

# Security labels in descending severity (the bridge's contract relies on this).
_SECURITY_ORDER = ("eval", "os.system", "pickle", "yaml", "sql", "tempfile", "weak-hash", "bare except", "base-exception")

# Inline suppression: respect the same comments Bandit/ruff do, so `apex review`
# and the health grade (both built on this detector) agree with the developer's
# explicit acknowledgement instead of re-flagging a line they already silenced.
_SUPPRESS_RE = re.compile(r"#\s*(noqa|nosec)\b(?:\s*[:=]\s*([A-Za-z0-9 ,]+))?", re.IGNORECASE)
# Lint codes that, when named in a suppression comment, suppress a finding.
_FIXKIND_NOQA = {"bare except": "E722", "base-exception": "B036"}


def _suppressed(line: str, category: str, fix_kind: str, message: str) -> bool:
    """True if ``line`` carries a suppression comment covering this finding.

    ``# nosec`` silences security findings; a bare ``# noqa`` silences everything
    on the line; ``# noqa: <codes>`` silences a security finding when an S-code
    is present, a bare-except when E722 is present, and the identity-literal bug
    when F632 is present.
    """
    m = _SUPPRESS_RE.search(line)
    if not m:
        return False
    directive = m.group(1).lower()
    codes_raw = m.group(2)
    if directive == "nosec":
        return category == "security"
    if not codes_raw:  # a bare directive (no codes) disables all lint on the line
        return True
    codes = {c.strip().upper() for c in codes_raw.replace(",", " ").split()}
    if category == "security" and any(c[:1] == "S" and c[1:].isdigit() for c in codes):
        return True
    if _FIXKIND_NOQA.get(fix_kind) in codes:
        return True
    if "F632" in codes and "identity check against a literal" in message:
        return True
    return False


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
            elif "BaseException" in _exc_names(node.type) and not _reraises(node.body):
                # B036: swallows KeyboardInterrupt/SystemExit. A handler that
                # re-raises (bare `raise`) is the legitimate cleanup pattern.
                add(node.lineno, "security", "medium",
                    "except BaseException also catches KeyboardInterrupt/SystemExit — "
                    "use except Exception: (or re-raise)", "base-exception")
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                add(node.lineno, "bug", "medium",
                    "exception silently swallowed (except: pass) — log or handle it", "")
            for lineno in _raise_without_from(node.body):
                add(lineno, "bug", "low",
                    "raising a new exception in an except block without `from` loses the "
                    "original cause — use `raise ... from err` (or `from None`)", "")
        elif isinstance(node, ast.Try):
            for lineno in _escapes_finally(node.finalbody):
                add(lineno, "bug", "high",
                    "return/break/continue in a finally block swallows exceptions and "
                    "overrides control flow", "")
            for lineno in _unreachable_handlers(node.handlers):
                add(lineno, "bug", "high",
                    "unreachable except — a broader handler above already catches this", "")
        elif isinstance(node, ast.Assert) and isinstance(node.test, ast.Tuple) and node.test.elts:
            add(node.lineno, "bug", "high",
                "assert on a tuple is always true — remove the parentheses", "")
        elif (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
              and isinstance(node.operand, ast.Compare) and len(node.operand.ops) == 1
              and isinstance(node.operand.ops[0], (ast.In, ast.Is))):
            kind = "not in" if isinstance(node.operand.ops[0], ast.In) else "is not"
            add(node.lineno, "style", "low",
                f"use `{kind}` instead of negating the comparison (`not ... "
                f"{'in' if kind == 'not in' else 'is'}`)", "negated-comparison")
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
            if any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops) and \
               any(_is_identity_literal(x) for x in node.comparators):
                add(node.lineno, "bug", "medium",
                    "identity check against a literal (`is`/`is not`) is a bug — use ==/!=",
                    "identity-literal")
            for i, op in enumerate(node.ops):
                # Comparing a pure reference with itself is always constant — a
                # likely typo (meant a different operand). `!=`/`==` are excluded:
                # `x != x` / `x == x` are the idiomatic NaN checks.
                if not isinstance(op, (ast.Eq, ast.NotEq)) and _same_ref(operands[i], operands[i + 1]):
                    add(node.lineno, "bug", "medium",
                        "comparison with itself is always constant — likely a typo", "")
                    break
        elif isinstance(node, ast.ClassDef):
            if _is_frozen_dataclass(node):
                for sub in ast.walk(node):
                    targets: list[ast.expr] = []
                    if isinstance(sub, ast.Assign):
                        targets = list(sub.targets)
                    elif isinstance(sub, (ast.AugAssign, ast.AnnAssign)):
                        targets = [sub.target]
                    if any(isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                           and t.value.id == "self" for t in targets):
                        add(sub.lineno, "bug", "high",
                            "assignment to a frozen dataclass field raises FrozenInstanceError "
                            "at runtime — use dataclasses.replace()", "")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _has_mutable_default(node):
                add(node.lineno, "bug", "high", "mutable default argument — shared-state bug", "mutable-default")
            if ast.get_docstring(node) is None and not node.name.startswith("_"):
                add(node.lineno, "docs", "low", f"public function `{node.name}` lacks a docstring", "docstring")

    # Drop findings the developer explicitly suppressed inline (noqa / nosec).
    lines = source.splitlines()
    kept = [
        i for i in out
        if not (1 <= i.line <= len(lines)
                and _suppressed(lines[i.line - 1], i.category, i.fix_kind, i.message))
    ]
    return kept


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


# BaseException subclasses that ``except Exception`` does NOT catch — so a later
# handler for one of these stays reachable.
_BASE_TIER = {"BaseException", "KeyboardInterrupt", "SystemExit", "GeneratorExit"}


def _exc_names(type_node: ast.expr | None) -> list[str]:
    """Simple names of the exception type(s) a handler catches ([] if unknown/bare)."""
    if type_node is None:
        return []
    elts = type_node.elts if isinstance(type_node, ast.Tuple) else [type_node]
    names: list[str] = []
    for e in elts:
        if isinstance(e, ast.Name):
            names.append(e.id)
        elif isinstance(e, ast.Attribute):
            names.append(e.attr)
    return names


def _raise_without_from(body: list) -> list[int]:
    """Lines where an except block constructs+raises a NEW exception without `from`.

    ``raise ValueError(...)`` inside ``except`` discards the original traceback
    chain (flake8-bugbear B904). Only a *constructed* exception (a call) is
    flagged — a bare ``raise`` or ``raise err`` (re-raising the caught value) is
    fine — and nested functions/classes/try blocks have their own context.
    """
    found: list[int] = []

    def walk(stmts: list) -> None:
        for s in stmts:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Try)):
                continue
            if isinstance(s, ast.Raise) and isinstance(s.exc, ast.Call) and s.cause is None:
                found.append(s.lineno)
            elif isinstance(s, (ast.If, ast.For, ast.While, ast.With, ast.AsyncFor, ast.AsyncWith)):
                walk(s.body)
                walk(getattr(s, "orelse", []))
    walk(body)
    return found


def _reraises(body: list) -> bool:
    """True if the handler body re-raises the active exception (bare ``raise``).

    Nested functions are separate scopes — a ``raise`` inside one fires later,
    not during the handler — so they don't count as re-raising.
    """
    stack = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Raise) and node.exc is None:
            return True
        stack.extend(ast.iter_child_nodes(node))
    return False


def _unreachable_handlers(handlers: list) -> list[int]:
    """Line numbers of except clauses shadowed by a broader handler above them.

    ``except BaseException`` shadows everything after it; ``except Exception``
    shadows everything except the BaseException-tier classes it can't catch.
    Handlers whose type we can't read are left alone (no false positives).
    """
    found: list[int] = []
    broad = ""  # "" | "Exception" | "BaseException"
    for h in handlers:
        names = _exc_names(h.type)
        if broad == "BaseException" or (
            broad == "Exception" and names and not all(n in _BASE_TIER for n in names)
        ):
            found.append(h.lineno)
        if h.type is not None:
            if "BaseException" in names:
                broad = "BaseException"
            elif "Exception" in names and broad != "BaseException":
                broad = "Exception"
    return found


def _escapes_finally(finalbody: list) -> list[int]:
    """Line numbers of return/break/continue that escape a ``finally`` block.

    A ``return`` in ``finally`` always swallows a pending exception and discards
    the function's real return; a bare ``break``/``continue`` does the same to a
    loop. Nested functions/classes are separate scopes (their ``return`` is
    fine), break/continue inside a loop *within* the finally are fine, and nested
    ``try`` blocks are reported when ast.walk reaches them (no double counting).
    """
    found: list[int] = []

    def walk_stmts(stmts: list, loop_depth: int) -> None:
        for s in stmts:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Try)):
                continue  # separate scope, or handled when ast.walk reaches it
            if isinstance(s, ast.Return):
                found.append(s.lineno)
            elif isinstance(s, (ast.Break, ast.Continue)) and loop_depth == 0:
                found.append(s.lineno)
            elif isinstance(s, (ast.For, ast.While, ast.AsyncFor)):
                walk_stmts(s.body, loop_depth + 1)
                walk_stmts(s.orelse, loop_depth + 1)
            elif isinstance(s, ast.If):
                walk_stmts(s.body, loop_depth)
                walk_stmts(s.orelse, loop_depth)
            elif isinstance(s, (ast.With, ast.AsyncWith)):
                walk_stmts(s.body, loop_depth)

    walk_stmts(finalbody, 0)
    return found


def _is_frozen_dataclass(node: ast.ClassDef) -> bool:
    """True if the class is decorated ``@dataclass(frozen=True)`` (or dataclasses.dataclass)."""
    for dec in node.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        f = dec.func
        name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
        if name == "dataclass" and any(
            kw.arg == "frozen" and isinstance(kw.value, ast.Constant) and kw.value.value is True
            for kw in dec.keywords
        ):
            return True
    return False


def _same_ref(a: ast.AST, b: ast.AST) -> bool:
    """True if a and b are the *same* pure reference (a name or attribute chain).

    Restricted to Name/Attribute so side-effecting operands (calls, subscripts)
    are never treated as identical — ``f() < f()`` may legitimately differ.
    """
    if not (isinstance(a, (ast.Name, ast.Attribute)) and isinstance(b, (ast.Name, ast.Attribute))):
        return False
    return ast.dump(a) == ast.dump(b)


def _is_identity_literal(node: ast.AST) -> bool:
    """True if ``node`` is a literal that must never be compared with ``is``.

    ``x is 5`` / ``name is "admin"`` only ever work by accident of CPython
    interning — equality (``==``) is meant. ``None`` and bools are excluded:
    ``is None`` / ``is True`` are the correct, idiomatic forms.
    """
    if isinstance(node, ast.Constant):
        return node.value is not None and not isinstance(node.value, bool)
    return isinstance(node, (ast.Tuple, ast.List, ast.Dict, ast.Set))


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


def has_base_exception(source: str) -> bool:
    return any(i.fix_kind == "base-exception" for i in detect(source))


def has_identity_literal(source: str) -> bool:
    return any(i.fix_kind == "identity-literal" for i in detect(source))


def has_negated_comparison(source: str) -> bool:
    return any(i.fix_kind == "negated-comparison" for i in detect(source))


def _assert_is_substantive(test: ast.expr) -> bool:
    """True if an assert checks real behaviour, not just that code loads/has a type.

    Shallow (NOT substantive): a bare truthiness check (``assert mod``), an
    ``is/is not None`` check, or ``isinstance()/callable()/hasattr()``. These
    prove a module imports and returns the right *shape* but not that it is
    *correct*. A value/relational comparison (``==``, ``<``, ``in``, ...), a
    plain function-call assertion, or a negation of any of these is substantive.
    """
    if isinstance(test, (ast.Name, ast.Attribute, ast.Constant)):
        return False
    if isinstance(test, ast.Compare):
        only_none_identity = (
            all(isinstance(op, (ast.Is, ast.IsNot)) for op in test.ops)
            and any(isinstance(c, ast.Constant) and c.value is None
                    for c in [test.left, *test.comparators])
        )
        return not only_none_identity
    if isinstance(test, ast.Call):
        func = test.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else "")
        return name not in ("isinstance", "callable", "hasattr")
    if isinstance(test, ast.BoolOp):
        return any(_assert_is_substantive(v) for v in test.values)
    if isinstance(test, ast.UnaryOp):
        return _assert_is_substantive(test.operand)
    return True


def test_has_substantive_assertions(source: str) -> bool:
    """True if a test module asserts real behaviour, not just imports/types.

    Lets callers tell a genuine test from a shallow characterization stub
    (import-smoke + ``isinstance`` contracts), so 'covered' doesn't get confused
    with 'verified correct'.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(n, ast.Assert) and _assert_is_substantive(n.test)
        for n in ast.walk(tree)
    )


def has_open_without_encoding(source: str) -> bool:
    return any(i.fix_kind == "open-encoding" for i in detect(source))


def has_network_call_without_timeout(source: str) -> bool:
    return any(i.fix_kind == "net-timeout" for i in detect(source))
