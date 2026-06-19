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
import re

# Security labels in descending severity (the bridge's contract relies on this).
# New labels (os.popen, tls-verify, zip-slip, hashlib-new-weak, subprocess-shell-literal)
# slot in by severity; flag-only labels are skipped by the bridge once their marker
# comment is present, exactly like pickle/sql/tempfile/weak-hash.
_SECURITY_ORDER = ("eval", "os.system", "os.popen", "pickle", "subprocess-shell-literal",
                   "tls-verify", "zip-slip", "yaml", "sql", "tempfile", "weak-hash",
                   "hashlib-new-weak", "bare except", "base-exception")

# Inline suppression: respect the same comments Bandit/ruff do, so `apex review`
# and the health grade (both built on this detector) agree with the developer's
# explicit acknowledgement instead of re-flagging a line they already silenced.
_SUPPRESS_RE = re.compile(r"#\s*(noqa|nosec)\b(?:\s*[:=]\s*([A-Za-z0-9 ,]+))?", re.IGNORECASE)
# Lint codes that, when named in a suppression comment, suppress a finding.
_FIXKIND_NOQA = {"bare except": "E722", "base-exception": "B036", "raise-from": "B904",
                 "fstring-no-placeholder": "F541", "collection-literal": "C408"}


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
    return bool("F632" in codes and "identity check against a literal" in message)


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
    """All detectable issues in a source string (line-level).

    Thin dispatcher: a single :func:`ast.walk` routes each node to the cohesive
    per-node-type handler below (``_detect_call``, ``_detect_except_handler``,
    ...). Each handler emits the exact same findings, in the same order, as the
    original monolithic loop did; only the grouping changed. The ``elif`` chain
    here preserves the historical dispatch order, which the suppression filter
    and the byte-for-byte finding contract both depend on.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Issue(exc.lineno or 1, "bug", "high", f"SyntaxError: {exc.msg}", "")]
    except (RecursionError, MemoryError):
        # A pathological file (deeply-nested expression / enormous source) that
        # blows the parser is not analyzable — skip it like a syntax error
        # rather than crashing the whole scan.
        return []

    out: list[Issue] = []

    def add(line: int, cat: str, sev: str, msg: str, fix: str) -> None:
        out.append(Issue(line, cat, sev, msg, fix))

    for lineno in _unreachable_code_lines(tree):
        add(lineno, "bug", "medium", _UNREACHABLE_CODE_MSG, "")

    for node in ast.walk(tree):
        _dispatch_node(node, add)

    # Broadened SQL-injection detection (new sinks / format-taint / concat /
    # assigned-then-passed) needs whole-module context — the assignment map — so
    # it runs as its own pass after the per-node walk. It deliberately skips the
    # historical inline-f-string-on-classic-sink shape, which the per-node rule
    # in _CALL_ATTR_RULES already emits, so no finding is duplicated.
    _detect_sql_injection(tree, add)

    # Drop findings the developer explicitly suppressed inline (noqa / nosec).
    lines = source.splitlines()
    kept = [
        i for i in out
        if not (1 <= i.line <= len(lines)
                and _suppressed(lines[i.line - 1], i.category, i.fix_kind, i.message))
    ]
    return kept


def _dispatch_node(node: ast.AST, add) -> None:
    """Route one AST node to its per-node-type handler.

    The ``elif`` chain preserves the historical dispatch order, which the
    byte-for-byte finding contract depends on. ``add`` is the emit closure from
    :func:`detect` (``add(line, cat, sev, msg, fix)``).
    """
    if isinstance(node, ast.Call):
        _detect_call(node, add)
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        _detect_assignment(node, add)
    elif isinstance(node, ast.ExceptHandler):
        _detect_except_handler(node, add)
    elif isinstance(node, ast.Try):
        _detect_try(node, add)
    elif isinstance(node, ast.Assert):
        _detect_assert(node, add)
    elif isinstance(node, ast.UnaryOp):
        _detect_negated_comparison(node, add)
    elif isinstance(node, ast.Compare):
        _detect_compare(node, add)
    elif isinstance(node, ast.ClassDef):
        _detect_classdef(node, add)
    elif isinstance(node, ast.JoinedStr):
        _detect_fstring(node, add)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        _detect_function(node, add)


# Each ``_detect_*`` below owns one node-type branch lifted verbatim out of the
# dispatcher above. ``add`` is the dispatcher's emit closure
# (``add(line, cat, sev, msg, fix)``); handlers append findings in source order.


def _detect_call(node: ast.Call, add) -> None:
    """Findings for a call node: a network call missing ``timeout=``; the
    ``eval``/``exec``/``open``/empty-collection builtins; and attribute-based
    risks (``os.system``, ``pickle.loads``, ``yaml.load``, ``tempfile.mktemp``,
    weak hashes, SQL f-strings, ``subprocess`` with ``shell=True``).

    The network-timeout check fires independently; the func-shape rules below it
    are mutually exclusive (first match wins, preserving the original ``elif``
    order), split into per-shape helpers so this dispatcher stays small.
    """
    if _is_network_call_without_timeout(node):
        add(node.lineno, "bug", "medium",
            "network call without timeout= can hang forever — pass timeout=...", "net-timeout")
    f = node.func
    if isinstance(f, ast.Attribute) and _is_unguarded_extractall(node, f):
        add(node.lineno, "security", "high",
            "archive extractall() without a member-path guard — a malicious "
            "entry can escape the target dir (Zip-Slip/path traversal); pass "
            "filter=\"data\" (3.12+) or validate each member path", "zip-slip")
    if isinstance(f, ast.Name):
        _detect_call_name(node, f, add)
    elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        _detect_call_attr(node, f, add)


def _is_unguarded_extractall(node: ast.Call, f: ast.Attribute) -> bool:
    """True for an ``.extractall(...)`` call with no member-path guard.

    Conservative, high-precision Zip-Slip / path-traversal detection. Fires only
    on a method literally named ``extractall`` (the tarfile/zipfile API) that
    does NOT constrain which members are written — i.e. passes neither
    ``members=`` (an explicit, presumably-validated member list) nor ``filter=``
    (the 3.12+ extraction-filter guard). A guarded extraction is left alone, so
    safe code never trips this; a ``**kwargs`` smuggle is treated as guarded.
    """
    if f.attr != "extractall":
        return False
    if any(kw.arg is None for kw in node.keywords):       # **kwargs may carry a guard
        return False
    return not any(kw.arg in ("members", "filter") for kw in node.keywords)


def _detect_call_name(node: ast.Call, f: ast.Name, add) -> None:
    """Findings for a ``Name(...)`` call: ``eval``/``exec``, an encoding-less
    text ``open()``, and an empty ``dict``/``list``/``tuple`` constructor. First
    match wins, matching the original ``elif`` ordering."""
    if f.id == "eval":
        add(node.lineno, "security", "high", "eval() — code injection risk", "eval")
    elif f.id == "exec":
        add(node.lineno, "security", "high", "exec() — code injection risk", "")
    elif f.id == "open" and _is_text_open_without_encoding(node):
        add(node.lineno, "bug", "low",
            "open() without encoding= is locale-dependent — pass encoding=\"utf-8\"",
            "open-encoding")
    elif f.id in ("dict", "list", "tuple") and not node.args and not node.keywords:
        lit = {"dict": "{}", "list": "[]", "tuple": "()"}[f.id]
        add(node.lineno, "style", "low",
            f"use a literal `{lit}` instead of `{f.id}()`", "collection-literal")


# DB-API sinks that take a raw SQL string as their first argument. The classic
# DB-API 2.0 cursor verbs (``execute``/``executemany``/``cursor``) plus the
# realistic async/driver fetch verbs (asyncpg / ``databases``:
# ``fetch``/``fetchrow``/``fetchval``/``fetchmany``). A tainted string
# (f-string / ``str.format()`` / concat) reaching any of these is an injection
# risk.
_SQL_CLASSIC_SINKS = frozenset({"execute", "executemany", "cursor"})
_SQL_FETCH_SINKS = frozenset({"fetch", "fetchrow", "fetchval", "fetchmany"})
_SQL_SINKS = _SQL_CLASSIC_SINKS | _SQL_FETCH_SINKS

# Tokens that mark a string as SQL. Used to keep the broadened detection
# (the generically-named ``fetch*`` sinks and the ``.format()`` taint) precise:
# we only flag those when the string literally reads like SQL, so a non-DB
# ``queue.fetch(f"{job}")`` or a ``"{}".format(name)`` greeting is never flagged.
_SQL_KEYWORDS = (
    "select ", "insert ", "update ", "delete ", "from ", "where ", " join ",
    " into ", "values ", "create table", "drop table", "alter table",
    "union ", "order by", "group by",
)


def _looks_like_sql(text: str) -> bool:
    """True if ``text`` reads like a SQL statement (case-insensitive keyword)."""
    low = text.lower()
    return any(kw in low for kw in _SQL_KEYWORDS)


def _joinedstr_static_text(node: ast.JoinedStr) -> str:
    """The literal (non-interpolated) text of an f-string, joined."""
    return "".join(
        v.value for v in node.values
        if isinstance(v, ast.Constant) and isinstance(v.value, str)
    )


def _format_call_template(node: ast.Call) -> str | None:
    """The constant template of a ``"...".format(...)`` call with a TAINTED arg.

    Returns the template string only when the receiver is a string literal and
    at least one ``format()`` argument is non-literal (a name/call/attribute —
    i.e. user-controlled), which is the injection-prone shape. A pure-literal
    ``"a={}".format("b")`` is constant and returns None.
    """
    f = node.func
    if not (isinstance(f, ast.Attribute) and f.attr == "format"):
        return None
    recv = f.value
    if not (isinstance(recv, ast.Constant) and isinstance(recv.value, str)):
        return None
    args = [*node.args, *(kw.value for kw in node.keywords)]
    if not any(not isinstance(a, ast.Constant) for a in args):
        return None
    return recv.value


def _is_tainted_sql_string(arg: ast.expr) -> str | None:
    """The literal SQL text of a tainted query expression, else None.

    Recognizes the three interpolation shapes that build SQL from non-constants:
    an f-string with a placeholder, a ``str.format()`` with a non-literal arg,
    and a ``"..." + var`` style concat with a string-literal side. Returns the
    static portion of the text (for the SQL-look guard); a fully-constant string
    or an unrecognized shape returns None.
    """
    if isinstance(arg, ast.JoinedStr):
        if not any(isinstance(v, ast.FormattedValue) for v in arg.values):
            return None  # f-string with no placeholder is constant
        return _joinedstr_static_text(arg)
    if isinstance(arg, ast.Call):
        return _format_call_template(arg)
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
        for side in (arg.left, arg.right):
            if isinstance(side, ast.Constant) and isinstance(side.value, str):
                return side.value
    return None


def _is_sql_fstring_call(node: ast.Call, owner: str, attr: str) -> bool:
    """True for a DB-cursor ``execute``/``executemany``/``cursor`` call whose
    args include an f-string (SQL built via interpolation — injection risk).

    Unchanged classic-sink rule used by :data:`_CALL_ATTR_RULES`: it fires on the
    historical inline-f-string-on-``execute``/``executemany``/``cursor`` shape so
    the byte-for-byte finding contract is preserved. The broadened detection
    (the ``fetch*`` sinks, ``str.format()``/concat taint, and the
    assigned-then-passed resolver) lives in :func:`_detect_sql_injection`, which
    deliberately skips this exact shape to avoid a duplicate finding.
    """
    return attr in _SQL_CLASSIC_SINKS and any(
        isinstance(a, ast.JoinedStr) for a in node.args)


def _is_shell_true_call(node: ast.Call, owner: str, attr: str) -> bool:
    """True for a ``subprocess`` runner call passing ``shell=True``."""
    return attr in ("run", "call", "Popen", "check_output", "check_call") and any(
        kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in node.keywords)


def _is_weak_hash_call(node: ast.Call, owner: str, attr: str) -> bool:
    """True for ``hashlib.md5``/``sha1`` not declared ``usedforsecurity=False``."""
    return owner == "hashlib" and attr in ("md5", "sha1") and not _has_usedforsecurity_false(node)


# Shell metacharacters that make a command string un-tokenisable by a plain
# ``shlex.split`` (they have shell meaning: redirection, piping, substitution,
# chaining, globbing, quoting). A literal containing ANY of these is left as a
# flag, never rewritten.
_SHELL_METACHARS = frozenset(";&|`$><()*?[]{}~!#\\\"'\n\t")


def _subprocess_runner_attr(attr: str) -> bool:
    return attr in ("run", "call", "Popen", "check_output", "check_call")


def _shell_true_literal_command(node: ast.Call) -> str | None:
    """The safe literal command of a ``shell=True`` runner call, else None.

    Returns the string only when the FIRST positional argument is a plain string
    constant containing no shell metacharacters — the one case where switching to
    ``shell=False`` + ``shlex.split("<literal>")`` is provably behaviour-
    preserving. Anything dynamic, a list, or a metachar-bearing literal returns
    None (so it falls through to the generic flag-only shell=True finding).
    """
    if not (node.args and isinstance(node.args[0], ast.Constant)):
        return None
    value = node.args[0].value
    if not isinstance(value, str):
        return None
    if not value.strip() or any(ch in _SHELL_METACHARS for ch in value):
        return None
    return value


def _is_shell_true_literal_call(node: ast.Call, owner: str, attr: str) -> bool:
    """True for a ``subprocess`` runner with ``shell=True`` and a safe literal cmd."""
    if not (owner == "subprocess" and _subprocess_runner_attr(attr)):
        return False
    if not _has_kw_const_true(node, "shell"):
        return False
    return _shell_true_literal_command(node) is not None


def _has_kw_const_true(node: ast.Call, name: str) -> bool:
    """True if the call passes ``name=True`` as a constant keyword argument."""
    return any(kw.arg == name and isinstance(kw.value, ast.Constant)
               and kw.value.value is True for kw in node.keywords)


def _weak_hash_message(node: ast.Call, owner: str, attr: str) -> str:
    return (f"hashlib.{attr}() is weak for security — use sha256, or pass "
            "usedforsecurity=False if non-security")


def _is_os_popen_call(node: ast.Call, owner: str, attr: str) -> bool:
    """True for ``os.popen(...)`` — deprecated, runs a shell, injection-prone."""
    return owner == "os" and attr == "popen"


# Module names that expose pickle's load API (the stdlib name plus the historical
# ``cPickle`` and the CPython-internal ``_pickle`` accelerator). Loading a pickle
# from an untrusted source is RCE: the unpickler can execute arbitrary code via
# ``__reduce__``. This is the norm for ML model files (``*.pkl``, torch.save).
_PICKLE_MODULES = frozenset({"pickle", "cPickle", "_pickle"})


def _is_pickle_load_call(node: ast.Call, owner: str, attr: str) -> bool:
    """True for ``pickle.load(...)`` / ``pickle.loads(...)`` (incl. cPickle/_pickle).

    Matches the file-stream (``load``) and bytes (``loads``) forms on any of the
    pickle module names. The existing ``pickle.loads`` rule (which routes to the
    flag transform) is ordered ahead of this in :data:`_CALL_ATTR_RULES`, so this
    catch-all only fires for the cases that rule misses: ``pickle.load(f)``, and
    the ``cPickle``/``_pickle`` aliases of either form.
    """
    return owner in _PICKLE_MODULES and attr in ("load", "loads")


def _is_marshal_load_call(node: ast.Call, owner: str, attr: str) -> bool:
    """True for ``marshal.load(...)`` / ``marshal.loads(...)``.

    ``marshal`` is not safe against erroneous or maliciously-constructed data
    (the docs say so explicitly); deserializing untrusted marshal can crash the
    interpreter. Flag-only — there is no safe drop-in replacement.
    """
    return owner == "marshal" and attr in ("load", "loads")


def _has_kw_const_false(node: ast.Call, name: str) -> bool:
    """True if the call passes ``name=False`` as a constant keyword argument."""
    return any(kw.arg == name and isinstance(kw.value, ast.Constant)
               and kw.value.value is False for kw in node.keywords)


# HTTP client modules whose verb calls accept a ``verify=`` TLS toggle.
_TLS_CLIENTS = frozenset({"requests", "httpx"})


def _is_tls_verify_disabled_call(node: ast.Call, owner: str, attr: str) -> bool:
    """True for an HTTP client call that disables TLS verification.

    Fires only on the unambiguous, high-precision form
    ``requests.<verb>(..., verify=False)`` / ``httpx.<verb>(..., verify=False)``
    where the verb is a known network verb and ``verify`` is a literal ``False``.
    A ``verify=True`` (or any non-literal, or a ``**kwargs`` smuggle) is left
    alone, so clean code never trips this.
    """
    if owner not in _TLS_CLIENTS or attr not in _NET_VERBS:
        return False
    return _has_kw_const_false(node, "verify")


def _is_hashlib_new_weak_call(node: ast.Call, owner: str, attr: str) -> bool:
    """True for ``hashlib.new("md5"|"sha1")`` not declared ``usedforsecurity=False``.

    The string-form constructor (``hashlib.new("md5")``) is the sibling of the
    direct ``hashlib.md5()`` weak-hash finding. Only a constant first argument
    naming a weak digest is matched; a dynamic name is left alone (no false
    positive). A call already passing ``usedforsecurity=False`` is safe.
    """
    if not (owner == "hashlib" and attr == "new" and node.args):
        return False
    first = node.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return False
    if first.value.lower() not in ("md5", "sha1"):
        return False
    return not _has_usedforsecurity_false(node)


def _hashlib_new_weak_message(node: ast.Call, owner: str, attr: str) -> str:
    name = node.args[0].value
    return (f'hashlib.new("{name}") is a weak hash for security — use sha256, or '
            "pass usedforsecurity=False if non-security")


# Ordered rule table for an ``owner.attr(...)`` call (``owner`` a plain Name).
# Each rule is (predicate, category, severity, message, fix_kind); the message
# may be a str or a callable ``(node, owner, attr) -> str`` for the one rule that
# interpolates ``attr``. First matching rule wins, preserving the historical
# ``elif`` order the byte-for-byte finding contract depends on.
_CALL_ATTR_RULES = (
    (lambda n, o, a: o == "os" and a == "system",
     "security", "high", "os.system() — prefer subprocess.run()", "os.system"),
    (_is_os_popen_call,
     "security", "high", "os.popen() — runs a shell; prefer subprocess.run()", "os.popen"),
    (lambda n, o, a: o == "pickle" and a == "loads",
     "security", "high", "pickle.loads() — unsafe deserialization", "pickle"),
    (_is_pickle_load_call,
     "security", "high",
     "pickle.load()/loads() of untrusted input executes arbitrary code on "
     "deserialization (RCE) — validate the source or use a safe format "
     "(json/msgpack); no safe drop-in, review manually", ""),
    (_is_marshal_load_call,
     "security", "high",
     "marshal.load()/loads() is unsafe on untrusted input — it can crash the "
     "interpreter; use a safe format and review manually", ""),
    (_is_shell_true_literal_call,
     "security", "high",
     "subprocess shell=True with a literal command — run shell-free with "
     "shlex.split() to remove the injection surface", "subprocess-shell-literal"),
    (_is_tls_verify_disabled_call,
     "security", "high",
     "TLS verification disabled (verify=False) — exposes the connection to "
     "man-in-the-middle attacks", "tls-verify"),
    (lambda n, o, a: o == "yaml" and a == "load",
     "security", "medium", "yaml.load() — prefer yaml.safe_load()", "yaml"),
    (lambda n, o, a: o == "tempfile" and a == "mktemp",
     "security", "medium",
     "tempfile.mktemp() — TOCTOU race; use mkstemp()/NamedTemporaryFile", "tempfile"),
    (_is_weak_hash_call, "security", "medium", _weak_hash_message, "weak-hash"),
    (_is_hashlib_new_weak_call, "security", "medium", _hashlib_new_weak_message, "hashlib-new-weak"),
    (_is_sql_fstring_call,
     "security", "high", "SQL built from an f-string — injection risk", "sql"),
    (_is_shell_true_call,
     "security", "high", "subprocess with shell=True — command injection risk", ""),
)


def _detect_call_attr(node: ast.Call, f: ast.Attribute, add) -> None:
    """Findings for an ``owner.attr(...)`` call (``owner`` a plain Name):
    ``os.system``, ``pickle.loads``, ``yaml.load``, ``tempfile.mktemp``, a weak
    hash, a SQL f-string, or ``subprocess`` with ``shell=True``. Walks
    :data:`_CALL_ATTR_RULES` in order; the first match emits and wins (the same
    first-match semantics as the original ``elif`` chain)."""
    owner, attr = f.value.id, f.attr
    for predicate, category, severity, message, fix_kind in _CALL_ATTR_RULES:
        if predicate(node, owner, attr):
            msg = message(node, owner, attr) if callable(message) else message
            add(node.lineno, category, severity, msg, fix_kind)
            return


# Message/routing reused for every SQL-injection shape, so security_label /
# security_labels (which key on the "sql" fix_kind) keep working unchanged.
_SQL_INJECTION_MSG = "SQL built from an f-string — injection risk"


def _collect_assignments(tree: ast.AST) -> dict[str, ast.expr]:
    """Map ``name -> value`` for every simple ``name = <expr>`` assignment.

    Conservative single-assignment resolver used to follow a query built on one
    line and passed to a sink on the next (``q = f"..."; conn.fetch(q)``). A name
    assigned more than once is dropped (ambiguous), so we never resolve a value
    that may have been overwritten. Module- and function-level assignments share
    one flat map — good enough for the local ``q = ...; sink(q)`` idiom and never
    a false positive (an unresolved name is simply not flagged).
    """
    seen: dict[str, ast.expr] = {}
    multiple: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    if t.id in seen:
                        multiple.add(t.id)
                    seen[t.id] = node.value
    return {k: v for k, v in seen.items() if k not in multiple}


def _sink_attr(node: ast.Call) -> str | None:
    """The SQL-sink method name this call targets, else None."""
    f = node.func
    if isinstance(f, ast.Attribute) and f.attr in _SQL_SINKS:
        return f.attr
    return None


def _tainted_sql_for_sink(arg: ast.expr, attr: str,
                          assigns: dict[str, ast.expr]) -> bool:
    """True if ``arg`` (possibly resolved through one assignment) is tainted SQL
    feeding a sink ``attr``, for a shape NOT already covered by the classic
    inline-f-string rule.

    A bare ``Name`` is resolved once through ``assigns``. Classic sinks skip the
    inline-f-string case (the per-node rule owns it, avoiding a duplicate);
    every other tainted shape on a classic sink, and ALL tainted shapes on the
    generically-named ``fetch*`` sinks, must additionally LOOK like SQL so a
    non-DB ``q.fetch(...)`` or a ``"{}".format(x)`` greeting is never flagged.
    """
    resolved = arg
    if isinstance(arg, ast.Name):
        resolved = assigns.get(arg.id)
        if resolved is None:
            return False
    classic_inline_fstring = (
        attr in _SQL_CLASSIC_SINKS and arg is resolved
        and isinstance(resolved, ast.JoinedStr)
    )
    if classic_inline_fstring:
        return False  # already emitted by the per-node _is_sql_fstring_call rule
    static = _is_tainted_sql_string(resolved)
    if static is None:
        return False
    # Classic sink + inline f-string resolved via a variable is unambiguous SQL
    # already (a cursor sink); everything else must read like SQL to stay precise.
    if attr in _SQL_CLASSIC_SINKS and isinstance(resolved, ast.JoinedStr):
        return True
    return _looks_like_sql(static)


def _detect_sql_injection(tree: ast.AST, add) -> None:
    """Flag tainted SQL reaching a recognized DB sink (the cases the per-node
    inline-f-string rule misses): the async ``fetch*`` sinks, ``str.format()`` /
    concat taint, and a query assigned on one line then passed on the next.

    Reuses the ``"sql"`` fix_kind and message (flag-only — SQL rewrites need
    human review), so existing consumers keyed on that label are unaffected.
    """
    assigns = _collect_assignments(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attr = _sink_attr(node)
        if attr is None or not node.args:
            continue
        if _tainted_sql_for_sink(node.args[0], attr, assigns):
            add(node.lineno, "security", "high", _SQL_INJECTION_MSG, "sql")


# Module/class-level config names whose hardcoded-True is a production-debug
# footgun (Django/Flask DEBUG, generic debug flags). Detected by exact name.
_DEBUG_FLAG_NAMES = frozenset({"DEBUG", "debug"})

_DEBUG_FLAG_MSG = (
    "debug flag hardcoded to True — turn off debug mode in production "
    "(load it from the environment / config)"
)


def _detect_assignment(node, add) -> None:
    """Flag a non-trivial string literal assigned to a secret-looking name, and a
    hardcoded ``DEBUG = True`` / ``debug = True`` production-debug flag."""
    if _is_hardcoded_secret(node):
        add(node.lineno, "security", "high", "possible hardcoded secret — load it from the environment", "")
    _detect_debug_flag(node, add)


def _detect_debug_flag(node, add) -> None:
    """Flag a hardcoded ``DEBUG = True`` / ``debug = True`` (production-debug).

    Fires only when the value is the literal ``True`` (``ast.Constant`` whose
    value ``is True``) assigned to a bare ``DEBUG``/``debug`` name. ``= False``
    is the safe production setting, and ``debug = <call>`` / ``debug = cfg.x``
    are config-driven (not hardcoded), so neither is flagged. Low severity,
    flag-only (the fix — read it from the environment — is contextual).
    """
    if isinstance(node, ast.AnnAssign):
        targets: list[ast.expr] = [node.target]
        value = node.value
    else:
        targets = list(node.targets)
        value = node.value
    if not (isinstance(value, ast.Constant) and value.value is True):
        return
    for t in targets:
        if isinstance(t, ast.Name) and t.id in _DEBUG_FLAG_NAMES:
            add(node.lineno, "bug", "low", _DEBUG_FLAG_MSG, "debug-flag")
            return


def _detect_except_handler(node: ast.ExceptHandler, add) -> None:
    """Findings for one ``except`` clause: bare-except, ``BaseException`` catches,
    silently-swallowed exceptions (the ``pass``-only and broad-silent variants),
    and a new exception raised without ``from``."""
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
    # Broad + silent. A handler that swallows a BROAD type (typed
    # Exception/BaseException, or a tuple containing one) with a body that
    # does nothing — `pass`, `...`, or only a docstring/constant.
    #
    # Non-duplication rule: we deliberately do NOT fire on the bare
    # `except:` case (node.type is None). Bare-except is already covered
    # by the "bare except" security finding above plus the generic
    # "silently swallowed" finding, so adding a third message there would
    # be noisy/confusing. The generic "silently swallowed" finding still
    # fires for a pass-only body of any type (review/maintain depend on
    # its exact wording); this finding adds the distinct broad-scope
    # warning and uniquely covers the `...`/docstring-only silent bodies
    # that the pass-only check misses. Narrow silent passes
    # (`except KeyError: pass`) are intentionally left alone — they are
    # frequently a deliberate best-effort. fix_kind is "" because the
    # correct fix (log / narrow the type / re-raise) is contextual; no
    # single ruff code maps cleanly, so suppression relies on a bare noqa.
    if node.type is not None and _is_broad_exc(node.type) and _is_silent_body(node.body):
        add(node.lineno, "bug", "medium",
            _SILENT_BROAD_EXCEPT_MSG, "")
    for lineno in _raise_without_from(node.body):
        # Auto-fixable only when the handler binds the exception
        # (`except E as err:`) — then `from err` is a pure, safe append.
        add(lineno, "bug", "low",
            "raising a new exception in an except block without `from` loses the "
            "original cause — use `raise ... from err` (or `from None`)",
            "raise-from" if node.name else "")


def _detect_try(node: ast.Try, add) -> None:
    """Findings for a ``try`` node: control flow escaping ``finally`` and an
    ``except`` clause shadowed by a broader handler above it."""
    for lineno in _escapes_finally(node.finalbody):
        add(lineno, "bug", "high",
            "return/break/continue in a finally block swallows exceptions and "
            "overrides control flow", "")
    for lineno in _unreachable_handlers(node.handlers):
        add(lineno, "bug", "high",
            "unreachable except — a broader handler above already catches this", "")


def _detect_assert(node: ast.Assert, add) -> None:
    """Flag ``assert (a, b)`` — a non-empty tuple literal is always truthy, so the
    parentheses turn the assertion into a no-op. Other asserts are left alone."""
    if isinstance(node.test, ast.Tuple) and node.test.elts:
        add(node.lineno, "bug", "high",
            "assert on a tuple is always true — remove the parentheses", "")


def _detect_negated_comparison(node: ast.UnaryOp, add) -> None:
    """Suggest ``not in`` / ``is not`` over a negated membership/identity test.

    Fires only for ``not`` applied to a single-operator ``In``/``Is`` comparison
    (``not x in y`` / ``not x is y``); any other unary op is left alone.
    """
    if not (isinstance(node.op, ast.Not)
            and isinstance(node.operand, ast.Compare) and len(node.operand.ops) == 1
            and isinstance(node.operand.ops[0], (ast.In, ast.Is))):
        return
    kind = "not in" if isinstance(node.operand.ops[0], ast.In) else "is not"
    add(node.lineno, "style", "low",
        f"use `{kind}` instead of negating the comparison (`not ... "
        f"{'in' if kind == 'not in' else 'is'}`)", "negated-comparison")


def _compare_has_eq(node: ast.Compare) -> bool:
    """True if any operator in the comparison is ``==`` or ``!=``."""
    return any(isinstance(o, (ast.Eq, ast.NotEq)) for o in node.ops)


def _compare_eq_none(node: ast.Compare, operands: list[ast.expr]) -> bool:
    """True if an ``==``/``!=`` compares against the ``None`` constant literal."""
    return _compare_has_eq(node) and any(
        isinstance(x, ast.Constant) and x.value is None for x in operands)


def _compare_eq_bool(node: ast.Compare, operands: list[ast.expr]) -> bool:
    """True if an ``==``/``!=`` compares against a ``True``/``False`` literal."""
    return _compare_has_eq(node) and any(
        isinstance(x, ast.Constant) and isinstance(x.value, bool) for x in operands)


def _compare_has_type_call(operands: list[ast.expr]) -> bool:
    """True if any operand is a ``type(...)`` call (suggests isinstance())."""
    return any(isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "type"
               for x in operands)


def _compare_is_identity_literal(node: ast.Compare) -> bool:
    """True if an ``is``/``is not`` operator compares against a forbidden literal."""
    return (any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops)
            and any(_is_identity_literal(x) for x in node.comparators))


def _compare_self_reference(node: ast.Compare, operands: list[ast.expr]) -> bool:
    """True if a non-eq operator compares a pure reference with itself.

    Comparing a pure reference with itself is always constant — a likely typo
    (meant a different operand). ``!=``/``==`` are excluded: ``x != x`` /
    ``x == x`` are the idiomatic NaN checks.
    """
    for i, op in enumerate(node.ops):
        if not isinstance(op, (ast.Eq, ast.NotEq)) and _same_ref(operands[i], operands[i + 1]):
            return True
    return False


def _detect_compare(node: ast.Compare, add) -> None:
    """Findings for a comparison node: ``== None`` / ``== True`` style checks,
    comparing ``type()`` instead of ``isinstance``, identity against a literal,
    and a self-comparison that is always constant (likely a typo)."""
    operands = [node.left, *node.comparators]
    if _compare_eq_none(node, operands):
        add(node.lineno, "style", "low", "compare to None with `is` / `is not`", "none-comparison")
    if _compare_eq_bool(node, operands):
        add(node.lineno, "style", "low",
            "compare to True/False directly (drop `== True` / `== False`)", "")
    if _compare_has_type_call(operands):
        add(node.lineno, "style", "medium", "use isinstance() instead of comparing type()", "")
    if _compare_is_identity_literal(node):
        add(node.lineno, "bug", "medium",
            "identity check against a literal (`is`/`is not`) is a bug — use ==/!=",
            "identity-literal")
    if _compare_self_reference(node, operands):
        add(node.lineno, "bug", "medium",
            "comparison with itself is always constant — likely a typo", "")


def _detect_classdef(node: ast.ClassDef, add) -> None:
    """Findings for a class body: a write to a frozen-dataclass field, and a
    mutable class-level attribute mutated in place (shared across instances)."""
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
    for line, attr in _mutable_class_attribute_lines(node).items():
        add(line, "bug", "medium",
            f"mutable class attribute `{attr}` is shared across all instances and "
            "mutated in place — move it into __init__ (or use default_factory)", "")


def _detect_fstring(node: ast.JoinedStr, add) -> None:
    """Flag an f-string with no interpolation — it is just a string with a
    misleading prefix, so the ``f`` can be dropped (un-doubling braces). An
    f-string that actually interpolates a value is left alone."""
    if not any(isinstance(v, ast.FormattedValue) for v in node.values):
        add(node.lineno, "style", "low",
            "f-string without placeholders — drop the `f` prefix",
            "fstring-no-placeholder")


def _detect_function(node, add) -> None:
    """Findings for a function def: a mutable default argument, and a public
    function missing a docstring."""
    if _has_mutable_default(node):
        add(node.lineno, "bug", "high", "mutable default argument — shared-state bug", "mutable-default")
    if ast.get_docstring(node) is None and not node.name.startswith("_"):
        add(node.lineno, "docs", "low", f"public function `{node.name}` lacks a docstring", "docstring")


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


def _is_builtin_open_with_args(node: ast.Call) -> bool:
    """True if ``node`` calls the builtin ``open`` with at least a path arg."""
    return isinstance(node.func, ast.Name) and node.func.id == "open" and bool(node.args)


def _encoding_is_provable_absent(node: ast.Call) -> bool:
    """True only if no ``encoding=`` and no ``**kwargs`` could supply one."""
    if any(kw.arg is None for kw in node.keywords):
        return False
    return not any(kw.arg == "encoding" for kw in node.keywords)


def _resolve_open_mode_node(node: ast.Call) -> ast.expr | None:
    """The mode argument: positional arg[1] or a ``mode=`` keyword (keyword wins)."""
    mode_node: ast.expr | None = node.args[1] if len(node.args) >= 2 else None
    for kw in node.keywords:
        if kw.arg == "mode":
            mode_node = kw.value
    return mode_node


def _mode_is_provable_text(mode_node: ast.expr | None) -> bool:
    """True if an absent/constant non-binary mode proves the call is text-mode."""
    if mode_node is None:
        return True
    if not (isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str)):
        return False
    return "b" not in mode_node.value


def _is_text_open_without_encoding(node: ast.Call) -> bool:
    """True if ``node`` is a builtin text-mode ``open()`` lacking ``encoding=``.

    Mirrors the open_encoding transform's guard so detection and the fix agree:
    a dynamic/binary mode or an existing ``encoding=`` (or ``**kwargs``) is left
    alone.
    """
    if not _is_builtin_open_with_args(node):
        return False
    if not _encoding_is_provable_absent(node):
        return False
    return _mode_is_provable_text(_resolve_open_mode_node(node))


# BaseException subclasses that ``except Exception`` does NOT catch — so a later
# handler for one of these stays reachable.
_BASE_TIER = {"BaseException", "KeyboardInterrupt", "SystemExit", "GeneratorExit"}


# Stable message for the silent-broad-except finding (fix_kind is "", so the
# query helper and any consumer match on this text rather than a routing code).
_SILENT_BROAD_EXCEPT_MSG = (
    "broad except silently swallows all errors — log it, narrow the type, "
    "or re-raise"
)


# Stable message for the unreachable-code finding (fix_kind is "" — removing dead
# code is a judgment call — so the query helper matches on this text, not a code).
_UNREACHABLE_CODE_MSG = (
    "unreachable code — this runs after an unconditional "
    "return/raise/break/continue"
)


def _is_broad_exc(type_node: ast.expr) -> bool:
    """True if a handler's type catches a BROAD class (Exception/BaseException).

    ``except Exception:`` / ``except BaseException:`` qualify, as does a tuple
    that contains one of them (``except (Exception, OSError):``). A narrow type
    (``KeyError``) or an unreadable/dotted type does not. Bare ``except:`` is
    handled separately by the caller (node.type is None) and never reaches here.
    """
    elts = type_node.elts if isinstance(type_node, ast.Tuple) else [type_node]
    return any(
        isinstance(e, ast.Name) and e.id in ("Exception", "BaseException")
        for e in elts
    )


def _is_silent_body(body: list) -> bool:
    """True if a handler body does nothing but swallow the exception.

    A body is silent when every statement is inert: a ``pass``, a literal
    ``...`` (an ``Expr`` whose value is an Ellipsis constant), or a bare
    docstring/constant expression. Anything that logs, re-raises, or otherwise
    runs code makes the handler non-silent. An empty body cannot occur (Python
    requires at least one statement), so this is always evaluated over >=1 stmt.
    """
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # docstring, `...` (Ellipsis), or any bare constant
        return False
    return True


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


# Statement-list attributes that form an executable block (a sequence where a
# terminal makes its successors dead). ``Try.handlers`` is intentionally absent —
# each ExceptHandler carries its own ``body`` and is visited below.
_BLOCK_FIELDS = ("body", "orelse", "finalbody")

# Unconditional terminals: control never falls through to the next sibling.
_TERMINALS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def _unreachable_code_lines(tree: ast.AST) -> list[int]:
    """Lines of the first dead statement in each block that has one.

    For every executable statement list — a function body, both branches of an
    ``if``, loop bodies/else, ``with`` bodies, the ``try``/``except``/``else``/
    ``finally`` bodies, and the module body — an unconditional terminal
    (``return``/``raise``/``break``/``continue``) that is a *direct* child and not
    the last statement makes the statement immediately after it unreachable. One
    line per such block, reported in document order.

    Conservative by design: a terminal nested inside a child block (e.g. a
    ``return`` guarded by an ``if``) does not make following siblings dead, so
    only direct children are inspected.
    """
    found: list[int] = []

    def scan(block: list) -> None:
        for i, stmt in enumerate(block[:-1]):
            if isinstance(stmt, _TERMINALS):
                found.append(block[i + 1].lineno)
                break  # one finding per block

    for node in ast.walk(tree):
        # ExceptHandler owns a ``body`` but isn't covered by _BLOCK_FIELDS' use of
        # generic getattr on the same set; handle every block-bearing node here.
        for field in _BLOCK_FIELDS:
            block = getattr(node, field, None)
            if isinstance(block, list) and block and all(
                isinstance(s, ast.stmt) for s in block
            ):
                scan(block)
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


_MUTATING_METHODS = frozenset({
    "append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse",
    "update", "add", "discard", "setdefault", "popitem",
    "intersection_update", "difference_update", "symmetric_difference_update",
})


def _is_mutable_constructor(node: ast.AST) -> bool:
    """True for a mutable-collection literal or an empty list()/dict()/set()."""
    if isinstance(node, (ast.List, ast.Dict, ast.Set)):
        return True
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in ("list", "dict", "set")
            and not node.args and not node.keywords)


def _self_attr(node: ast.AST) -> str | None:
    """The attribute name if ``node`` is ``self.<name>``, else None."""
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "self"):
        return node.attr
    return None


def _class_level_mutables(cls: ast.ClassDef) -> dict[str, int]:
    """Direct class-body assignments of a mutable constructor → ``{name: line}``.

    Only the direct class body is scanned (not nested defs).
    """
    class_level: dict[str, int] = {}
    for stmt in cls.body:
        if (isinstance(stmt, ast.Assign)) and (_is_mutable_constructor(stmt.value)):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    class_level[t.id] = stmt.lineno
        if (isinstance(stmt, ast.AnnAssign) and stmt.value is not None) and (isinstance(stmt.target, ast.Name) and _is_mutable_constructor(stmt.value)):
            class_level[stmt.target.id] = stmt.lineno
    return class_level


def _init_reassigned_attrs(cls: ast.ClassDef) -> set[str]:
    """Attribute names reassigned ``self.x = ...`` inside ``__init__`` (per-instance)."""
    reassigned: set[str] = set()
    for sub in ast.walk(cls):
        if isinstance(sub, ast.FunctionDef) and sub.name == "__init__":
            for n in ast.walk(sub):
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        name = _self_attr(t)
                        if name:
                            reassigned.add(name)
    return reassigned


def _in_place_mutated_attr(sub: ast.AST) -> str | None:
    """The ``self.x`` attribute name this node mutates in place, else None.

    Covers ``self.x.append(...)`` and friends, ``self.x[...] = ...`` /
    ``del self.x[...]``, and ``self.x += ...``.
    """
    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
        name = _self_attr(sub.func.value)
        if name and sub.func.attr in _MUTATING_METHODS:
            return name
    elif isinstance(sub, ast.Subscript):
        name = _self_attr(sub.value)
        if name and isinstance(sub.ctx, (ast.Store, ast.Del)):
            return name
    elif isinstance(sub, ast.AugAssign):
        name = _self_attr(sub.target)
        if name:
            return name
    return None


def _mutated_attrs(cls: ast.ClassDef) -> set[str]:
    """Attribute names mutated in place anywhere in the class body."""
    mutated: set[str] = set()
    for sub in ast.walk(cls):
        name = _in_place_mutated_attr(sub)
        if name:
            mutated.add(name)
    return mutated


def _mutable_class_attribute_lines(cls: ast.ClassDef) -> dict[int, str]:
    """Class-level mutable attributes that are MUTATED in place by a method and
    not reassigned per-instance — a shared-state bug (every instance sees the
    same list/dict/set). Conservative: a class-level mutable that is only read,
    or that ``__init__`` reassigns with ``self.x = ...``, is NOT flagged.

    Returns ``{lineno: attr_name}`` for each flagged class-level assignment.
    """
    class_level = _class_level_mutables(cls)
    if not class_level:
        return {}
    reassigned = _init_reassigned_attrs(cls)
    mutated = _mutated_attrs(cls)
    return {line: name for name, line in class_level.items()
            if name in mutated and name not in reassigned}


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
    except (SyntaxError, RecursionError, MemoryError):
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
    except (SyntaxError, RecursionError, MemoryError):
        top = security_label(source)
        return [top] if top else []
    labels = {i.fix_kind for i in detect(source) if i.category == "security" and i.fix_kind}
    return [label for label in _SECURITY_ORDER if label in labels]


def has_mutable_default(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, MemoryError):
        return False
    return any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _has_mutable_default(n)
        for n in ast.walk(tree)
    )


def has_none_comparison(source: str) -> bool:
    return any(i.fix_kind == "none-comparison" for i in detect(source))


def has_base_exception(source: str) -> bool:
    return any(i.fix_kind == "base-exception" for i in detect(source))


def has_silent_broad_except(source: str) -> bool:
    """True if any handler swallows a broad type (Exception/BaseException) silently.

    The finding carries no fix_kind (the fix is contextual), so this matches on
    the stable message text instead of a routing code.
    """
    return any(i.message == _SILENT_BROAD_EXCEPT_MSG for i in detect(source))


def has_unreachable_code(source: str) -> bool:
    """True if any block has statements after an unconditional terminal.

    The finding carries no fix_kind (removing dead code is a judgment call), so
    this matches on the stable message text instead of a routing code.
    """
    return any(i.message == _UNREACHABLE_CODE_MSG for i in detect(source))


def has_fixable_raise_without_from(source: str) -> bool:
    return any(i.fix_kind == "raise-from" for i in detect(source))


def has_identity_literal(source: str) -> bool:
    return any(i.fix_kind == "identity-literal" for i in detect(source))


def has_negated_comparison(source: str) -> bool:
    return any(i.fix_kind == "negated-comparison" for i in detect(source))


def has_fstring_no_placeholder(source: str) -> bool:
    return any(i.fix_kind == "fstring-no-placeholder" for i in detect(source))


def has_collection_literal(source: str) -> bool:
    return any(i.fix_kind == "collection-literal" for i in detect(source))


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
    except (SyntaxError, RecursionError, MemoryError):
        return False
    return any(
        isinstance(n, ast.Assert) and _assert_is_substantive(n.test)
        for n in ast.walk(tree)
    )


def has_open_without_encoding(source: str) -> bool:
    return any(i.fix_kind == "open-encoding" for i in detect(source))


def has_network_call_without_timeout(source: str) -> bool:
    return any(i.fix_kind == "net-timeout" for i in detect(source))


def has_os_popen(source: str) -> bool:
    return any(i.fix_kind == "os.popen" for i in detect(source))


def has_tls_verify_disabled(source: str) -> bool:
    return any(i.fix_kind == "tls-verify" for i in detect(source))


def has_zip_slip(source: str) -> bool:
    return any(i.fix_kind == "zip-slip" for i in detect(source))


def has_hashlib_new_weak(source: str) -> bool:
    return any(i.fix_kind == "hashlib-new-weak" for i in detect(source))


def has_subprocess_shell_literal(source: str) -> bool:
    return any(i.fix_kind == "subprocess-shell-literal" for i in detect(source))


def has_debug_flag(source: str) -> bool:
    """True if a hardcoded ``DEBUG = True`` / ``debug = True`` flag is present."""
    return any(i.fix_kind == "debug-flag" for i in detect(source))
